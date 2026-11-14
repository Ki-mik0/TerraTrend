"""Training data of M2 (docs/PLAN_ANALYTICS.md section 11.3): labels, regions, dataset.

* **Labels** are Radar stage 1 results (section 9.5): significant = ``q < 0.05``, the sign
  of Sen's slope, |SNR|. ``labels_from_candidates`` reads any object with the fields of
  ``radar.models.RadarCandidate`` (no import, so the trainer does not depend on the scan).
* **Random regions** (rectangles and circles anywhere on the grid) teach the model about
  more than administrative borders; ``region_features_from_rasters`` turns a mask into
  ``RegionFeatures`` from the precomputed feature rasters.
* **Spatial blocks** (30 deg lat x 60 deg lon) are the groups of the spatial CV.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics.ml.features import FEATURE_NAMES, Vocab, build_matrix
from earthtrend.analytics.ml.potential_models import (
    LAND_COVER_CLASSES,
    RegionFeatures,
    VariableInfo,
)
from earthtrend.analytics.regional.weights import area_weights
from earthtrend.analytics.spatial.zones import cell_area_km2

LABEL_Q = 0.05  # section 11.3: significant = q < 0.05
BLOCK_LAT_DEG = 30.0
BLOCK_LON_DEG = 60.0


# ---------------------------------------------------------------- labels


@dataclass(frozen=True)
class PotentialLabel:
    region_id: str
    variable_id: str
    season: str
    significant: bool
    sign: int  # -1 / 0 / 1 (Sen slope)
    snr: float  # |SNR|


class CandidateLike(Protocol):
    region_id: str
    variable_id: str
    season: str
    slope_per_decade: float | None
    q_variable: float | None
    snr: float | None
    skipped: str | None


def labels_from_candidates(
    candidates: Iterable[CandidateLike], q_alpha: float = LABEL_Q
) -> list[PotentialLabel]:
    out: list[PotentialLabel] = []
    for c in candidates:
        if c.skipped or c.q_variable is None or c.snr is None or c.slope_per_decade is None:
            continue
        s = c.slope_per_decade
        out.append(
            PotentialLabel(
                region_id=c.region_id,
                variable_id=c.variable_id,
                season=str(c.season),
                significant=c.q_variable < q_alpha,
                sign=0 if s == 0 or not math.isfinite(s) else (1 if s > 0 else -1),
                snr=abs(float(c.snr)),
            )
        )
    return out


# ---------------------------------------------------------------- regions


def spatial_block(lat: float, lon: float) -> str:
    lon = ((lon + 180.0) % 360.0) - 180.0
    i = min(int((lat + 90.0) // BLOCK_LAT_DEG), int(180 / BLOCK_LAT_DEG) - 1)
    j = min(int((lon + 180.0) // BLOCK_LON_DEG), int(360 / BLOCK_LON_DEG) - 1)
    return f"b{i}_{j}"


def random_region_masks(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    n: int,
    seed: int = 0,
    min_cells: int = 4,
    land: NDArray[np.bool_] | None = None,
) -> list[tuple[str, NDArray[np.bool_]]]:
    """``n`` random rectangles and circles (half each) of 2-25 deg across.

    Regions with fewer than ``min_cells`` cells (or land cells, when ``land`` is given) are
    redrawn. Names are ``rand_rect_<k>`` / ``rand_circ_<k>``.
    """
    rng = np.random.default_rng(seed)
    glat, glon = np.meshgrid(lat, lon, indexing="ij")
    out: list[tuple[str, NDArray[np.bool_]]] = []
    k = 0
    tries = 0
    while len(out) < n and tries < 50 * n:
        tries += 1
        c_lat = math.degrees(math.asin(rng.uniform(-0.97, 0.97)))  # uniform on the sphere
        c_lon = float(rng.uniform(lon.min(), lon.max()))
        size = float(rng.uniform(2.0, 25.0))
        if k % 2 == 0:
            half_lon = size / 2 / max(math.cos(math.radians(c_lat)), 0.2)
            dlon = np.abs(((glon - c_lon + 180) % 360) - 180)
            mask = (np.abs(glat - c_lat) <= size / 2) & (dlon <= half_lon)
            name = f"rand_rect_{len(out)}"
        else:
            p1, p2 = np.radians(glat), math.radians(c_lat)
            dl = np.radians(glon - c_lon)
            cosd = np.sin(p1) * math.sin(p2) + np.cos(p1) * math.cos(p2) * np.cos(dl)
            mask = np.degrees(np.arccos(np.clip(cosd, -1, 1))) <= size / 2
            name = f"rand_circ_{len(out)}"
        k += 1
        cells = mask & land if land is not None else mask
        if int(cells.sum()) >= min_cells:
            out.append((name, cells))
    return out


def region_features_from_rasters(
    region_id: str,
    mask: NDArray[np.bool_],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    rasters: Mapping[str, NDArray[np.float64]],
) -> RegionFeatures:
    """Area-weighted means of the precomputed feature rasters over ``mask``.

    Raster keys: any scalar ``RegionFeatures`` field (``clim_t_c``, ``aridity_index``...),
    ``lc_<class>`` for land-cover shares, ``elevation_m`` (gives mean and range),
    ``koppen_code`` (0..4 = A..E; the area mode is used). Missing rasters -> None.
    """
    w = area_weights(lat, lon, mask)
    if w.sum() <= 0:
        raise ValueError("empty region")
    glat, glon = np.meshgrid(lat, lon, indexing="ij")

    def wmean(a: NDArray[np.float64]) -> float | None:
        ok = np.isfinite(a) & (w > 0)
        if not ok.any():
            return None
        return float(np.sum(a[ok] * w[ok]) / np.sum(w[ok]))

    c_lat = wmean(glat)
    # circular mean of longitude
    ang = np.radians(glon)
    c_lon = float(
        np.degrees(math.atan2(float(np.sum(np.sin(ang) * w)), float(np.sum(np.cos(ang) * w))))
    )
    area = float(cell_area_km2(lat, lon)[mask].sum())
    data: dict[str, Any] = {
        "region_id": region_id,
        "lat": c_lat,
        "lon": c_lon,
        "area_km2": max(area, 1e-6),
    }
    for name in (
        "coast_share",
        "dist_to_sea_km",
        "clim_t_c",
        "clim_pr_mm_yr",
        "clim_ndvi",
        "seasonal_amplitude_c",
        "aridity_index",
        "pop_density",
        "pop_change_pct",
        "built_share",
    ):
        if name in rasters:
            data[name] = wmean(np.asarray(rasters[name], dtype=np.float64))
    if "elevation_m" in rasters:
        el = np.asarray(rasters["elevation_m"], dtype=np.float64)
        data["elev_mean_m"] = wmean(el)
        sel = el[mask & np.isfinite(el)]
        data["elev_range_m"] = float(sel.max() - sel.min()) if sel.size else None
    lc = {
        c: v
        for c in LAND_COVER_CLASSES
        if f"lc_{c}" in rasters
        and (v := wmean(np.asarray(rasters[f"lc_{c}"], dtype=np.float64))) is not None
    }
    if lc:
        data["land_cover"] = lc
    if "koppen_code" in rasters:
        kc_raw = np.asarray(rasters["koppen_code"], dtype=np.float64)[mask]
        kc = kc_raw[np.isfinite(kc_raw)].astype(np.int64)
        if kc.size:
            data["koppen"] = "ABCDE"[int(np.bincount(kc, minlength=5).argmax())]
    return RegionFeatures.model_validate(data)


# ---------------------------------------------------------------- dataset


@dataclass
class PotentialDataset:
    x: NDArray[np.float64]
    significant: NDArray[np.bool_]
    sign: NDArray[np.int64]
    snr: NDArray[np.float64]
    region_ids: list[str]
    variable_ids: list[str]
    seasons: list[str]
    blocks: list[str]
    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    vocab: Vocab
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def subset(self, idx: NDArray[np.int64]) -> PotentialDataset:
        def pick(seq: list[str]) -> list[str]:
            return [seq[i] for i in idx]

        return PotentialDataset(
            x=self.x[idx],
            significant=self.significant[idx],
            sign=self.sign[idx],
            snr=self.snr[idx],
            region_ids=pick(self.region_ids),
            variable_ids=pick(self.variable_ids),
            seasons=pick(self.seasons),
            blocks=pick(self.blocks),
            lat=self.lat[idx],
            lon=self.lon[idx],
            vocab=self.vocab,
            meta=self.meta,
        )

    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(np.nan_to_num(self.x, nan=-9999.0)).tobytes())
        h.update(self.significant.tobytes())
        h.update(self.sign.tobytes())
        h.update(np.ascontiguousarray(self.snr).tobytes())
        h.update(json.dumps(self.vocab.data, sort_keys=True).encode())
        return h.hexdigest()[:16]


def build_dataset(
    labels: Sequence[PotentialLabel],
    regions: Mapping[str, RegionFeatures],
    variables: Mapping[str, VariableInfo],
    vocab: Vocab | None = None,
) -> PotentialDataset:
    """Join labels with region and variable descriptors. Labels whose region or variable
    has no descriptors are dropped (counted in ``meta``)."""
    keep = [lb for lb in labels if lb.region_id in regions and lb.variable_id in variables]
    vocab = vocab or Vocab.fit(list(variables.values()))
    rows = [(regions[lb.region_id], variables[lb.variable_id], lb.season) for lb in keep]
    x = build_matrix(rows, vocab) if rows else np.empty((0, len(FEATURE_NAMES)))
    return PotentialDataset(
        x=x,
        significant=np.array([lb.significant for lb in keep], dtype=bool),
        sign=np.array([lb.sign for lb in keep], dtype=np.int64),
        snr=np.array([lb.snr for lb in keep], dtype=np.float64),
        region_ids=[lb.region_id for lb in keep],
        variable_ids=[lb.variable_id for lb in keep],
        seasons=[lb.season for lb in keep],
        blocks=[spatial_block(regions[lb.region_id].lat, regions[lb.region_id].lon) for lb in keep],
        lat=np.array([regions[lb.region_id].lat for lb in keep]),
        lon=np.array([regions[lb.region_id].lon for lb in keep]),
        vocab=vocab,
        meta={"n_labels": len(labels), "n_dropped": len(labels) - len(keep)},
    )


# ---------------------------------------------------------------- synthetic world


def synthetic_world(
    n_regions: int = 400, seed: int = 0
) -> tuple[list[PotentialLabel], dict[str, RegionFeatures], dict[str, VariableInfo]]:
    """A world with known geographic rules, for tests and the pipeline smoke run.

    Rules (log-odds of a significant trend, all regions also get noise):
    temperature trends almost everywhere, stronger at high latitudes; soil moisture dries
    in arid regions; NDVI greens in cold, cropland-rich regions; NO2 falls in dense,
    rich-urban regions and rises with rapid urban growth; snow declines at high latitude;
    precipitation is mostly noise. Never use it as evidence about the real Earth.
    """
    rng = np.random.default_rng(seed)
    variables = {
        "t2m": VariableInfo(
            variable_id="t2m",
            concept_id="air_temperature",
            domain="atmosphere",
            record_years=45,
            noise_level=0.6,
        ),
        "lst_night": VariableInfo(
            variable_id="lst_night",
            concept_id="surface_temperature",
            domain="land",
            record_years=24,
            noise_level=0.8,
        ),
        "soil_moisture": VariableInfo(
            variable_id="soil_moisture",
            concept_id="soil_moisture",
            domain="hydrology",
            record_years=40,
            noise_level=1.0,
        ),
        "ndvi": VariableInfo(
            variable_id="ndvi",
            concept_id="vegetation",
            domain="land",
            record_years=24,
            noise_level=0.9,
        ),
        "no2": VariableInfo(
            variable_id="no2",
            concept_id="no2",
            domain="composition",
            record_years=20,
            noise_level=1.1,
        ),
        "snow_cover": VariableInfo(
            variable_id="snow_cover",
            concept_id="snow",
            domain="cryosphere",
            record_years=24,
            noise_level=1.0,
        ),
        "precip": VariableInfo(
            variable_id="precip",
            concept_id="precipitation",
            domain="hydrology",
            record_years=25,
            noise_level=1.4,
        ),
        "precip_gpcp": VariableInfo(
            variable_id="precip_gpcp",
            concept_id="precipitation",
            domain="hydrology",
            record_years=45,
            noise_level=1.3,
        ),
    }
    regions: dict[str, RegionFeatures] = {}
    labels: list[PotentialLabel] = []
    sig = lambda z: 1 / (1 + math.exp(-z))  # noqa: E731
    for k in range(n_regions):
        lat = math.degrees(math.asin(rng.uniform(-0.95, 0.98)))
        lon = float(rng.uniform(-180, 180))
        abs_lat = abs(lat)
        clim_t = 28 - 0.55 * abs_lat + rng.normal(0, 3)
        aridity = float(np.exp(rng.normal(-0.2, 0.9)))
        built = float(np.clip(rng.beta(0.6, 8), 0, 1))
        crop = float(np.clip(rng.beta(1, 3), 0, 1))
        forest = float(np.clip(rng.beta(1, 2) * (1 - crop), 0, 1))
        pop = float(10 ** rng.normal(1.5, 1.0))
        growth = float(rng.normal(8, 10))
        rid = f"syn_{k}"
        regions[rid] = RegionFeatures(
            region_id=rid,
            lat=lat,
            lon=lon,
            area_km2=float(10 ** rng.uniform(3, 6)),
            coast_share=float(rng.beta(1, 4)),
            elev_mean_m=float(abs(rng.normal(400, 500))),
            elev_range_m=float(abs(rng.normal(800, 700))),
            land_cover={
                "forest": forest,
                "cropland": crop,
                "urban": built,
                "barren": float(np.clip(0.6 - aridity, 0, 1)),
            },
            clim_t_c=clim_t,
            aridity_index=aridity,
            pop_density=pop,
            pop_change_pct=growth,
            built_share=built,
            seasonal_amplitude_c=float(abs(5 + 0.4 * abs_lat + rng.normal(0, 3))),
        )
        for season in ("annual", "JJA"):
            for vid in variables:
                z: float
                s_pos: float
                if vid in ("t2m", "lst_night"):
                    z, s_pos = 0.5 + 0.06 * (abs_lat - 30), 0.92
                elif vid == "soil_moisture":
                    z, s_pos = 1.5 - 4.0 * min(aridity, 1.0), 0.15
                elif vid == "ndvi":
                    z, s_pos = -1.5 + 4.0 * crop + (1.0 if clim_t < 5 else 0.0), 0.85
                elif vid == "no2":
                    z = -2.0 + 0.9 * math.log10(1 + pop) + 0.08 * max(growth, 0)
                    s_pos = 0.8 if growth > 15 else 0.2
                elif vid == "snow_cover":
                    z, s_pos = -3.0 + 0.08 * abs_lat, 0.1
                else:
                    z, s_pos = -1.6, 0.5
                if season == "JJA":
                    z -= 0.3
                p = sig(z)
                is_sig = bool(rng.random() < p)
                sign = 1 if rng.random() < s_pos else -1
                snr = float(abs(rng.normal(0.6 if is_sig else 0.15, 0.15)))
                labels.append(PotentialLabel(rid, vid, season, is_sig, sign, snr))
    return labels, regions, variables


__all__ = [
    "LABEL_Q",
    "PotentialDataset",
    "PotentialLabel",
    "build_dataset",
    "labels_from_candidates",
    "random_region_masks",
    "region_features_from_rasters",
    "spatial_block",
    "synthetic_world",
]
