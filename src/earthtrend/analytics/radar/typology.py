"""Change typology (docs/PLAN_ANALYTICS.md section 8.5), used by the Radar map.

Features of a unit (region or grid cell) = signed SNR of several variables -> standardized
-> k-means with k chosen by the mean silhouette in 4..10 (or HDBSCAN when scikit-learn is
installed). A missing value becomes 0 after standardization (the variable's mean).
Cluster name = sign pattern of the centroid in signed SNR: + / - when |SNR| >= 0.2
(``SNR_MODERATE``), else 0.

k-means: ``scipy.cluster.vq.kmeans2`` (k-means++), best of ``n_init`` seeded starts.
The silhouette is computed on at most ``max_silhouette`` units (seeded sample).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.cluster.vq import kmeans2
from scipy.spatial.distance import cdist

from earthtrend.analytics import config
from earthtrend.analytics.radar.models import RadarCandidate, TypologyCluster, TypologyResult

F = NDArray[np.float64]
MIN_UNITS = 8  # below this a typology is meaningless


def silhouette(x: F, labels: NDArray[np.int64]) -> float:
    """Mean silhouette (Rousseeuw 1987); units in singleton clusters score 0."""
    uniq = np.unique(labels)
    if uniq.size < 2:
        return float("nan")
    d = cdist(x, x)
    s = np.zeros(x.shape[0])
    for i in range(x.shape[0]):
        own = labels == labels[i]
        n_own = own.sum() - 1
        if n_own == 0:
            continue
        a = d[i, own].sum() / n_own
        b = min(d[i, labels == u].mean() for u in uniq if u != labels[i])
        s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean())


def _kmeans(z: F, k: int, seed: int, n_init: int) -> tuple[NDArray[np.int64], float]:
    best_lab: NDArray[np.int64] | None = None
    best_inertia = np.inf
    for i in range(n_init):
        cent, lab = kmeans2(z, k, minit="++", seed=np.random.default_rng(seed + i))
        inertia = float(((z - cent[lab]) ** 2).sum())
        if inertia < best_inertia:
            best_inertia, best_lab = inertia, lab.astype(np.int64)
    assert best_lab is not None
    return best_lab, best_inertia


def _relabel(labels: NDArray[np.int64]) -> NDArray[np.int64]:
    """Cluster ids by decreasing size (0 = largest), noise (-1) kept; deterministic."""
    uniq, counts = np.unique(labels[labels >= 0], return_counts=True)
    order = uniq[np.lexsort((uniq, -counts))]
    mapping = {int(u): i for i, u in enumerate(order)}
    return np.array([mapping.get(int(v), -1) for v in labels], dtype=np.int64)


def _code(signs: dict[str, int]) -> str:
    parts = [f"{v}{'+' if s > 0 else '-'}" for v, s in signs.items() if s != 0]
    return "|".join(parts) if parts else "no_change"


def change_typology(
    signed_snr: F,
    variables: Sequence[str],
    units: Sequence[str],
    *,
    method: Literal["kmeans", "hdbscan"] = "kmeans",
    k_range: tuple[int, int] = (4, 10),
    seed: int = 42,
    n_init: int = 5,
    max_silhouette: int = 2000,
    season: str | None = None,
) -> TypologyResult | None:
    """``signed_snr``: (units, variables), NaN allowed. None if too few units / variables."""
    x = np.asarray(signed_snr, dtype=np.float64)
    if x.ndim != 2 or x.shape != (len(units), len(variables)):
        raise ValueError("signed_snr must have shape (len(units), len(variables))")
    n = x.shape[0]
    if n < MIN_UNITS or x.shape[1] < 2:
        return None
    with np.errstate(invalid="ignore"):
        mu = np.nanmean(np.where(np.isfinite(x), x, np.nan), axis=0)
        sd = np.nanstd(np.where(np.isfinite(x), x, np.nan), axis=0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
    z = np.where(np.isfinite(x), (x - mu) / sd, 0.0)

    rng = np.random.default_rng(seed)
    sample = np.sort(rng.choice(n, size=min(n, max_silhouette), replace=False))

    used: Literal["kmeans", "hdbscan"] = "kmeans"
    labels: NDArray[np.int64] | None = None
    sil: float | None = None
    k = 1
    if method == "hdbscan":
        try:
            from sklearn.cluster import HDBSCAN

            mcs = max(5, n // 50)
            try:
                model = HDBSCAN(min_cluster_size=mcs, copy=True)  # explicit since sklearn 1.8
            except TypeError:  # older scikit-learn without ``copy``
                model = HDBSCAN(min_cluster_size=mcs)
            lab = model.fit_predict(z).astype(np.int64)
            if np.unique(lab[lab >= 0]).size >= 2:
                labels, used = lab, "hdbscan"
                k = int(np.unique(lab[lab >= 0]).size)
                ok = sample[lab[sample] >= 0]
                sil = silhouette(z[ok], lab[ok]) if ok.size > k else None
        except ImportError:
            pass  # scikit-learn is optional; fall back to k-means
    if labels is None:
        k_lo, k_hi = k_range[0], min(k_range[1], n - 1)
        best: tuple[float, int, NDArray[np.int64]] | None = None
        for kk in range(max(2, k_lo), k_hi + 1):
            lab, _ = _kmeans(z, kk, seed, n_init)
            if np.unique(lab).size < 2:
                continue
            s = silhouette(z[sample], lab[sample])
            if best is None or s > best[0] + 1e-12:
                best = (s, kk, lab)
        if best is None:
            return None
        sil, k, labels = best
    labels = _relabel(labels)

    clusters: list[TypologyCluster] = []
    for cid in range(int(labels.max()) + 1):
        members = labels == cid
        with np.errstate(invalid="ignore"):
            cent = np.nanmean(np.where(np.isfinite(x[members]), x[members], np.nan), axis=0)
        cent = np.where(np.isfinite(cent), cent, 0.0)
        signs = {
            v: (0 if abs(c) < config.SNR_MODERATE else int(np.sign(c)))
            for v, c in zip(variables, cent, strict=True)
        }
        clusters.append(
            TypologyCluster(
                id=cid,
                code=_code(signs),
                signs=signs,
                centroid_snr={v: round(float(c), 4) for v, c in zip(variables, cent, strict=True)},
                size=int(members.sum()),
            )
        )
    return TypologyResult(
        method=used,
        season=season,
        variables=list(variables),
        k=k,
        silhouette=None if sil is None or not np.isfinite(sil) else round(float(sil), 4),
        clusters=clusters,
        assignments={u: int(c) for u, c in zip(units, labels, strict=True)},
    )


def typology_from_candidates(
    candidates: Sequence[RadarCandidate],
    season: str = "annual",
    *,
    method: Literal["kmeans", "hdbscan"] = "kmeans",
    seed: int = 42,
    min_coverage: float = 0.5,
) -> TypologyResult | None:
    """Regions x variables matrix of stage 1 signed SNR for one season, then typology.

    Variables present in fewer than ``min_coverage`` of the regions are left out.
    """
    table: dict[str, dict[str, float]] = defaultdict(dict)
    for c in candidates:
        if c.season == season and c.signed_snr is not None:
            table[c.region_id][c.variable_id] = c.signed_snr
    regions = sorted(table)
    if not regions:
        return None
    counts: dict[str, int] = defaultdict(int)
    for row in table.values():
        for v in row:
            counts[v] += 1
    variables = sorted(v for v, n in counts.items() if n >= min_coverage * len(regions))
    x = np.array(
        [[table[r].get(v, np.nan) for v in variables] for r in regions], dtype=np.float64
    ).reshape(len(regions), len(variables))
    return change_typology(x, variables, regions, method=method, seed=seed, season=season)


__all__ = ["change_typology", "silhouette", "typology_from_candidates"]
