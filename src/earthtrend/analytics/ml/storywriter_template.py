"""Deterministic template writer of Story Lens texts, UA and EN (section 11.5).

The fallback author of ``write_story`` and the default teacher of the M4 distillation set.
It never fails: any valid ``StoryFacts`` gives a text, and that text passes
``check_numbers`` by construction (numbers are printed only from ``StoryFacts.numbers``;
every mandatory caveat gets its sentence). Nothing here quotes a number that is not a fact:
names avoid digits ("per decade", not "per 10 years"; "autocorrelation", not "AR(1)").
"""

from __future__ import annotations

import math

from earthtrend.analytics.ml.storywriter_check import Lang
from earthtrend.analytics.story.models import RelatedVariable, StoryFacts

TEMPLATE_VERSION = "template_v1"
MAX_RELATED = 3
MAX_WITNESSES = 3

CONCEPTS: dict[str, tuple[str, str]] = {  # id -> (uk, en)
    "air_temperature": ("Температура повітря", "Air temperature"),
    "land_surface_temperature_day": (
        "Денна температура поверхні",
        "Daytime land surface temperature",
    ),
    "sea_surface_temperature": ("Температура поверхні моря", "Sea surface temperature"),
    "air_temperature_upper": ("Температура верхньої тропосфери", "Upper-air temperature"),
    "stratosphere_temperature": ("Температура стратосфери", "Stratosphere temperature"),
    "precipitation": ("Опади", "Precipitation"),
    "soil_moisture_surface": ("Вологість поверхні ґрунту", "Surface soil moisture"),
    "soil_moisture_root_zone": ("Вологість кореневої зони", "Root-zone soil moisture"),
    "evapotranspiration": ("Випаровування", "Evapotranspiration"),
    "terrestrial_water_storage": ("Запас води на суходолі", "Terrestrial water storage"),
    "ndvi": ("Зеленість рослин (NDVI)", "Vegetation greenness (NDVI)"),
    "growing_season_length": ("Тривалість вегетаційного сезону", "Growing season length"),
    "burned_area": ("Площа пожеж", "Burned area"),
    "snow_cover": ("Сніговий покрив", "Snow cover"),
    "snow_days": ("Кількість снігових днів", "Snow days"),
    "snow_water_equivalent": ("Запас води в снігу", "Snow water equivalent"),
    "sea_ice": ("Морський лід", "Sea ice"),
    "no2": ("Діоксид азоту (NO₂)", "Nitrogen dioxide (NO₂)"),
    "aerosol_optical_depth": ("Аерозольна оптична товщина", "Aerosol optical depth"),
    "urban_heat_contrast": ("Різниця температур місто − околиці", "Urban heat contrast"),
}

SEASONS: dict[str, tuple[str, str]] = {
    "annual": ("за рік", "annual"),
    "DJF": ("взимку (DJF)", "winter (DJF)"),
    "MAM": ("навесні (MAM)", "spring (MAM)"),
    "JJA": ("влітку (JJA)", "summer (JJA)"),
    "SON": ("восени (SON)", "autumn (SON)"),
}

DIRECTIONS: dict[str, tuple[str, str]] = {
    "increasing": ("зростає", "is increasing"),
    "decreasing": ("спадає", "is decreasing"),
    "none": ("не має чіткого тренду", "shows no clear trend"),
}

VERDICTS: dict[str, tuple[str, str]] = {
    "proven": ("доведено", "proven"),
    "strong": ("сильні докази", "strong evidence"),
    "likely": ("ймовірний тренд", "a likely trend"),
    "suspicious": ("підозрілий результат", "a suspicious result"),
    "no_evidence": ("доказів тренду немає", "no evidence of a trend"),
    "inadmissible": ("висновок неможливий", "no conclusion possible"),
}

