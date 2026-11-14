"""Assistant exchange and the rules that keep its plan and answer inside the facts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from earthtrend.api.domain.shared.numbers import collect_numbers, normalize_number, numbers_in  # noqa: F401  re-exported

ALLOWED_TOOLS = frozenset(
    {
        "search_variables",
        "get_variable",
        "search_regions",
        "analyze_case",
        "get_evidence",
        "get_profile",
        "get_urban",
        "compare_cases",
        "get_story",
        "get_radar",
    }
)
CASE_TOOLS = frozenset({"get_evidence", "get_profile", "get_urban", "get_story"})
MODES = frozenset({"investigate", "teach"})
LANGUAGES = frozenset({"uk", "en"})
STATUSES = frozenset({"running", "answered", "failed"})
NOTE_ROLES = frozenset({"user", "teacher", "admin"})
MAX_STEPS = 8
VERDICT_WORDS = frozenset(
    {"proven", "strong", "likely", "suspicious", "no_evidence", "inadmissible", "доведено", "вирок"}
)


_INVENTED_KEYS = frozenset(
    {"p_value", "p_mk", "p_ols", "slope", "slope_decade", "snr", "correlation", "q_fdr"}
)

MESSAGES: dict[str, dict[str, str]] = {
    "uk": {
        "tool_not_allowed": "Інструмент {tool} не дозволений",
        "variable_not_in_catalog": "Змінна {value} відсутня в каталозі",
        "region_not_in_catalog": "Регіон {value} відсутній у каталозі",
        "model_invented_number": "Крок плану містить число, яке назвала модель",
        "plan_too_long": "План довший за {value} кроків, зайве відкинуто",
        "case_required": "Крок {tool} потребує справи, але справи ще немає",
        "tool_failed": "Інструмент {tool} повернув помилку {value}",
        "answer_outside_facts": "Відповідь містила число поза фактами",
        "teach_rejected": "Навчальна відповідь не була запитанням",
        "rate_limited": "Забагато запитань. Спробуйте за хвилину",
        "exchange_not_found": "Розмову не знайдено",
        "mode_unknown": "Невідомий режим {value}",
        "language_unknown": "Невідома мова {value}",
        "no_evidence": "Недостатньо доказів у каталозі.",
        "facts_only": "Висновок зібрано лише з фактів справи {value}.",
        "teach_default": "Що, на твою думку, могло б пояснити цей тренд, окрім зміни клімату?",
    },
    "en": {
        "tool_not_allowed": "Tool {tool} is not allowed",
        "variable_not_in_catalog": "Variable {value} is not in the catalog",
        "region_not_in_catalog": "Region {value} is not in the catalog",
        "model_invented_number": "A plan step contains a number the model made up",
        "plan_too_long": "The plan is longer than {value} steps, the rest was dropped",
        "case_required": "Step {tool} needs a case, but no case exists yet",
        "tool_failed": "Tool {tool} returned error {value}",
        "answer_outside_facts": "The answer had a number outside the facts",
        "teach_rejected": "The teaching answer was not a question",
        "rate_limited": "Too many questions. Try again in a minute",
        "exchange_not_found": "Conversation not found",
        "mode_unknown": "Unknown mode {value}",
        "language_unknown": "Unknown language {value}",
        "no_evidence": "Not enough evidence in the catalog.",
        "facts_only": "The conclusion uses only the facts of case {value}.",
        "teach_default": "What else, besides a changing climate, could explain this trend?",
    },
}


def message(code: str, language: str = "uk", **params: Any) -> str:
    table = MESSAGES.get(language, MESSAGES["uk"])
    return table[code].format(tool=params.get("tool", ""), value=params.get("value", ""))


class ExchangeError(Exception):
    def __init__(self, code: str, language: str = "uk", **params: Any) -> None:
        self.code = code
        self.message = message(code, language, **params)
        super().__init__(self.message)


@dataclass(frozen=True)
class ToolStep:
    tool: str
    reason: str
    input: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {"tool": self.tool, "reason": self.reason, "input": dict(self.input)}


@dataclass
class AssistantExchange:
    question: str
    language: str
    role: str
    owner_id: str = ""
    mode: str = "investigate"
    id: str = ""
    created_at: datetime | None = None
    status: str = "running"
    steps: list[ToolStep] = field(default_factory=list)
    case_ids: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ExchangeError("mode_unknown", value=self.mode)
        if self.language not in LANGUAGES:
            raise ExchangeError("language_unknown", value=self.language)

    @property
    def writes_note(self) -> bool:
        return self.role in NOTE_ROLES

    def warn(self, code: str, **params: Any) -> None:
        self.warnings.append(message(code, self.language, **params))

    def add_case(self, case_id: str) -> None:
        if case_id not in self.case_ids:
            self.case_ids.append(case_id)

    def cite(self, citation: dict[str, Any]) -> None:
        """One citation per case: later tools add fields to it, never a duplicate."""
        for existing in self.citations:
            if existing.get("case_id") == citation.get("case_id"):
                existing.update({key: value for key, value in citation.items() if key not in existing})
                return
        self.citations.append(dict(citation))

    def finish(self, answer: str) -> None:
        self.answer = answer
        self.status = "answered"

    def fail(self) -> None:
        self.status = "failed"


def _has_invented_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(_INVENTED_KEYS.intersection(value)) or any(_has_invented_key(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_invented_key(item) for item in value)
    return False


def check_step(step: ToolStep, catalog_ids: set[str], region_ids: set[str] | None = None) -> None:
    if step.tool not in ALLOWED_TOOLS:
        raise ExchangeError("tool_not_allowed", tool=step.tool)
    variable_id = step.input.get("variable_id")
    if variable_id is not None and variable_id not in catalog_ids:
        raise ExchangeError("variable_not_in_catalog", value=variable_id)
    region_id = step.input.get("region_id")
    if region_ids is not None and region_id is not None and region_id not in region_ids:
        raise ExchangeError("region_not_in_catalog", value=region_id)
    if _has_invented_key(step.input):
        raise ExchangeError("model_invented_number")


def accept_plan(
    exchange: AssistantExchange,
    proposed: list[ToolStep],
    catalog_ids: set[str],
    region_ids: set[str] | None = None,
) -> list[ToolStep]:
    accepted: list[ToolStep] = []
    for step in proposed:
        try:
            check_step(step, catalog_ids, region_ids)
        except ExchangeError as error:
            exchange.warnings.append(message(error.code, exchange.language, tool=step.tool, value=_value(error, step)))
            continue
        if len(accepted) == MAX_STEPS:
            exchange.warn("plan_too_long", value=MAX_STEPS)
            break
        accepted.append(step)
    return accepted


def _value(error: ExchangeError, step: ToolStep) -> Any:
    if error.code == "variable_not_in_catalog":
        return step.input.get("variable_id")
    if error.code == "region_not_in_catalog":
        return step.input.get("region_id")
    return ""


def answer_stays_inside_facts(text: str, allowed: set[str]) -> bool:
    return numbers_in(text) <= allowed


def teach_answer_ok(text: str) -> bool:
    stripped = text.strip()
    if not stripped.endswith("?"):
        return False
    words = set(re.findall(r"[\w’']+", stripped.casefold()))
    return not (words & VERDICT_WORDS)


def fallback_answer(exchange: AssistantExchange) -> str:
    if exchange.mode == "teach":
        return message("teach_default", exchange.language)
    if not exchange.case_ids:
        return message("no_evidence", exchange.language)
    return message("facts_only", exchange.language, value=", ".join(exchange.case_ids))


def split_chunks(text: str) -> list[str]:
    parts = re.findall(r"[^.!?]+[.!?]*\s*", text)
    return [part for part in parts if part.strip()] or [text]
