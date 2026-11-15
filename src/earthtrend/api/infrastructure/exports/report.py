"""Everything an export shows, gathered once from the stored case.

Numbers come from the case and its evidence protocol; the sentences and check thresholds match the
case page (web/src/explain.ts) so a downloaded report says what the screen says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from statistics import mean
from typing import Any

from earthtrend.api.domain.cases.model import Case

SIGNIFICANT = {"proven", "strong", "likely"}

VERDICTS: dict[str, tuple[str, str, str, str]] = {
    # code: (label uk, meaning uk, label en, meaning en)
    "proven": ("Доведено", "Тренд підтверджують усі перевірки: статистика, свідки, стійкість і алібі.", "Proven", "Every check agrees: statistics, witnesses, robustness and the alibi."),
    "strong": ("Сильні докази", "Статистика однозначна, і щонайменше дві інші перевірки її підтримують.", "Strong evidence", "The statistics are clear and at least two other checks back them."),
    "likely": ("Ймовірно", "Статистика за тренд, але свідки чи стійкість ще сумніваються.", "Likely", "The statistics point to a trend, but witnesses or robustness still doubt it."),
    "suspicious": ("Підозріло", "Схоже на тренд, але доказів поки замало — потрібно більше років даних.", "Suspicious", "It looks like a trend, but there is not enough evidence yet."),
    "no_evidence": ("Немає доказів", "Помітного тренду немає: зміни не виходять за межі звичайних коливань.", "No evidence", "No noticeable trend: changes stay within normal ups and downs."),
    "inadmissible": ("Не можна розглянути", "Справу не можна розглянути: замало даних або вони погані.", "Inadmissible", "The case cannot be judged: too little or poor data."),
}

SEASONS = {"annual": ("Увесь рік", "Whole year"), "DJF": ("Зима", "Winter"), "MAM": ("Весна", "Spring"), "JJA": ("Літо", "Summer"), "SON": ("Осінь", "Autumn")}
UNITS = {"K": "°C", "°C": "°C", "1": "", "mm": "mm", "mm/day": "mm/day", "kg/m2": "kg/m²", "day": "days"}
UNITS_UK = {"mm": "мм", "mm/day": "мм/день", "days": "днів", "kg/m²": "кг/м²"}


@dataclass(frozen=True)
class Names:
    """Catalog facts the report needs; the export service fills them, tests may pass them directly."""

    variable: str
    region: str
    units: str = ""
    doi: str = ""
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class CheckLine:
    status: str  # ok, warn or bad
    title: str
    text: str


@dataclass
class Report:
    language: str
    case_id: str
    variable_id: str
    region_id: str
    title: str
    variable: str
    region: str
    units: str
    period: str
    season: str
    verdict_code: str
    verdict_label: str
    verdict_meaning: str
    direction: str
    slope: float | None
    sentence: str
    checks: list[CheckLine]
    months: list[tuple[int, float]]
    series_dates: list[date]
    series_values: list[float | None]
    annual: list[tuple[int, float]]
    evidence: dict[str, Any]
    source: str
    source_note: str
    doi: str
    bbox: tuple[float, float, float, float] | None
    versions: dict[str, str]
    generated_at: str
    extras: dict[str, Any] = field(default_factory=dict)

    def t(self, uk: str, en: str) -> str:
        return en if self.language == "en" else uk


def _fixed(value: float) -> str:
    size = abs(value)
    return f"{size:.0f}" if size >= 10 else f"{size:.1f}" if size >= 1 else f"{size:.2f}"


def _source(version: str, language: str) -> tuple[str, str]:
    uk = language != "en"
    if version.startswith("nasa-power"):
        return "NASA POWER", (
            "Реальні щомісячні дані NASA POWER (супутники та кліматичні моделі), середнє з кількох точок регіону."
            if uk
            else "Real monthly NASA POWER data (satellites and climate models), averaged over several points of the region."
        )
    if version.startswith("demo"):
        return ("Демо-дані" if uk else "Demo data"), (
            "Синтетичний навчальний ряд: підходить, щоб зрозуміти інструменти, але не для висновків про реальний світ."
            if uk
            else "A synthetic teaching series: fine for learning the tools, not for real-world conclusions."
        )
    return ("Продукт аналітики" if uk else "Analytics product"), (
        "Попередньо пораховане зведення аналітики EarthTrend." if uk else "A precomputed EarthTrend analytics product."
    )


def _checks(case: Case, report_language: str) -> list[CheckLine]:
    def tr(uk: str, en: str) -> str:
        return en if report_language == "en" else uk

    evidence = case.evidence
    verdict = case.verdict.code if case.verdict else ""
    lines: list[CheckLine] = []
    if verdict in SIGNIFICANT:
        lines.append(CheckLine("ok", tr("Статистика", "Statistics"), tr("Тренд надто виразний, щоб бути випадковістю.", "The trend is too clear to be chance.")))
    elif verdict == "suspicious":
        lines.append(CheckLine("warn", tr("Статистика", "Statistics"), tr("Щось є, але може бути й випадковістю.", "Something is there, but it may still be chance.")))
    else:
        lines.append(CheckLine("bad", tr("Статистика", "Statistics"), tr("Тренд не відрізняється від випадкових коливань.", "The trend is not distinguishable from chance.")))
    if evidence is None:
        return lines
    confirmed, total = evidence.witnesses.confirmed, evidence.witnesses.total
    if total == 0:
        lines.append(CheckLine("warn", tr("Свідки", "Witnesses"), tr("Інших джерел для звірки немає.", "No other sources to cross-check.")))
    elif confirmed / total >= 2 / 3:
        lines.append(CheckLine("ok", tr("Свідки", "Witnesses"), tr(f"{confirmed} з {total} незалежних джерел бачать те саме.", f"{confirmed} of {total} independent sources see the same.")))
    elif confirmed > 0:
        lines.append(CheckLine("warn", tr("Свідки", "Witnesses"), tr(f"Лише {confirmed} з {total} джерел підтверджують.", f"Only {confirmed} of {total} sources agree.")))
    else:
        lines.append(CheckLine("bad", tr("Свідки", "Witnesses"), tr(f"Жодне з {total} джерел не підтверджує.", f"None of {total} sources agree.")))
    share = round(evidence.triangle.same_sign_share * 100)
    lines.append(
        CheckLine(
            "ok" if share >= 80 else "warn" if share >= 60 else "bad",
            tr("Стійкість", "Robustness"),
            tr(f"Тренд тримається для {share}% можливих періодів.", f"The trend holds for {share}% of possible periods.")
            if share >= 80
            else tr(f"Лише {share}% періодів дають той самий знак.", f"Only {share}% of periods agree."),
        )
    )
    raw = abs(evidence.alibi.b_raw)
    kept = abs(evidence.alibi.b_adjusted) / raw if raw > 0 else 1.0
    lines.append(
        CheckLine(
            "ok" if kept >= 0.7 else "warn" if kept >= 0.4 else "bad",
            tr("Алібі", "Alibi"),
            tr("Ель-Ніньйо та інші природні причини не пояснюють тренд.", "El Niño and other natural causes do not explain the trend.")
            if kept >= 0.7
            else tr("Природні причини пояснюють частину зміни, але тренд лишається.", "Natural causes explain part of the change, but the trend remains.")
            if kept >= 0.4
            else tr("Більшу частину зміни пояснюють природні коливання.", "Natural variability explains most of the change."),
        )
    )
    quality = getattr(evidence, "quality", None)
    gaps = round(getattr(quality, "gap_fraction", 0.0) * 100)
    lines.append(CheckLine("ok" if gaps <= 10 else "warn" if gaps <= 20 else "bad", tr("Якість даних", "Data quality"), tr(f"Пропущено {gaps}% місяців.", f"{gaps}% of months are missing.")))
    return lines


def _series(case: Case) -> tuple[list[date], list[float | None], list[tuple[int, float]]]:
    raw = case.source_series or {}
    dates: list[date] = []
    values: list[float | None] = []
    for when, value in zip(raw.get("dates", []), raw.get("values", []), strict=False):
        dates.append(when if isinstance(when, date) else date.fromisoformat(str(when)[:10]))
        values.append(None if value is None else float(value))
    by_year: dict[int, list[float]] = {}
    for when, value in zip(dates, values, strict=False):
        if value is not None:
            by_year.setdefault(when.year, []).append(value)
    annual = [(year, mean(items)) for year, items in sorted(by_year.items()) if len(items) >= 10]
    return dates, values, annual


def build_report(case: Case, names: Names, language: str | None = None) -> Report:
    lang = "en" if (language or case.spec.language) == "en" else "uk"

    def tr(uk: str, en: str) -> str:
        return en if lang == "en" else uk

    units = UNITS.get(names.units, names.units)
    if lang == "uk":
        units = UNITS_UK.get(units, units)
    code = case.verdict.code if case.verdict else "inadmissible"
    label_uk, meaning_uk, label_en, meaning_en = VERDICTS.get(code, (code, "", code, ""))
    slope = case.series.slope_decade if case.series else None
    direction = case.verdict.direction if case.verdict else "none"
    period = f"{case.spec.period_start[:4]}–{case.spec.period_end[:4]}"
    season_uk, season_en = SEASONS.get(case.spec.season or "annual", (case.spec.season or "", case.spec.season or ""))
    season = tr(season_uk, season_en)
    where = f"{names.variable} ({season.lower()}) — {names.region}, {period}"
    if code == "inadmissible":
        sentence = tr(f"{where}: даних замало або вони неякісні, тож висновку немає.", f"{where}: too little or poor data, so there is no conclusion.")
    elif code == "no_evidence" or slope is None or direction == "none":
        sentence = tr(f"{where}: помітного тренду немає — зміни в межах звичайних коливань.", f"{where}: no noticeable trend — changes stay within normal ups and downs.")
    else:
        amount = f"{_fixed(slope)}{f' {units}' if units else ''}"
        sentence = (
            tr(f"{where}: зростає приблизно на {amount} кожні 10 років.", f"{where}: rising by about {amount} every 10 years.")
            if direction == "increasing"
            else tr(f"{where}: спадає приблизно на {amount} кожні 10 років.", f"{where}: falling by about {amount} every 10 years.")
        )
    dates, values, annual = _series(case)
    evidence = case.evidence
    source, note = _source(case.datasets_version, lang)
    return Report(
        language=lang,
        case_id=case.id,
        variable_id=case.spec.variable_id,
        region_id=case.spec.region_id,
        title=f"{names.variable} · {names.region}",
        variable=names.variable,
        region=names.region,
        units=units,
        period=period,
        season=season,
        verdict_code=code,
        verdict_label=tr(label_uk, label_en),
        verdict_meaning=tr(meaning_uk, meaning_en),
        direction=direction,
        slope=slope,
        sentence=sentence,
        checks=_checks(case, lang),
        months=[(item.month, item.slope) for item in (case.series.months if case.series else ())],
        series_dates=dates,
        series_values=values,
        annual=annual,
        evidence={}
        if evidence is None
        else {
            "witnesses_confirmed": evidence.witnesses.confirmed,
            "witnesses_total": evidence.witnesses.total,
            "triangle_same_sign_share": evidence.triangle.same_sign_share,
            "alibi_b_raw": evidence.alibi.b_raw,
            "alibi_b_adjusted": evidence.alibi.b_adjusted,
            "gap_fraction": getattr(evidence.quality, "gap_fraction", None),
            "n_eff": getattr(evidence.quality, "n_eff", None),
        },
        source=source,
        source_note=note,
        doi=names.doi,
        bbox=names.bbox,
        versions={"catalog": case.catalog_version, "datasets": case.datasets_version, "algorithm": case.algorithm_version, "result_hash": case.result_hash},
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )
