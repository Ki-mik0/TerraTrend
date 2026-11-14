"""Curated analysis products. The backend stores them; it does not compute a trend."""

from __future__ import annotations

from earthtrend.api.domain.cases.codec import seal
from earthtrend.api.domain.cases.model import (
    AlibiResult,
    AnalysisProduct,
    CaseError,
    CaseSpec,
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

CATALOG_VERSION = "catalog-v1"
DATASETS_VERSION = "datasets-v1"
ALGORITHM_VERSION = "analytics-v1"


def _months(values: tuple[float, ...]) -> tuple[MonthSlope, ...]:
    if len(values) != 12:
        raise CaseError("verdict_required", "Ряд потребує дванадцяти місяців")
    return tuple(MonthSlope(month=index, slope=slope) for index, slope in enumerate(values, start=1))


def _levels(*rows: tuple[int, float, float, float, float, str]) -> VerticalProfile:
    return VerticalProfile(
        levels=tuple(
            VerticalLevel(pressure_hpa=pressure, slope=slope, low=low, high=high, p_value=p_value, pattern=pattern)
            for pressure, slope, low, high, p_value, pattern in rows
        )
    )


def _body(
    *,
    code: str,
    direction: str,
    summary: str,
    witnesses: tuple[int, int],
    triangle: float,
    alibi: tuple[float, float],
    quality: tuple[float, float, float],
    slope: float,
    months: tuple[float, ...],
    accelerating: bool,
    profile: VerticalProfile,
    urban: tuple[float, float, float],
    zones: tuple[Zone, ...] = (),
) -> AnalysisProduct:
    verdict = Verdict(code=code, ruleset="verdict_rules_v1", direction=direction, summary=summary)
    return AnalysisProduct(
        verdict=verdict,
        evidence=EvidenceProtocol(
            version="",
            witnesses=WitnessesResult(confirmed=witnesses[0], total=witnesses[1]),
            triangle=TriangleResult(same_sign_share=triangle),
            alibi=AlibiResult(b_raw=alibi[0], b_adjusted=alibi[1]),
            verdict_code=code,
            quality=QualityResult(gap_fraction=quality[0], stable_fraction=quality[1], n_eff=quality[2]),
        ),
        series=SeriesArtifact(
            slope_decade=slope,
            split=SplitResult(split_flag=False, sig_pos=0.2, sig_neg=0.7),
            jackknife=JackknifeResult(influential_year=None),
            zones=zones,
            months=_months(months),
            gam=GamResult(accelerating=accelerating),
        ),
        profile=profile,
        urban=UrbanContrast(city_slope=urban[0], ring_slope=urban[1], difference=urban[2]),
        catalog_version="",
        datasets_version="",
        algorithm_version="",
        result_hash="",
    )


_GLDAS_MONTHS = (-0.10, -0.12, -0.15, -0.18, -0.22, -0.30, -0.28, -0.24, -0.16, -0.14, -0.11, -0.09)
_MERRA_MONTHS = (0.12, 0.14, 0.16, 0.18, 0.20, 0.24, 0.26, 0.22, 0.18, 0.15, 0.13, 0.11)
_NORTH_MONTHS = (-0.05, -0.06, -0.08, -0.09, -0.11, -0.14, -0.13, -0.10, -0.08, -0.07, -0.06, -0.05)

_PRODUCTS: dict[tuple[str, str], AnalysisProduct] = {
    ("gldas_sm", "ukraine_south"): _body(
        code="strong",
        direction="decreasing",
        summary="Волога ґрунту спадає",
        witnesses=(3, 3),
        triangle=0.92,
        alibi=(-0.21, -0.18),
        quality=(0.04, 0.91, 80.0),
        slope=-0.21,
        months=_GLDAS_MONTHS,
        accelerating=False,
        profile=_levels(
            (1000, -0.21, -0.30, -0.12, 0.01, "drying"),
            (850, -0.08, -0.14, -0.02, 0.08, "weak"),
        ),
        urban=(-0.16, -0.09, -0.07),
        zones=(Zone(sign=-1, slope_decade=-0.21),),
    ),
    ("merra2_t2m", "ukraine_south"): _body(
        code="proven",
        direction="increasing",
        summary="Повітря теплішає",
        witnesses=(2, 3),
        triangle=0.81,
        alibi=(0.34, 0.27),
        quality=(0.02, 0.95, 110.0),
        slope=0.18,
        months=_MERRA_MONTHS,
        accelerating=True,
        profile=_levels(
            (1000, 0.18, 0.10, 0.26, 0.01, "warming"),
            (500, 0.05, 0.01, 0.09, 0.12, "aloft"),
        ),
        urban=(0.22, 0.11, 0.11),
        zones=(Zone(sign=1, slope_decade=0.18),),
    ),
    ("gldas_sm", "ukraine_north"): _body(
        code="strong",
        direction="decreasing",
        summary="На півночі волога теж спадає",
        witnesses=(2, 3),
        triangle=0.77,
        alibi=(-0.11, -0.09),
        quality=(0.06, 0.88, 70.0),
        slope=-0.11,
        months=_NORTH_MONTHS,
        accelerating=False,
        profile=_levels(
            (1000, -0.11, -0.18, -0.04, 0.03, "drying"),
            (850, -0.04, -0.08, 0.0, 0.15, "weak"),
        ),
        urban=(-0.08, -0.05, -0.03),
        zones=(Zone(sign=-1, slope_decade=-0.11),),
    ),
}


def stamp(
    template: AnalysisProduct, *, catalog_version: str, datasets_version: str, algorithm_version: str
) -> AnalysisProduct:
    evidence = EvidenceProtocol(
        version=algorithm_version,
        witnesses=template.evidence.witnesses,
        triangle=template.evidence.triangle,
        alibi=template.evidence.alibi,
        verdict_code=template.evidence.verdict_code,
        quality=template.evidence.quality,
    )
    return seal(
        AnalysisProduct(
            verdict=template.verdict,
            evidence=evidence,
            series=template.series,
            profile=template.profile,
            urban=template.urban,
            catalog_version=catalog_version,
            datasets_version=datasets_version,
            algorithm_version=algorithm_version,
            result_hash="",
        )
    )


def product_for(spec: CaseSpec, *, catalog_version: str, datasets_version: str, algorithm_version: str) -> AnalysisProduct:
    template = _PRODUCTS.get((spec.variable_id, spec.region_id))
    if template is None:
        raise CaseError("data_not_ready", "Продукту для цієї пари немає")
    return stamp(
        template,
        catalog_version=catalog_version,
        datasets_version=datasets_version,
        algorithm_version=algorithm_version,
    )
