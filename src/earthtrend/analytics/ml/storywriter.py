"""Story Lens texts written by an external LLM, checked against the facts
(docs/PLAN_ANALYTICS.md sections 10.4, 11.5, 17).

Team decision (2026-11-14): M4 is not trained; the backend connects an LLM. Analytics
never makes HTTP calls (section 17), so the backend passes its client in as a function
``llm(system, user) -> text``. Here:

1. ``build_messages`` turns ``StoryFacts`` into a system prompt (rules) and a user message
   (the facts as JSON; every number the text may quote is in ``numbers``);
2. the text must pass ``check_numbers`` (numbers within rounding + every mandatory caveat);
3. on failure the LLM gets one repair message listing the wrong numbers / missing caveats;
4. if it still fails, or there is no LLM, or the call raises, the deterministic template
   writer answers (``fallback_reason`` says why). The template never fails.

The number check applies to every author, always.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from earthtrend.analytics.ml.storywriter_check import (
    CAVEAT_MARKERS,
    LANGS,
    Lang,
    NumberCheck,
    check_numbers,
)
from earthtrend.analytics.ml.storywriter_template import (
    TEMPLATE_VERSION,
    caveat_sentence,
    concept_name,
    template_story,
)
from earthtrend.analytics.story.models import StoryFacts

PROMPT_VERSION = "story_llm_prompt_v1"
MAX_ATTEMPTS = 2  # first try + one repair
Method = Literal["llm", "template"]

# llm(system_prompt, user_message) -> text. Supplied by the backend (its LLM client).
LLMComplete = Callable[[str, str], str]


class StoryText(BaseModel):
    text: str
    lang: Lang
    method: Method
    model_version: str  # the backend's LLM label or the template version
    prompt_version: str = PROMPT_VERSION
    attempts: int = 0  # LLM calls made
    fallback_reason: str | None = None  # no_llm, llm_error, failed_number_check
    check: NumberCheck


def facts_payload(facts: StoryFacts, lang: Lang) -> dict[str, Any]:
    """Compact, deterministic view of the facts given to the LLM."""
    m = facts.main
    return {
        "lang": lang,
        "concept": m.concept_id,
        "concept_name": concept_name(m.concept_id, lang),
        "region": m.region_id,
        "season": m.season,
        "period": [m.period_start.year, m.period_end.year]
        if m.period_start and m.period_end
        else None,
        "units": m.units,
        "direction": m.direction,
        "verdict": m.verdict,
        "ruleset": m.ruleset,
        "snr_class": m.snr_class,
        "witnesses": facts.witnesses.status if facts.witnesses else None,
        "alibi": facts.alibi.status if facts.alibi else None,
        "related": [
            {
                "variable": r.variable_id,
                "concept": r.concept_id,
                "direction": r.direction,
                "corr_consistency": r.corr_consistency,
            }
            for r in facts.related
        ],
        "patterns": [p.code for p in facts.patterns],
        "ai_class": facts.ai_opinion.predicted_class if facts.ai_opinion else None,
        "caveats": [{"code": c, "say": caveat_sentence(c, lang)} for c in facts.caveats],
        "numbers": dict(sorted(facts.numbers.items())),
    }


_SYSTEM = {
    "uk": (
        "Ти пишеш короткий текст Story Lens українською для широкої аудиторії (школярі, "
        "вчителі, журналісти) про зміну кліматичної змінної в регіоні. Правила:\n"
        "1. Використовуй ЛИШЕ числа з поля `numbers` (можна округлювати). Не вигадуй чисел.\n"
        "2. Обов'язково згадай кожне застереження з `caveats` (можна своїми словами поруч "
        "із `say`).\n"
        "3. Вирок (`verdict`) передавай точно, не посилюй його. Думка ШІ (`ai_class`) — лише "
        "порада, а не доказ.\n"
        "4. Пов'язані змінні й патерни описуй як асоціацію, не як причину.\n"
        "5. 80–180 слів, без заголовків і списків."
    ),
    "en": (
        "You write a short Story Lens text in English for a general audience (students, "
        "teachers, journalists) about the change of a climate variable in a region. Rules:\n"
        "1. Use ONLY numbers from the `numbers` field (rounding is fine). Never invent numbers.\n"
        "2. Mention every caveat in `caveats` (in your own words, next to `say`).\n"
        "3. Report the `verdict` exactly; never make it stronger. The AI opinion (`ai_class`) "
        "is advice, not evidence.\n"
        "4. Describe related variables and patterns as association, not cause.\n"
        "5. 80-180 words, no headings or lists."
    ),
}


def build_messages(facts: StoryFacts, lang: Lang) -> tuple[str, str]:
    """(system prompt, user message) for the LLM."""
    user = f"[{PROMPT_VERSION}] Facts:\n" + json.dumps(
        facts_payload(facts, lang), ensure_ascii=False, sort_keys=True
    )
    return _SYSTEM[lang], user


def repair_message(previous: str, check: NumberCheck, lang: Lang) -> str:
    """User message for the single repair attempt."""
    parts = []
    if check.unmatched:
        parts.append(
            (
                "Ці числа не з фактів, прибери або заміни їх: "
                if lang == "uk"
                else "These numbers are not in the facts, remove or replace them: "
            )
            + ", ".join(check.unmatched)
        )
    if check.missing_caveats:
        parts.append(
            ("Не згадано застереження: " if lang == "uk" else "Missing caveats: ")
            + ", ".join(check.missing_caveats)
        )
    head = "Виправ текст. " if lang == "uk" else "Fix the text. "
    return head + " ".join(parts) + "\n---\n" + previous


def _template(facts: StoryFacts, lang: Lang, reason: str | None, attempts: int) -> StoryText:
    text = template_story(facts, lang)
    return StoryText(
        text=text,
        lang=lang,
        method="template",
        model_version=TEMPLATE_VERSION,
        attempts=attempts,
        fallback_reason=reason,
        check=check_numbers(text, facts, lang),
    )


def write_story(
    facts: StoryFacts,
    lang: Lang = "uk",
    *,
    llm: LLMComplete | None = None,
    llm_label: str = "external_llm",
    max_attempts: int = MAX_ATTEMPTS,
) -> StoryText:
    """Story Lens text from the LLM if it passes the number check, else the template."""
    if lang not in LANGS:
        raise ValueError(f"unsupported language {lang!r}")
    if llm is None:
        return _template(facts, lang, "no_llm", 0)
    system, user = build_messages(facts, lang)
    attempts = 0
    message = user
    while attempts < max(1, max_attempts):
        attempts += 1
        try:
            text = llm(system, message).strip()
        except Exception:  # noqa: BLE001 - any client failure falls back to the template
            return _template(facts, lang, "llm_error", attempts)
        check = check_numbers(text, facts, lang)
        if check.passed:
            return StoryText(
                text=text,
                lang=lang,
                method="llm",
                model_version=llm_label,
                attempts=attempts,
                check=check,
            )
        message = user + "\n\n" + repair_message(text, check, lang)
    return _template(facts, lang, "failed_number_check", attempts)


__all__ = [
    "CAVEAT_MARKERS",
    "LLMComplete",
    "MAX_ATTEMPTS",
    "PROMPT_VERSION",
    "StoryText",
    "build_messages",
    "check_numbers",
    "facts_payload",
    "repair_message",
    "template_story",
    "write_story",
]
