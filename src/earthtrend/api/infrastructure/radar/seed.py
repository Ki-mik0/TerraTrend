"""Built-in radar product used until analytics writes a real scan. Every row obeys the feed rules."""

from __future__ import annotations

from earthtrend.api.domain.radar.model import RadarItem, RadarProduct, TypologyCluster

SEED_VERSION = "seed-1"
SEED_GENERATED_AT = "2026-11-01T00:00:00Z"

# feed, variable, region, season, direction, slope, pct, snr, p, q, split, score, verdict, novelty, years, area
_ROWS: list[tuple] = [
    ("strongest", "merra2_t2m", "arctic", "annual", "increasing", 0.72, 2.6, 0.9, 0.0001, 0.001, False, 0.97, "proven", "unchanged", None, 14_000_000),
    ("strongest", "gldas_sm", "ukraine_south", "JJA", "decreasing", -0.031, -1.8, 0.55, 0.003, 0.02, False, 0.81, "strong", "upgraded", None, 120_000),
    ("strongest", "grace_tws", "north_india", "annual", "decreasing", -1.9, -4.1, 0.7, 0.0005, 0.004, False, 0.88, "proven", "unchanged", None, 650_000),
    ("strongest", "merra2_t2m", "sahel", "MAM", "increasing", 0.41, 1.4, 0.6, 0.002, 0.015, False, 0.74, "strong", "new", None, 3_000_000),
    ("opposite", "omi_no2", "usa_europe_south_asia", "annual", "none", -0.08, -3.2, 0.5, 0.004, 0.03, True, 0.86, "strong", "unchanged", None, 9_000_000),
    ("opposite", "modis_ndvi", "sahel", "JJA", "increasing", 0.012, 2.1, 0.45, 0.01, 0.05, True, 0.66, "likely", "new", None, 3_000_000),
    ("accelerating", "merra2_t2m", "arctic", "DJF", "increasing", 0.95, 3.4, 0.8, 0.0003, 0.002, False, 0.9, "proven", "upgraded", None, 14_000_000),
    ("accelerating", "grace_tws", "california", "annual", "decreasing", -1.2, -3.0, 0.5, 0.006, 0.04, False, 0.7, "likely", "unchanged", None, 420_000),
    ("breakpoints", "omi_no2", "china_east", "annual", "decreasing", -0.11, -4.5, 0.6, 0.002, 0.02, False, 0.78, "strong", "new", None, 1_200_000),
    ("breakpoints", "gldas_sm", "ukraine_south", "annual", "decreasing", -0.02, -1.1, 0.35, 0.02, 0.07, False, 0.58, "likely", "unchanged", None, 120_000),
    ("almost", "gldas_sm", "ukraine_north", "JJA", "decreasing", -0.012, -0.7, 0.18, 0.09, 0.16, False, 0.42, "suspicious", "new", 6.0, 90_000),
    ("almost", "modis_ndvi", "ukraine_south", "MAM", "increasing", 0.004, 0.6, 0.15, 0.12, 0.19, False, 0.38, "suspicious", "unchanged", 9.0, 120_000),
    ("almost", "merra2_t2m", "kyiv", "annual", "increasing", 0.18, 0.7, 0.2, 0.07, 0.15, False, 0.4, "suspicious", "downgraded", 4.0, 840),
    ("stable", "gldas_sm", "carpathians", "annual", "none", 0.001, 0.05, 0.02, 0.7, 0.85, False, 0.3, "no_evidence", "unchanged", None, 24_000),
    ("stable", "modis_ndvi", "amazon", "annual", "none", 0.0005, 0.03, 0.01, 0.8, 0.9, False, 0.25, "no_evidence", "unchanged", None, 5_500_000),
    ("ai_flagged", "gldas_sm", "ukraine_south", "annual", "decreasing", -0.025, -1.4, 0.4, 0.01, 0.06, False, 0.62, "suspicious", "new", None, 120_000),
    ("ai_flagged", "omi_no2", "kyiv", "annual", "decreasing", -0.05, -2.2, 0.3, 0.02, 0.08, False, 0.55, "likely", "unchanged", None, 840),
]

_CLUSTERS = [
    TypologyCluster(
        id="typ_warmer_drier_browner",
        pattern="warmer_drier_browner",
        signs={"merra2_t2m": 1, "gldas_sm": -1, "modis_ndvi": -1},
        season="JJA",
        area_km2=2_100_000,
        region_ids=("ukraine_south", "mediterranean"),
    ),
    TypologyCluster(
        id="typ_warmer_greener",
        pattern="warmer_greener",
        signs={"merra2_t2m": 1, "modis_ndvi": 1},
        season="annual",
        area_km2=7_800_000,
        region_ids=("arctic", "sahel"),
    ),
    TypologyCluster(
        id="typ_cleaner_air",
        pattern="cleaner_air",
        signs={"omi_no2": -1},
        season="annual",
        area_km2=4_300_000,
        region_ids=("usa_europe_south_asia", "china_east"),
    ),
]


def seed_product() -> RadarProduct:
    items = tuple(
        RadarItem(
            id=f"radar_{feed}_{variable}_{region}_{season}".lower(),
            feed=feed,
            variable_id=variable,
            region_id=region,
            season=season,
            direction=direction,
            slope_decade=slope,
            pct_decade=pct,
            snr=snr,
            p_mk=p,
            p_ols=min(p * 1.5, 1.0),
            q_fdr=q,
            split_flag=split,
            score=score,
            verdict_level=verdict,
            novelty=novelty,
            years_to_detect=years,
            area_km2=float(area),
            case_id=f"case_radar_{variable}_{region}_{season}".lower(),
        )
        for feed, variable, region, season, direction, slope, pct, snr, p, q, split, score, verdict, novelty, years, area in _ROWS
    )
    return RadarProduct(version=SEED_VERSION, generated_at=SEED_GENERATED_AT, items=items, clusters=tuple(_CLUSTERS))
