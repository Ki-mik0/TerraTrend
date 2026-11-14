"""Number check of story texts (docs/PLAN_ANALYTICS.md sections 10.4 and 11.5).

Every number written in a story must come from ``StoryFacts`` (within the rounding the text
uses), and every mandatory caveat of the case must be mentioned. The check applies to any
author: the template writer, an external LLM or the M4 model.

What counts as a number: a run of digits, optionally with one decimal point or decimal comma
(``0.31``, ``0,31``), optionally with an explicit sign (``+0.3``, ``-0.3``, ``−0.3``) and a
trailing ``%``. Digits glued to letters or underscores are part of an identifier and are
ignored (``nino34``, ``gpcp_v3``, ``NO₂``, ``m-2`` in units).

A number matches a fact value ``v`` when:

* it equals ``v`` or ``|v|`` rounded to the decimals the text shows (an explicit sign must
  match the sign of ``v``; without a sign the direction words carry it);
* with ``%`` it may also be a share: ``72%`` matches ``0.72`` (probabilities, confidences);
* after ``<`` / ``≤`` it is a bound: ``p < 0.001`` holds when some p-value fact is below it;
* it is a year inside the analysed period, or one of ``ALLOWED_CONSTANTS`` (``10`` as in
  "per 10 years", ``90``/``95`` as in "95% interval", ``100`` as in "78 of 100").

Mandatory caveats are found by regular expressions per language (``CAVEAT_MARKERS``); a code
without markers must appear literally. Pure Python: no ML dependencies.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from earthtrend.analytics.story.models import StoryFacts

Lang = Literal["uk", "en"]
LANGS: tuple[Lang, ...] = ("uk", "en")
ALLOWED_CONSTANTS = (10.0, 90.0, 95.0, 100.0)
_EPS = 1e-9

_SIGNS = "+-−"  # plus, hyphen-minus, minus sign
# sign: only at a word start (not "m-2", not the dash of "1985-2020");
# digits: not glued to a word, a decimal point or a sign glued to a letter.
NUMBER_RE = re.compile(
    rf"(?:(?<![\w.,])([{_SIGNS}]))?"
    rf"(?<![\w.,])(?<![^\W\d_][{_SIGNS}])"
    r"(\d+(?:[.,]\d+)?)"
    r"(?!\w)(?![.,]\d)"
    r"(\s?%)?"
)
_BOUND_RE = re.compile(r"(<|≤|менше\s+ніж|менше\s+за|less\s+than|below)\s*$", re.IGNORECASE)

_DIS = r"(?:розход|не\s+погодж|супереч|відрізня)"
_DIS_EN = r"(?:disagree|diverg|contradict|differ)"
_GAP = r"\W+(?:\w+\W+){0,4}"

# code -> {lang: regexes}; any regex found => the caveat is mentioned.
CAVEAT_MARKERS: dict[str, dict[str, tuple[str, ...]]] = {
    "many_gaps": {"uk": (r"пропуск",), "en": (r"\bgaps?\b", r"missing\s+(?:data|values|months)")},
    "low_stable_coverage": {"uk": (r"покритт",), "en": (r"coverage",)},
    "possible_artifact": {"uk": (r"артефакт",), "en": (r"artifact", r"artefact")},
    "methods_disagree": {
        "uk": (rf"(?:метод|тест)\w*{_GAP}{_DIS}",),
        "en": (rf"(?:methods|tests){_GAP}{_DIS_EN}",),
    },
    "witnesses_disagree": {
        "uk": (rf"свідк\w*{_GAP}{_DIS}",),
        "en": (rf"witness\w*{_GAP}{_DIS_EN}",),
    },
    "period_sensitive": {
        "uk": (rf"чутлив\w*{_GAP}період",),
        "en": (rf"sensitive{_GAP}period",),
    },
    "influential_year": {
        "uk": (r"(?:один|одного|окрем\w*|впливов\w*)\s+р(?:ік|оку)",),
        "en": (r"(?:single|one|influential)\s+year",),
    },
    "index_trend_overlap": {
        "uk": (rf"індекс\w*{_GAP}(?:перекрива|власн\w*\s+тренд)",),
        "en": (rf"index{_GAP}(?:overlap|own\s+trend)",),
    },
    "explained_by_enso": {
        "uk": (r"ENSO", r"Ель[\s-]Ніньйо"),
        "en": (r"ENSO", r"El\s+Ni[ñn]o"),
    },
    "long_memory": {"uk": (r"довг\w*\s+пам",), "en": (r"long[\s-]+memory",)},
    "split_region": {
        "uk": (r"частин\w*\s+регіон",),
        "en": (r"parts?\s+of\s+the\s+region",),
    },
    "ai_disagrees": {
        "uk": (rf"ШІ{_GAP}{_DIS}",),
        "en": (rf"\bAI{_GAP}{_DIS_EN}",),
    },
    "short_record": {
        "uk": (r"закоротк", r"коротк\w*\s+ряд"),
        "en": (r"too\s+short", r"short\s+record"),
    },
    "outliers": {"uk": (r"викид",), "en": (r"outlier",)},
    "low_n_eff": {
        "uk": (r"ефективн\w*\s+обсяг",),
        "en": (r"effective\s+sample",),
    },
}


class NumberCheck(BaseModel):
    """Result of ``check_numbers``: ``passed`` only with no unmatched number and no missing
    caveat."""

    passed: bool
    n_numbers: int
    unmatched: list[str] = Field(default_factory=list)  # numbers as written in the text
    missing_caveats: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class FoundNumber:
    raw: str
    value: float
    decimals: int
    sign: int  # +1 / -1 explicit, 0 when not written
    percent: bool
    bound: bool  # preceded by "<" / "≤" / "less than"


def extract_numbers(text: str) -> list[FoundNumber]:
    out: list[FoundNumber] = []
    for m in NUMBER_RE.finditer(text):
        sign_s, digits, pct = m.group(1), m.group(2), m.group(3)
        frac = re.split(r"[.,]", digits)
        decimals = len(frac[1]) if len(frac) > 1 else 0
        value = float(digits.replace(",", "."))
        sign = 0 if not sign_s else (1 if sign_s == "+" else -1)
        bound = _BOUND_RE.search(text[: m.start()]) is not None
        out.append(FoundNumber(m.group(0).strip(), value, decimals, sign, bool(pct), bound))
    return out


def _close(x: float, v: float, decimals: int) -> bool:
    tol = 0.5 * 10.0**-decimals + _EPS * max(1.0, abs(v))
    return abs(x - v) <= tol


def _matches(n: FoundNumber, values: Iterable[float], p_values: list[float]) -> bool:
    signed = n.value * n.sign if n.sign else n.value
    for v in values:
        targets = [v * 100.0] if n.percent else []
        targets.append(v)
        for t in targets:
            if n.sign:
                if _close(signed, t, n.decimals):
                    return True
            elif _close(n.value, t, n.decimals) or _close(n.value, abs(t), n.decimals):
                return True
    return n.bound and any(p < n.value + _EPS for p in p_values)


def _allowed_values(facts: StoryFacts) -> tuple[list[float], list[float]]:
    values = [float(v) for v in facts.numbers.values() if math.isfinite(v)]
    p_values = [
        float(v)
        for k, v in facts.numbers.items()
        if k.rsplit(".", 1)[-1] in ("p_mk", "p_ols", "p_ols_annual", "corr_p", "partial_p")
        or k.endswith("p_adjusted")
    ]
    return values, p_values


def _period_years(facts: StoryFacts) -> set[int]:
    start, end = facts.main.period_start, facts.main.period_end
    if start is None or end is None:
        return set()
    return set(range(start.year, end.year + 1))


def caveat_mentioned(code: str, text: str, lang: Lang) -> bool:
    patterns = CAVEAT_MARKERS.get(code, {}).get(lang)
    if not patterns:
        return code in text or code.replace("_", " ") in text.lower()
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _strip_units(text: str, units: str) -> str:
    # Units like "kg m-2 s-1" are a fact themselves; digits inside them are not numbers.
    if units and any(c.isalpha() for c in units) and any(c.isdigit() for c in units):
        return text.replace(units, " ")
    return text


def check_numbers(text: str, facts: StoryFacts, lang: Lang = "uk") -> NumberCheck:
    """Check a story text against its facts (any author). See the module docstring."""
    body = _strip_units(text, facts.main.units)
    values, p_values = _allowed_values(facts)
    years = _period_years(facts)
    unmatched: list[str] = []
    found = extract_numbers(body)
    for n in found:
        if n.decimals == 0 and not n.sign and not n.percent and not n.bound:
            if int(n.value) in years or n.value in ALLOWED_CONSTANTS:
                continue
        if n.percent and not n.sign and n.value in ALLOWED_CONSTANTS:
            continue  # "95% interval"
        if not _matches(n, values, p_values):
            unmatched.append(n.raw)
    missing = [c for c in facts.caveats if not caveat_mentioned(c, text, lang)]
    return NumberCheck(
        passed=not unmatched and not missing,
        n_numbers=len(found),
        unmatched=unmatched,
        missing_caveats=missing,
    )


__all__ = [
    "ALLOWED_CONSTANTS",
    "CAVEAT_MARKERS",
    "LANGS",
    "FoundNumber",
    "Lang",
    "NumberCheck",
    "caveat_mentioned",
    "check_numbers",
    "extract_numbers",
]
