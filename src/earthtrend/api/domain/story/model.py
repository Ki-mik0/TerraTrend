"""A story is text built only from StoryFacts. Every number in the text must be one of the facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from earthtrend.api.domain.shared.numbers import collect_numbers, numbers_in

LANGUAGES = frozenset({"uk", "en"})
SOURCES = frozenset({"m4", "model", "template", "demo", "cache"})
CORRELATION_CAVEAT = "correlation_not_causation"

ERRORS: dict[str, dict[str, str]] = {
    "case_not_found": {"uk": "Справу не знайдено", "en": "Case not found"},
    "data_not_ready": {"uk": "Факти справи ще не пораховано", "en": "The case facts are not computed yet"},
    "variable_not_found": {"uk": "Змінної немає в каталозі", "en": "The variable is not in the catalog"},
    "region_not_found": {"uk": "Регіону немає в каталозі", "en": "The region is not in the catalog"},
    "language_unknown": {"uk": "Мова має бути uk або en", "en": "Language must be uk or en"},
}

_DIRECTION = {
    "uk": {"increasing": "зростає", "decreasing": "спадає"},
    "en": {"increasing": "is increasing", "decreasing": "is decreasing"},
}
_NO_TREND = {"uk": "без вираженого тренду", "en": "shows no clear trend"}
_PATTERNS = {
    "uk": {
        "drying": "висихання",
        "warming": "потепління",
        "greening": "озеленення",
        "wetting": "зволоження",
        "cooling": "похолодання",
    },
    "en": {
        "drying": "drying",
        "warming": "warming",
        "greening": "greening",
        "wetting": "wetting",
        "cooling": "cooling",
    },
}


class StoryError(Exception):
    def __init__(self, code: str, message: str | None = None, *, language: str = "uk") -> None:
        self.code = code
        self.message = message or ERRORS.get(code, {}).get(language, code)
        super().__init__(self.message)


def require_language(language: str) -> str:
    if language not in LANGUAGES:
        raise StoryError("language_unknown")
    return language


@dataclass(frozen=True)
class RelatedVariable:
    """A co-participant in the process graph. `partial_r` and `lag_months` come from analytics."""

    variable_id: str
    role: str
    lag_months: int = 0
    partial_r: float | None = None
    name: str = ""


@dataclass(frozen=True)
class Paper:
    title: str
    url: str
    doi: str = ""


@dataclass(frozen=True)
class StoryFacts:
    variable_id: str
    region_id: str
    direction: str
    slope_decade: float
    pattern: str
    related: tuple[RelatedVariable, ...] = ()
    patterns: tuple[str, ...] = ()
    alibi: tuple[float, float] | None = None
    witnesses: tuple[int, int] | None = None
    papers: tuple[Paper, ...] = ()
    caveats: tuple[str, ...] = ()
    versions: dict[str, str] = field(default_factory=dict, hash=False)
    variable_name: str = ""
    region_name: str = ""

    def allowed_numbers(self) -> set[str]:
        """Numbers a text may use: the computed values, never ids, paper titles, URLs or DOIs."""
        values: list[Any] = [self.slope_decade, self.alibi, self.witnesses]
        values += [(item.lag_months, item.partial_r) for item in self.related]
        return collect_numbers(values)

    def all_caveats(self) -> tuple[str, ...]:
        caveats = list(self.caveats)
        if self.related and CORRELATION_CAVEAT not in caveats:
            caveats.append(CORRELATION_CAVEAT)
        return tuple(caveats)

    def cache_tag(self) -> str:
        return ",".join(f"{key}={self.versions[key]}" for key in sorted(self.versions)) or "none"


@dataclass(frozen=True)
class Draft:
    """Text a narrator wrote, and which narrator wrote it."""

    text: str
    source: str


@dataclass
class Story:
    id: str
    language: str
    text: str
    facts: StoryFacts
    case_id: str | None = None
    cached: bool = False
    title: str = ""
    source: str = "template"
    warnings: list[str] = field(default_factory=list)

    @property
    def caveats(self) -> tuple[str, ...]:
        return self.facts.all_caveats()

    def uses_only_fact_numbers(self) -> bool:
        return numbers_in(self.text) <= self.facts.allowed_numbers()


def draft_fits(draft: str, facts: StoryFacts) -> bool:
    return bool(draft.strip()) and numbers_in(draft) <= facts.allowed_numbers()


def keep_or_template(draft: str, facts: StoryFacts, language: str) -> tuple[str, bool]:
    """The draft if every number in it is a fact, else the template built from the facts."""
    if draft_fits(draft, facts):
        return draft, True
    return template_text(facts, language), False


def _direction(facts: StoryFacts, language: str) -> str:
    return _DIRECTION[language].get(facts.direction, _NO_TREND[language])


def _pattern(code: str, language: str) -> str:
    return _PATTERNS[language].get(code, code)


def story_title(facts: StoryFacts, language: str) -> str:
    variable = facts.variable_name or facts.variable_id
    region = facts.region_name or facts.region_id
    return f"{variable} · {region}: {_pattern(facts.pattern, language)}"


def template_text(facts: StoryFacts, language: str) -> str:
    variable = facts.variable_name or facts.variable_id
    region = facts.region_name or facts.region_id
    uk = language == "uk"
    if uk:
        parts = [f"{variable} у регіоні {region} {_direction(facts, language)}: {facts.slope_decade} за десятиліття."]
        parts.append(f"Патерн: {_pattern(facts.pattern, language)}.")
    else:
        parts = [f"{variable} in {region} {_direction(facts, language)}: {facts.slope_decade} per decade."]
        parts.append(f"Pattern: {_pattern(facts.pattern, language)}.")
    if facts.related:
        names = ", ".join(_related_text(item, language) for item in facts.related)
        parts.append(f"Співучасники: {names}." if uk else f"Co-participants: {names}.")
    if facts.alibi is not None:
        raw, adjusted = facts.alibi
        parts.append(
            f"Алібі: без впливу ENSO нахил {adjusted} замість {raw}."
            if uk
            else f"Alibi: without ENSO the slope is {adjusted} instead of {raw}."
        )
    if facts.witnesses is not None:
        confirmed, total = facts.witnesses
        parts.append(
            f"Свідки: {confirmed} з {total} підтверджують тренд."
            if uk
            else f"Witnesses: {confirmed} of {total} confirm the trend."
        )
    if CORRELATION_CAVEAT in facts.all_caveats():
        parts.append("Кореляція не є причинністю." if uk else "Correlation is not causation.")
    return " ".join(parts)


def _related_text(item: RelatedVariable, language: str) -> str:
    name = item.name or item.variable_id
    if item.lag_months:
        return f"{name} (затримка {item.lag_months} міс.)" if language == "uk" else f"{name} (lag {item.lag_months} mo)"
    return name


def facts_to_dict(facts: StoryFacts) -> dict[str, Any]:
    return {
        "variable_id": facts.variable_id,
        "region_id": facts.region_id,
        "direction": facts.direction,
        "slope_decade": facts.slope_decade,
        "pattern": facts.pattern,
        "related": [
            {
                "variable_id": item.variable_id,
                "role": item.role,
                "lag_months": item.lag_months,
                "partial_r": item.partial_r,
                "name": item.name,
            }
            for item in facts.related
        ],
        "patterns": list(facts.patterns),
        "alibi": None if facts.alibi is None else list(facts.alibi),
        "witnesses": None if facts.witnesses is None else list(facts.witnesses),
        "papers": [{"title": paper.title, "url": paper.url, "doi": paper.doi} for paper in facts.papers],
        "caveats": list(facts.caveats),
        "versions": dict(facts.versions),
        "variable_name": facts.variable_name,
        "region_name": facts.region_name,
    }


def facts_from_dict(body: dict[str, Any]) -> StoryFacts:
    alibi = body.get("alibi")
    witnesses = body.get("witnesses")
    return StoryFacts(
        variable_id=body["variable_id"],
        region_id=body["region_id"],
        direction=body["direction"],
        slope_decade=body["slope_decade"],
        pattern=body["pattern"],
        related=tuple(RelatedVariable(**item) for item in body.get("related", [])),
        patterns=tuple(body.get("patterns", [])),
        alibi=None if alibi is None else (alibi[0], alibi[1]),
        witnesses=None if witnesses is None else (witnesses[0], witnesses[1]),
        papers=tuple(Paper(**item) for item in body.get("papers", [])),
        caveats=tuple(body.get("caveats", [])),
        versions=dict(body.get("versions", {})),
        variable_name=body.get("variable_name", ""),
        region_name=body.get("region_name", ""),
    )