PATTERNS: dict[str, tuple[str, str]] = {
    "aridification": ("посушливішання", "aridification (drying)"),
    "greening": ("озеленення", "greening"),
    "earlier_spring": ("раніша весна", "earlier spring"),
    "snow_retreat": ("відступ снігу", "snow retreat"),
    "cleaner_air": ("чистіше повітря", "cleaner air"),
    "worsening_air": ("брудніше повітря", "worsening air"),
    "urban_heating": ("нагрівання міста", "urban heating"),
    "ocean_warming": ("потепління океану", "ocean warming"),
    "troposphere_warming_stratosphere_cooling": (
        "тропосфера теплішає, стратосфера холоднішає",
        "troposphere warming, stratosphere cooling",
    ),
}

AI_CLASSES: dict[str, tuple[str, str]] = {
    "no_trend": ("без тренду", "no trend"),
    "linear": ("лінійний тренд", "a linear trend"),
    "step": ("стрибок", "a step"),
    "accelerating": ("прискорення", "an accelerating trend"),
    "trend_plus_step": ("тренд зі стрибком", "a trend plus a step"),
}

SNR_CLASSES: dict[str, tuple[str, str]] = {
    "strong": ("сильний", "strong"),
    "moderate": ("помірний", "moderate"),
    "weak": ("слабкий", "weak"),
}

# Caveat code -> (uk, en) sentence; each matches its CAVEAT_MARKERS (tested).
CAVEATS: dict[str, tuple[str, str]] = {
    "many_gaps": ("У ряді багато пропусків.", "The series has many gaps."),
    "low_stable_coverage": (
        "Стабільне покриття регіону даними мале.",
        "Stable data coverage of the region is low.",
    ),
    "possible_artifact": (
        "Можливий артефакт сенсора: частина зміни може бути технічною.",
        "A sensor artifact is possible: part of the change may be technical.",
    ),
    "methods_disagree": (
        "Статистичні методи розходяться між собою.",
        "The statistical methods disagree with each other.",
    ),
    "witnesses_disagree": (
        "Незалежні свідки (інші датасети) розходяться з основним рядом.",
        "Independent witnesses (other datasets) disagree with the main series.",
    ),
    "period_sensitive": (
        "Результат чутливий до вибору періоду.",
        "The result is sensitive to the choice of period.",
    ),
    "influential_year": (
        "Один рік помітно впливає на результат.",
        "A single year noticeably influences the result.",
    ),
    "index_trend_overlap": (
        "Кліматичний індекс має власний тренд, тож поправка на нього неточна.",
        "A climate index has its own trend, so the adjustment for it is uncertain.",
    ),
    "explained_by_enso": (
        "Тренд значною мірою пояснюється Ель-Ніньйо (ENSO).",
        "The trend is largely explained by El Niño (ENSO).",
    ),
    "long_memory": (
        "Ряд має довгу пам'ять: тренд може бути частиною повільних природних коливань.",
        "The series has long memory: the trend may be part of slow natural swings.",
    ),
    "split_region": (
        "Різні частини регіону змінюються по-різному.",
        "Different parts of the region change differently.",
    ),
    "ai_disagrees": (
        "Думка ШІ розходиться зі статистикою (вона лише дорадча).",
        "The AI opinion disagrees with the statistics (it is advisory only).",
    ),
    "short_record": (
        "Ряд закороткий для надійного висновку.",
        "The record is too short for a reliable conclusion.",
    ),
    "outliers": ("У ряді є викиди.", "The series contains outliers."),
    "low_n_eff": (
        "Через автокореляцію ефективний обсяг вибірки малий.",
        "Autocorrelation leaves a small effective sample size.",
    ),
}


def _pick(pair: tuple[str, str], lang: Lang) -> str:
    return pair[0] if lang == "uk" else pair[1]


def concept_name(concept_id: str, lang: Lang) -> str:
    pair = CONCEPTS.get(concept_id)
    return _pick(pair, lang) if pair else concept_id  # id: digits glued, never a "number"


def caveat_sentence(code: str, lang: Lang) -> str:
    pair = CAVEATS.get(code)
    if pair:
        return _pick(pair, lang)
    return f"Застереження: {code}." if lang == "uk" else f"Caveat: {code}."


