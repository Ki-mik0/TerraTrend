"""Seeded parametric generator of monthly series with known truth (section 12).

series = base + seasonal cycle + linear trend + optional step + AR(1) noise, with optional gaps.
Used by tests and Monte-Carlo checks; later by the Lab simulators (test vectors).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from earthtrend.analytics.models import RegionalSeries, SeriesMeta


@dataclass(frozen=True)
class SyntheticTruth:
    slope_per_decade: float
    phi: float
    sigma: float  # innovation std of the AR(1) noise
    step_size: float
    step_index: int | None


def ar1_noise(n: int, phi: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Stationary AR(1): e_0 ~ N(0, sigma^2 / (1 - phi^2)), e_t = phi e_(t-1) + N(0, sigma^2)."""
    if not -1 < phi < 1:
        raise ValueError("phi must lie in (-1, 1)")
    e = np.empty(n)
    e[0] = rng.normal(0.0, sigma / np.sqrt(1 - phi**2))
    eps = rng.normal(0.0, sigma, n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + eps[i]
    return e


def generate_monthly(
    *,
    n_years: int = 40,
    start_year: int = 1981,
    base: float = 0.0,
    seasonal_amplitude: float = 0.0,
    slope_per_decade: float = 0.0,
    phi: float = 0.0,
    sigma: float = 1.0,
    gap_fraction: float = 0.0,
    step_size: float = 0.0,
    step_index: int | None = None,
    seed: int = 0,
) -> tuple[list[date], np.ndarray, SyntheticTruth]:
    """Monthly series = base + seasonal sine + linear trend + optional step + AR(1) noise,
    with optional random gaps; returns (dates, values, truth). Seeded (section 12).
    """
    rng = np.random.default_rng(seed)
    n = n_years * 12
    dates = [date(start_year + i // 12, i % 12 + 1, 1) for i in range(n)]
    t_years = (np.arange(n) + 0.5) / 12.0
    month_idx = np.arange(n) % 12
    values = (
        base
        + seasonal_amplitude * np.sin(2 * np.pi * (month_idx - 3) / 12)
        + slope_per_decade / 10.0 * t_years
        + ar1_noise(n, phi, sigma, rng)
    )
    if step_index is not None and step_size:
        values[step_index:] += step_size
    if gap_fraction > 0:
        gaps = rng.random(n) < gap_fraction
        values[gaps] = np.nan
    truth = SyntheticTruth(slope_per_decade, phi, sigma, step_size, step_index)
    return dates, values, truth


def default_meta(**overrides: object) -> SeriesMeta:
    """``SeriesMeta`` with placeholder ids for synthetic data; ``overrides`` replace fields."""
    data: dict[str, object] = {
        "variable_id": "synthetic",
        "concept_id": "synthetic",
        "dataset_id": "synthetic",
        "dataset_version": "0",
        "units": "1",
        "region_id": "synthetic",
    }
    data.update(overrides)
    return SeriesMeta.model_validate(data)


def synthetic_case(
    meta: SeriesMeta | None = None, **kwargs: object
) -> tuple[RegionalSeries, SyntheticTruth]:
    """``generate_monthly(**kwargs)`` wrapped into a ``RegionalSeries``, plus the truth."""
    dates, values, truth = generate_monthly(**kwargs)  # type: ignore[arg-type]
    series = RegionalSeries(
        meta=meta or default_meta(),
        dates=dates,
        values=[None if np.isnan(v) else float(v) for v in values],
    )
    return series, truth


def generate_grid(
    *,
    slope_field: np.ndarray,
    n_years: int = 40,
    start_year: int = 1981,
    base: float = 0.0,
    seasonal_amplitude: float = 0.0,
    phi: float = 0.0,
    sigma: float = 1.0,
    seed: int = 0,
) -> tuple[list[date], np.ndarray]:
    """Monthly cube (time, lat, lon): per-cell trend ``slope_field`` (per decade) + AR(1) noise.

    Noise is independent between cells (no spatial correlation).
    """
    if not -1 < phi < 1:
        raise ValueError("phi must lie in (-1, 1)")
    rng = np.random.default_rng(seed)
    slope_field = np.asarray(slope_field, dtype=np.float64)
    n = n_years * 12
    dates = [date(start_year + i // 12, i % 12 + 1, 1) for i in range(n)]
    t_years = (np.arange(n) + 0.5) / 12.0
    month_idx = np.arange(n) % 12
    noise = np.empty((n, *slope_field.shape))
    noise[0] = rng.normal(0.0, sigma / np.sqrt(1 - phi**2), slope_field.shape)
    for i in range(1, n):
        noise[i] = phi * noise[i - 1] + rng.normal(0.0, sigma, slope_field.shape)
    seasonal = seasonal_amplitude * np.sin(2 * np.pi * (month_idx - 3) / 12)
    cube = (
        base + seasonal[:, None, None] + (slope_field[None] / 10.0) * t_years[:, None, None] + noise
    )
    return dates, cube


def fractional_noise(n: int, d: float, rng: np.random.Generator, burn: int = 2000) -> np.ndarray:
    """ARFIMA(0, d, 0) noise (long memory for 0 < d < 0.5), truncated MA(inf) weights."""
    from scipy.special import gammaln

    if not 0 < d < 0.5:
        raise ValueError("d must lie in (0, 0.5)")
    k = np.arange(1, n + burn)
    psi = np.r_[1.0, np.exp(gammaln(k + d) - gammaln(k + 1) - gammaln(d))]
    e = rng.normal(size=n + burn)
    return np.convolve(e, psi)[: n + burn][burn:]


def synthetic_series(
    n_years: int = 25,
    trend_per_decade: float = 0.3,
    noise_sd: float = 0.5,
    ar1: float = 0.3,
    season_amp: float = 5.0,
    step: tuple[int, float] | None = None,
    accel: float | None = None,
    gaps: float = 0.0,
    noise: str = "gaussian",
    seed: int = 0,
    *,
    start_year: int = 1981,
    base: float = 0.0,
    meta: SeriesMeta | None = None,
) -> RegionalSeries:
    """Parametric generator with the signature of PLAN_ANALYTICS section 12.

    * ``noise_sd`` - marginal standard deviation of the AR(1) noise (lag-1 = ``ar1``);
    * ``noise`` - ``"gaussian"`` or ``"student_t"`` (5 d.o.f., rescaled to ``noise_sd``);
    * ``step`` - ``(year, size)``: level shift from January of ``year``;
    * ``accel`` - quadratic term, units per decade squared (curvature of the trend);
    * ``gaps`` - share of months removed at random.

    Returns a ``RegionalSeries`` (the plan says ``pd.Series``; the analytics API works on
    ``RegionalSeries`` and pandas is not a dependency).
    """
    if not -1 < ar1 < 1:
        raise ValueError("ar1 must lie in (-1, 1)")
    rng = np.random.default_rng(seed)
    n = n_years * 12
    innov_sd = noise_sd * np.sqrt(1 - ar1**2)
    if noise == "gaussian":
        eps = rng.normal(0.0, 1.0, n)
    elif noise == "student_t":
        eps = rng.standard_t(5, n) / np.sqrt(5 / 3)
    else:
        raise ValueError(f"unknown noise {noise!r}")
    e = np.empty(n)
    e[0] = noise_sd * eps[0]
    for i in range(1, n):
        e[i] = ar1 * e[i - 1] + innov_sd * eps[i]
    t_dec = (np.arange(n) + 0.5) / 120.0
    month_idx = np.arange(n) % 12
    x = base + season_amp * np.sin(2 * np.pi * (month_idx - 3) / 12) + trend_per_decade * t_dec + e
    if accel:
        x = x + accel * (t_dec - t_dec.mean()) ** 2
    if step is not None:
        year, size = step
        x[max(0, (year - start_year) * 12) :] += size
    if gaps > 0:
        x[rng.random(n) < gaps] = np.nan
    dates = [date(start_year + i // 12, i % 12 + 1, 1) for i in range(n)]
    return RegionalSeries(
        meta=meta or default_meta(),
        dates=dates,
        values=[None if np.isnan(v) else float(v) for v in x],
    )
