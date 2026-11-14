"""JSON shape of a stored case and its curated product."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from earthtrend.api.domain.cases.model import (
    AiOpinion,
    AlibiResult,
    AnalysisProduct,
    Case,
    CaseSpec,
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


def cache_key(spec: CaseSpec, catalog_version: str, datasets_version: str, algorithm_version: str) -> str:
    raw = "|".join(
        (
            spec.variable_id,
            spec.region_id,
            spec.period_start,
            spec.period_end,
            spec.season or "",
            spec.frequency,
            spec.language,
            catalog_version,
            datasets_version,
            algorithm_version,
        )
    )
    return "case:" + hashlib.sha256(raw.encode()).hexdigest()


def dump_spec(spec: CaseSpec) -> dict[str, Any]:
    return {
        "variable_id": spec.variable_id,
        "region_id": spec.region_id,
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "season": spec.season,
        "frequency": spec.frequency,
        "language": spec.language,
        "heavy": spec.heavy,
    }


def load_spec(data: dict[str, Any]) -> CaseSpec:
    return CaseSpec(
        variable_id=data["variable_id"],
        region_id=data["region_id"],
        period_start=data["period_start"],
        period_end=data["period_end"],
        season=data.get("season"),
        frequency=data.get("frequency", "monthly"),
        language=data.get("language", "uk"),
        heavy=bool(data.get("heavy", False)),
    )


def dump_product(product: AnalysisProduct) -> dict[str, Any]:
    return {
        "verdict": _verdict(product.verdict),
        "evidence": _evidence(product.evidence),
        "series": _series(product.series),
        "profile": _profile(product.profile),
        "urban": _urban(product.urban),
        "catalog_version": product.catalog_version,
        "datasets_version": product.datasets_version,
        "algorithm_version": product.algorithm_version,
        "result_hash": product.result_hash,
    }


def load_product(data: dict[str, Any]) -> AnalysisProduct:
    return AnalysisProduct(
        verdict=_load_verdict(data["verdict"]),
        evidence=_load_evidence(data["evidence"]),
        series=_load_series(data["series"]),
        profile=_load_profile(data["profile"]),
        urban=_load_urban(data["urban"]),
        catalog_version=data["catalog_version"],
        datasets_version=data["datasets_version"],
        algorithm_version=data["algorithm_version"],
        result_hash=data["result_hash"],
    )


def seal(product: AnalysisProduct) -> AnalysisProduct:
    payload = dump_product(product)
    payload.pop("result_hash")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return AnalysisProduct(
        verdict=product.verdict,
        evidence=product.evidence,
        series=product.series,
        profile=product.profile,
        urban=product.urban,
        catalog_version=product.catalog_version,
        datasets_version=product.datasets_version,
        algorithm_version=product.algorithm_version,
        result_hash=digest,
    )


def dump_case_result(case: Case) -> dict[str, Any]:
    return {
        "verdict": None if case.verdict is None else _verdict(case.verdict),
        "evidence": None if case.evidence is None else _evidence(case.evidence),
        "series": None if case.series is None else _series(case.series),
        "profile": None if case.profile is None else _profile(case.profile),
        "urban": None if case.urban is None else _urban(case.urban),
        "ai_opinion": None if case.ai_opinion is None else _opinion(case.ai_opinion),
        "warnings": list(case.warnings),
        "job_id": case.job_id,
        "assignment_linked": case.assignment_linked,
        "role": case.role,
    }


def load_case(
    *,
    case_id: str,
    owner_id: str,
    status: str,
    ephemeral: bool,
    spec: dict[str, Any],
    verdict_code: str | None,
    result: dict[str, Any],
    catalog_version: str,
    datasets_version: str,
    algorithm_version: str,
    result_hash: str,
) -> Case:
    del verdict_code
    return Case(
        id=case_id,
        owner_id=owner_id,
        role=result.get("role", "user"),
        spec=load_spec(spec),
        status=status,
        ephemeral=ephemeral,
        assignment_linked=bool(result.get("assignment_linked", False)),
        job_id=result.get("job_id"),
        verdict=None if result.get("verdict") is None else _load_verdict(result["verdict"]),
        evidence=None if result.get("evidence") is None else _load_evidence(result["evidence"]),
        series=None if result.get("series") is None else _load_series(result["series"]),
        ai_opinion=None if result.get("ai_opinion") is None else _load_opinion(result["ai_opinion"]),
        profile=None if result.get("profile") is None else _load_profile(result["profile"]),
        urban=None if result.get("urban") is None else _load_urban(result["urban"]),
        catalog_version=catalog_version,
        datasets_version=datasets_version,
        algorithm_version=algorithm_version,
        result_hash=result_hash,
        warnings=list(result.get("warnings", [])),
    )


def _verdict(item: Verdict) -> dict[str, str]:
    return {"code": item.code, "ruleset": item.ruleset, "direction": item.direction, "summary": item.summary}


def _load_verdict(data: dict[str, Any]) -> Verdict:
    return Verdict(code=data["code"], ruleset=data["ruleset"], direction=data["direction"], summary=data["summary"])


def _evidence(item: EvidenceProtocol) -> dict[str, Any]:
    return {
        "version": item.version,
        "verdict_code": item.verdict_code,
        "witnesses": {"confirmed": item.witnesses.confirmed, "total": item.witnesses.total},
        "triangle": {"same_sign_share": item.triangle.same_sign_share},
        "alibi": {"b_raw": item.alibi.b_raw, "b_adjusted": item.alibi.b_adjusted},
        "quality": {
            "gap_fraction": item.quality.gap_fraction,
            "stable_fraction": item.quality.stable_fraction,
            "n_eff": item.quality.n_eff,
        },
    }


def _load_evidence(data: dict[str, Any]) -> EvidenceProtocol:
    quality = data["quality"]
    return EvidenceProtocol(
        version=data["version"],
        witnesses=WitnessesResult(confirmed=data["witnesses"]["confirmed"], total=data["witnesses"]["total"]),
        triangle=TriangleResult(same_sign_share=data["triangle"]["same_sign_share"]),
        alibi=AlibiResult(b_raw=data["alibi"]["b_raw"], b_adjusted=data["alibi"]["b_adjusted"]),
        verdict_code=data["verdict_code"],
        quality=QualityResult(
            gap_fraction=quality["gap_fraction"],
            stable_fraction=quality["stable_fraction"],
            n_eff=quality["n_eff"],
        ),
    )


def _series(item: SeriesArtifact) -> dict[str, Any]:
    return {
        "slope_decade": item.slope_decade,
        "split": {"split_flag": item.split.split_flag, "sig_pos": item.split.sig_pos, "sig_neg": item.split.sig_neg},
        "jackknife": {"influential_year": item.jackknife.influential_year},
        "changepoints": [{"year": point.year, "probability": point.probability} for point in item.changepoints],
        "zones": [{"sign": zone.sign, "slope_decade": zone.slope_decade} for zone in item.zones],
        "months": [{"month": month.month, "slope": month.slope} for month in item.months],
        "gam": {"accelerating": item.gam.accelerating},
    }


def _load_series(data: dict[str, Any]) -> SeriesArtifact:
    split = data["split"]
    return SeriesArtifact(
        slope_decade=data["slope_decade"],
        split=SplitResult(split_flag=split["split_flag"], sig_pos=split["sig_pos"], sig_neg=split["sig_neg"]),
        jackknife=JackknifeResult(influential_year=data["jackknife"]["influential_year"]),
        changepoints=tuple(
            Changepoint(year=point["year"], probability=point["probability"]) for point in data["changepoints"]
        ),
        zones=tuple(Zone(sign=zone["sign"], slope_decade=zone["slope_decade"]) for zone in data["zones"]),
        months=tuple(MonthSlope(month=month["month"], slope=month["slope"]) for month in data["months"]),
        gam=GamResult(accelerating=data["gam"]["accelerating"]),
    )


def _profile(item: VerticalProfile) -> dict[str, Any]:
    return {
        "levels": [
            {
                "pressure_hpa": level.pressure_hpa,
                "slope": level.slope,
                "low": level.low,
                "high": level.high,
                "p_value": level.p_value,
                "pattern": level.pattern,
            }
            for level in item.levels
        ]
    }


def _load_profile(data: dict[str, Any]) -> VerticalProfile:
    return VerticalProfile(
        levels=tuple(
            VerticalLevel(
                pressure_hpa=level["pressure_hpa"],
                slope=level["slope"],
                low=level["low"],
                high=level["high"],
                p_value=level["p_value"],
                pattern=level["pattern"],
            )
            for level in data["levels"]
        )
    )


def _urban(item: UrbanContrast) -> dict[str, float]:
    return {"city_slope": item.city_slope, "ring_slope": item.ring_slope, "difference": item.difference}


def _load_urban(data: dict[str, Any]) -> UrbanContrast:
    return UrbanContrast(city_slope=data["city_slope"], ring_slope=data["ring_slope"], difference=data["difference"])


def _opinion(item: AiOpinion) -> dict[str, Any]:
    return {
        "predicted_class": item.predicted_class,
        "confidence": item.confidence,
        "advisory": item.advisory,
        "disagrees": item.disagrees,
    }


def _load_opinion(data: dict[str, Any]) -> AiOpinion:
    return AiOpinion(
        predicted_class=data["predicted_class"],
        confidence=data["confidence"],
        advisory=data.get("advisory", True),
        disagrees=data.get("disagrees", False),
    )