# ---------------------------------------------------------------- number formatting


def _decimals(v: float) -> int:
    a = abs(v)
    if a == 0 or abs(v - round(v)) < 1e-9:
        return 0
    if a >= 100:
        return 0
    if a >= 10:
        return 1
    if a >= 1:
        return 2
    return min(6, max(2, 1 - math.floor(math.log10(a))))


def fmt(v: float, lang: Lang, signed: bool = False) -> str:
    """Rounded like a person would write it; ``signed`` prints ``+`` / ``−`` explicitly."""
    d = _decimals(v)
    s = f"{abs(v):.{d}f}"
    if lang == "uk":
        s = s.replace(".", ",")
    if signed and round(v, d) != 0:
        s = ("+" if v > 0 else "−") + s
    elif v < 0 and round(v, d) != 0:
        s = "−" + s
    return s


def fmt_p(p: float, lang: Lang) -> str:
    if p < 0.001:
        return "p < 0,001" if lang == "uk" else "p < 0.001"
    return "p = " + fmt(p, lang)


def fmt_pct(share: float) -> str:
    return f"{round(share * 100)}%"


# ---------------------------------------------------------------- sections


def _headline(f: StoryFacts, lang: Lang) -> str:
    m = f.main
    name = concept_name(m.concept_id, lang)
    season = _pick(SEASONS.get(m.season, (m.season, m.season)), lang)
    period = ""
    if m.period_start and m.period_end:
        period = f", {m.period_start.year}–{m.period_end.year}"
    where = f"у регіоні {m.region_id}" if lang == "uk" else f"in region {m.region_id}"
    head = f"{name} {where} ({season}{period})"
    if m.verdict == "inadmissible":
        tail = "даних замало для висновку" if lang == "uk" else "there are not enough data"
        return f"{head}: {tail}."
    return f"{head} {_pick(DIRECTIONS[m.direction], lang)}."


def _units(f: StoryFacts) -> str:
    u = f.main.units.strip()
    return "" if not u or u == "1" or not any(c.isalpha() for c in u) else f" {u}"


def _slope(f: StoryFacts, lang: Lang) -> list[str]:
    n = f.numbers
    if "main.slope_per_decade" not in n:
        return []
    per = "за десятиліття" if lang == "uk" else "per decade"
    s = (
        f"Тренд: {fmt(n['main.slope_per_decade'], lang, signed=True)}{_units(f)} {per}"
        if lang == "uk"
        else f"Trend: {fmt(n['main.slope_per_decade'], lang, signed=True)}{_units(f)} {per}"
    )
    if "main.ci95_low" in n and "main.ci95_high" in n:
        lo, hi = fmt(n["main.ci95_low"], lang), fmt(n["main.ci95_high"], lang)
        s += f" (95% ДІ від {lo} до {hi})" if lang == "uk" else f" (95% CI from {lo} to {hi})"
    if "main.percent_per_decade" in n:
        pct = fmt(n["main.percent_per_decade"], lang, signed=True)
        s += f", тобто {pct}% {per}" if lang == "uk" else f", that is {pct}% {per}"
    return [s + "."]


def _verdict(f: StoryFacts, lang: Lang) -> str:
    m = f.main
    v = _pick(VERDICTS[m.verdict], lang)
    if lang == "uk":
        return f"Вирок: {v} (сила {m.strength} зі 100, правила {m.ruleset})."
    return f"Verdict: {v} (strength {m.strength} of 100, rules {m.ruleset})."


