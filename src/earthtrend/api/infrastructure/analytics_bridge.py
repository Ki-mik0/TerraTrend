"""Turn analytics results into the case, radar, story and grid records the API already stores."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date

import numpy as np

from earthtrend.analytics import (
    ANALYTICS_VERSION,
    AnalysisOptions,
    RegionalSeries,
    analyze_grid,
    analyze_series,
    build_protocol,
    regional_series,
    run_radar,
    story_lens,
    urban_contrast,
    vertical_profile,
)
from earthtrend.analytics.models import SeriesMeta
from earthtrend.analytics.radar.models import RadarRun, RadarSeries
from earthtrend.analytics.simulate.synthetic import synthetic_series
from earthtrend.api.domain.cases.model import (
    AlibiResult,
    AnalysisProduct,
    Changepoint,
    EvidenceProtocol,
    GamResult,
    JackknifeResult,
    MonthSlope,
    QualityResult,
    SeriesArtifact,
    SplitResult,
    TriangleResult,
    UrbanContrast,
    Verdict,
    VerticalLevel,
    VerticalProfile,
    WitnessesResult,
    Zone,
)


def _item(protocol, key: str) -> dict:
    found = next((item for item in protocol.items if item.key == key), None)
    return {} if found is None else dict(found.details)


def product_from_series(raw: dict, levels: dict | None = None, urban: dict | None = None) -> AnalysisProduct:
    series = RegionalSeries.model_validate(raw)
    options = AnalysisOptions()
    result = analyze_series(series, options)
    protocol = build_protocol(series, options)
    witnesses = _item(protocol, "witnesses")
    datasets = witnesses.get("datasets") or []
    confirmed = sum(1 for row in datasets if row.get("significant"))
    triangle = _item(protocol, "robustness")
    alibi = _item(protocol, "alibi")
    ols = result.test("ols_ar1")
    months = {row.month: row.slope_per_decade or 0.0 for row in result.seasonal_breakdown}
    slope = float(result.primary_slope_per_decade or 0.0)
    direction = result.direction if result.direction in {"increasing", "decreasing"} else "none"
    profile = _profile(levels) if levels else VerticalProfile(levels=())
    city = _urban(urban) if urban else UrbanContrast(city_slope=slope, ring_slope=slope, difference=0.0)
    digest = hashlib.sha256(f"{result.verdict.code}:{slope}".encode()).hexdigest()
    return AnalysisProduct(
        verdict=Verdict(
            code=result.verdict.code,
            ruleset="verdict_rules_v1",
            direction=direction,
            summary=result.verdict.code,
        ),
        evidence=EvidenceProtocol(
            version="verdict_rules_v1",
            witnesses=WitnessesResult(confirmed=confirmed, total=len(datasets)),
            triangle=TriangleResult(same_sign_share=float(triangle.get("same_sign_share", 1.0))),
            alibi=AlibiResult(
                b_raw=float(alibi.get("b_raw", alibi.get("coefficient", 0.0)) or 0.0),
                b_adjusted=float(alibi.get("b_adjusted", alibi.get("coefficient", 0.0)) or 0.0),
            ),
            verdict_code=result.verdict.code,
            quality=QualityResult(
                gap_fraction=0.0,
                stable_fraction=series.stable_fraction,
                n_eff=float(ols.n_eff if ols and ols.n_eff is not None else result.n_used),
            ),
        ),
        series=SeriesArtifact(
            slope_decade=slope,
            split=SplitResult(split_flag=False, sig_pos=0.0, sig_neg=0.0),
            jackknife=JackknifeResult(
                influential_year=None if result.influence is None else result.influence.most_influential_year
            ),
            changepoints=tuple(
                Changepoint(year=point.at.year, probability=float(point.probability or 0.0))
                for point in result.changepoints
            ),
            zones=tuple(Zone(sign=zone.sign, slope_decade=zone.mean_slope_per_decade) for zone in []),
            months=tuple(MonthSlope(month=month, slope=months.get(month, 0.0)) for month in range(1, 13)),
            gam=GamResult(accelerating=bool(result.nonlinear and result.nonlinear.shape == "accelerating")),
        ),
        profile=profile,
        urban=city,
        catalog_version=series.meta.dataset_version,
        datasets_version=series.meta.dataset_id,
        algorithm_version=ANALYTICS_VERSION,
        result_hash=digest,
    )


def _profile(raw: dict) -> VerticalProfile:
    heights = raw["levels_hpa"]
    series = [RegionalSeries.model_validate(item) for item in raw["series"]]
    computed = vertical_profile(heights, series, lat=raw.get("lat"))
    return VerticalProfile(
        levels=tuple(
            VerticalLevel(
                pressure_hpa=int(level.level_hpa),
                slope=float(level.slope_per_decade or 0.0),
                low=float(level.ci95[0] if level.ci95 else 0.0),
                high=float(level.ci95[1] if level.ci95 else 0.0),
                p_value=float(level.p_level or 1.0),
                pattern=computed.patterns[0] if computed.patterns else "level",
            )
            for level in computed.levels
        )
    )


def _urban(raw: dict) -> UrbanContrast:
    cube = np.asarray(raw["values"], dtype=np.float64)
    dates = [date.fromisoformat(item) for item in raw["dates"]]
    contrast = urban_contrast(
        cube,
        np.asarray(raw["lat"], dtype=np.float64),
        np.asarray(raw["lon"], dtype=np.float64),
        dates,
        np.asarray(raw["city_mask"], dtype=bool),
        SeriesMeta.model_validate(raw["meta"]),
    )
    city = float(contrast.city.primary_slope_per_decade or 0.0)
    ring = 0.0 if contrast.ring is None else float(contrast.ring.primary_slope_per_decade or 0.0)
    diff = 0.0 if contrast.difference is None else float(contrast.difference.primary_slope_per_decade or 0.0)
    return UrbanContrast(city_slope=city, ring_slope=ring, difference=diff)


def series_from_grid(raw: dict) -> dict:
    cube = np.asarray(raw["values"], dtype=np.float64)
    dates = [date.fromisoformat(item) for item in raw["dates"]]
    mask = np.asarray(raw["mask"], dtype=bool)
    built = regional_series(
        cube,
        np.asarray(raw["lat"], dtype=np.float64),
        np.asarray(raw["lon"], dtype=np.float64),
        mask,
        dates,
        SeriesMeta.model_validate(raw["meta"]),
    )
    return built.model_dump(mode="json")


def scan_radar(rows: list[dict]) -> RadarRun:
    series = [RadarSeries.model_validate(row) for row in rows]
    return run_radar(series)


def facts_from_story(raw: dict) -> dict:
    series = RegionalSeries.model_validate(raw)
    facts = story_lens(series)
    main = facts.main
    return {
        "direction": "increasing" if (main.slope_per_decade or 0) > 0 else "decreasing" if (main.slope_per_decade or 0) < 0 else "none",
        "slope_decade": float(main.slope_per_decade or 0.0),
        "related": [
            {
                "variable_id": item.variable_id,
                "role": "related",
                "lag_months": item.lag_used_months,
                "partial_r": item.partial_corr,
            }
            for item in facts.related
        ],
        "patterns": [item.code for item in facts.patterns],
        "caveats": list(facts.caveats),
    }


def grid_product(raw: dict):
    dates = [date.fromisoformat(item) for item in raw["dates"]]
    return analyze_grid(
        np.asarray(raw["values"], dtype=np.float64),
        np.asarray(raw["lat"], dtype=np.float64),
        np.asarray(raw["lon"], dtype=np.float64),
        dates,
    )


def lab_series(noise: float, years: int, autocorrelation: float, trend: float, seed: int) -> dict:
    series = synthetic_series(
        n_years=years,
        trend_per_decade=trend,
        noise_sd=noise,
        ar1=autocorrelation,
        seed=seed,
    )
    result = analyze_series(series, AnalysisOptions(seasonal_breakdown=False, nonlinear=False, ai_opinion=False))
    ols = result.test("ols_ar1")
    return {
        "series": [None if value is None else float(value) for value in series.values],
        "slope_decade": float(result.primary_slope_per_decade or 0.0),
        "p_value": None if ols is None else ols.p_value,
        "n_eff": None if ols is None or ols.n_eff is None else float(ols.n_eff),
        "significant": result.verdict.code in {"proven", "strong", "likely"},
    }


async def run_blocking(func, *args):
    return await asyncio.to_thread(func, *args)