def _statistics(f: StoryFacts, lang: Lang) -> list[str]:
    n, m = f.numbers, f.main
    parts: list[str] = []
    if "main.p_ols_annual" in n:
        what = (
            "річні середні, поправка на автокореляцію"
            if lang == "uk"
            else "annual means, autocorrelation-corrected"
        )
        parts.append(f"{fmt_p(n['main.p_ols_annual'], lang)} ({what})")
    elif "main.p_ols" in n:
        what = "поправка на автокореляцію" if lang == "uk" else "autocorrelation-corrected"
        parts.append(f"{fmt_p(n['main.p_ols'], lang)} ({what})")
    if "main.p_mk" in n:
        parts.append(f"Mann-Kendall {fmt_p(n['main.p_mk'], lang)}")
    out: list[str] = []
    if parts:
        out.append(("Статистика: " if lang == "uk" else "Statistics: ") + "; ".join(parts) + ".")
    if "main.snr" in n:
        cls = _pick(SNR_CLASSES[m.snr_class], lang) if m.snr_class in SNR_CLASSES else ""
        val = fmt(n["main.snr"], lang)
        if lang == "uk":
            out.append(f"Відношення сигнал/шум {val}" + (f" ({cls})." if cls else "."))
        else:
            out.append(f"Signal-to-noise ratio {val}" + (f" ({cls})." if cls else "."))
    if "main.years_to_detect" in n and "main.years_of_data" in n:
        need, have = fmt(n["main.years_to_detect"], lang), fmt(n["main.years_of_data"], lang)
        if lang == "uk":
            out.append(f"Щоб виявити такий тренд, потрібно близько {need} р. даних; є {have}.")
        else:
            out.append(f"Detecting such a trend takes about {need} years of data; we have {have}.")
    return out


def _witnesses(f: StoryFacts, lang: Lang) -> list[str]:
    w = f.witnesses
    if w is None or w.status == "na":
        return []
    if w.status == "pass":
        s = (
            "Незалежні свідки підтверджують тренд"
            if lang == "uk"
            else "Independent witnesses confirm the trend"
        )
    elif w.status == "partial":
        s = (
            "Свідки підтверджують тренд частково"
            if lang == "uk"
            else "Witnesses partly confirm the trend"
        )
    else:
        s = (
            "Свідки не підтверджують тренд"
            if lang == "uk"
            else "Witnesses do not confirm the trend"
        )
    items: list[str] = []
    for d in w.datasets[:MAX_WITNESSES]:
        key = f"witnesses.{d['dataset_id']}.slope_per_decade"
        if key in f.numbers:
            items.append(f"{d['dataset_id']}: {fmt(f.numbers[key], lang, signed=True)}")
    if items:
        s += " (" + "; ".join(items) + ")"
    return [s + "."]


def _alibi(f: StoryFacts, lang: Lang) -> list[str]:
    a, n = f.alibi, f.numbers
    if a is None or a.status == "na":
        return []
    if a.status == "pass":
        s = (
            "Кліматичні індекси не пояснюють тренд"
            if lang == "uk"
            else "Climate indices do not explain the trend"
        )
    elif a.status == "partial":
        s = (
            "Кліматичні індекси пояснюють частину тренду"
            if lang == "uk"
            else "Climate indices explain part of the trend"
        )
    else:
        s = (
            "Кліматичні індекси пояснюють більшу частину тренду"
            if lang == "uk"
            else "Climate indices explain most of the trend"
        )
    if "alibi.b_adjusted_per_decade" in n:
        val = fmt(n["alibi.b_adjusted_per_decade"], lang, signed=True)
        s += (
            f": після поправки тренд {val} за десятиліття"
            if lang == "uk"
            else f": after adjustment the trend is {val} per decade"
        )
        if "alibi.p_adjusted" in n:
            s += f" ({fmt_p(n['alibi.p_adjusted'], lang)})"
    return [s + "."]


def _related_order(rv: RelatedVariable) -> tuple[int, float]:
    return (rv.route.depth, -abs(rv.corr) if rv.corr is not None else 0.0)


def _related(f: StoryFacts, lang: Lang) -> list[str]:
    out: list[str] = []
    n = f.numbers
    per = "за десятиліття" if lang == "uk" else "per decade"
    for rv in sorted(f.related, key=_related_order)[:MAX_RELATED]:
        pre = f"related.{rv.variable_id}"
        s = f"{concept_name(rv.concept_id, lang)} {_pick(DIRECTIONS[rv.direction], lang)}"
        if f"{pre}.slope_per_decade" in n:
            s += f" ({fmt(n[f'{pre}.slope_per_decade'], lang, signed=True)} {per})"
        if f"{pre}.corr" in n:
            r = fmt(n[f"{pre}.corr"], lang, signed=True)
            s += (
                f"; кореляція детрендованих аномалій r = {r}"
                if lang == "uk"
                else f"; correlation of detrended anomalies r = {r}"
            )
            if f"{pre}.corr_p" in n:
                s += f" ({fmt_p(n[f'{pre}.corr_p'], lang)})"
            lag = n.get(f"{pre}.lag_months", 0.0)
            if lag:
                lag_s = fmt(abs(lag), lang)
                s += f", зсув {lag_s} міс" if lang == "uk" else f", lag {lag_s} months"
        if rv.corr_consistency == "consistent":
            s += (
                "; це узгоджується з очікуваним зв'язком"
                if lang == "uk"
                else "; this fits the expected link"
            )
        elif rv.corr_consistency == "inconsistent":
            s += (
                "; це не збігається з очікуваним зв'язком"
                if lang == "uk"
                else "; this does not fit the expected link"
            )
        out.append(s + ".")
    if out:
        head = "Пов'язані змінні: " if lang == "uk" else "Related variables: "
        out[0] = head + out[0]
    return out


def _patterns(f: StoryFacts, lang: Lang) -> list[str]:
    out: list[str] = []
    for pm in f.patterns:
        key = f"patterns.{pm.code}.confidence"
        name = _pick(PATTERNS.get(pm.code, (pm.code, pm.code)), lang)
        conf = f" ({fmt_pct(f.numbers[key])})" if key in f.numbers else ""
        out.append(f"«{name}»{conf}" if lang == "uk" else f"“{name}”{conf}")
    if not out:
        return []
    head = "Схоже на патерн " if lang == "uk" else "This looks like the pattern "
    if len(out) > 1:
        head = "Схоже на патерни " if lang == "uk" else "This looks like the patterns "
    return [head + ", ".join(out) + "."]


def _ai(f: StoryFacts, lang: Lang) -> list[str]:
    op = f.ai_opinion
    if op is None:
        return []
    cls = _pick(AI_CLASSES.get(op.predicted_class, (op.predicted_class, op.predicted_class)), lang)
    key = f"ai.prob.{op.predicted_class}"
    prob = f" ({fmt_pct(f.numbers[key])})" if key in f.numbers else ""
    if lang == "uk":
        return [f"Нейродетектив (дорадча думка, не доказ) бачить тут {cls}{prob}."]
    return [f"The AI detective (advisory, not evidence) sees {cls} here{prob}."]


def _caveats(f: StoryFacts, lang: Lang) -> list[str]:
    if not f.caveats:
        return []
    head = "Застереження: " if lang == "uk" else "Caveats: "
    body = " ".join(caveat_sentence(c, lang) for c in f.caveats)
    return [head + body]


def template_story(facts: StoryFacts, lang: Lang = "uk") -> str:
    """Deterministic text of a Story Lens case. Never raises on valid facts."""
    lines = [_headline(facts, lang)]
    if facts.main.verdict != "inadmissible":
        lines += _slope(facts, lang)
        lines.append(_verdict(facts, lang))
        lines += _statistics(facts, lang)
        lines += _witnesses(facts, lang)
        lines += _alibi(facts, lang)
        lines += _related(facts, lang)
        lines += _patterns(facts, lang)
        lines += _ai(facts, lang)
    lines += _caveats(facts, lang)
    return " ".join(lines)


__all__ = [
    "CAVEATS",
    "TEMPLATE_VERSION",
    "caveat_sentence",
    "concept_name",
    "fmt",
    "template_story",
]
