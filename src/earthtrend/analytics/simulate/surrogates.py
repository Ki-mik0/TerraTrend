"""Surrogates with known truth (section 12): null series that look like real data.

* ``iaaft`` - Iterative Amplitude Adjusted Fourier Transform (Schreiber & Schmitz 1996):
  keeps the power spectrum (autocorrelation) and the value distribution of a template,
  destroys everything else, including any trend (the template is detrended first).
* ``skewed_ar1`` - AR(1) dependence with a gamma marginal (precipitation-like), by
  rank-mapping a Gaussian AR(1) onto gamma quantiles.
* ``with_witness`` - a second dataset that shares a common (null) signal with the first,
  as two reanalyses of the same weather would: the hard case for false "proven".
* ``insert_trend`` / ``insert_step`` / ``apply_gaps`` - plant known signals and real gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats

from earthtrend.analytics.simulate.synthetic import ar1_noise


def _detrend(x: np.ndarray) -> np.ndarray:
    t = np.arange(x.size, dtype=np.float64)
    coef = np.polyfit(t, x, 1)
    return x - np.polyval(coef, t)


def _fill_gaps(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(x)
    if ok.all():
        return x.copy(), ok
    filled = np.interp(np.arange(x.size), np.flatnonzero(ok), x[ok])
    return filled, ok


def iaaft(
    template: np.ndarray, rng: np.random.Generator, n_iter: int = 100, keep_gaps: bool = True
) -> np.ndarray:
    """One IAAFT surrogate of ``template`` (gaps interpolated, then re-applied)."""
    x, ok = _fill_gaps(np.asarray(template, dtype=np.float64))
    x = _detrend(x)
    amplitudes = np.abs(np.fft.rfft(x))
    sorted_x = np.sort(x)
    s = rng.permutation(x)
    for _ in range(n_iter):
        phases = np.angle(np.fft.rfft(s))
        s = np.fft.irfft(amplitudes * np.exp(1j * phases), n=x.size)
        ranks = np.argsort(np.argsort(s))
        new = sorted_x[ranks]
        if np.array_equal(new, s):
            break
        s = new
    if keep_gaps:
        s = s.copy()
        s[~ok] = np.nan
    return s


def iaaft_window(
    template: np.ndarray, n: int, rng: np.random.Generator, n_iter: int = 100
) -> np.ndarray:
    """IAAFT surrogate of the whole template, then a random window of length ``n``.

    FFT surrogates are circular: the end must join the start, which suppresses
    low-frequency drift across the record and makes trend tests look too conservative.
    Cutting a window of at most half the template length breaks that constraint.
    """
    if template.size < 2 * n:
        raise ValueError("template must be at least twice the requested length")
    s = iaaft(template, rng, n_iter)
    start = int(rng.integers(0, template.size - n + 1))
    return s[start : start + n]


def iaaft_surrogate(anomalies: np.ndarray, n_iter: int = 100, seed: int = 0) -> np.ndarray:
    """PLAN_ANALYTICS section 12 signature for :func:`iaaft`."""
    return iaaft(np.asarray(anomalies, dtype=np.float64), np.random.default_rng(seed), n_iter)


SignalKind = Literal["none", "linear", "step", "accel", "trend_plus_step"]


@dataclass(frozen=True)
class Label:
    """Ground truth of an injected signal (training labels for M1, section 11.2)."""

    kind: SignalKind
    slope_per_decade: float
    step_size: float
    step_index: int | None
    accel_per_decade2: float


def inject_signal(
    series: np.ndarray,
    kind: SignalKind,
    snr: float,
    when: float | None = None,
    seed: int = 0,
    step_years: float = 1 / 12,
) -> tuple[np.ndarray, Label]:
    """Plant a signal of a given signal-to-noise ratio into a null series (section 12).

    SNR follows section 6.1: |slope per decade| / sigma of the series (for ``step`` the
    step size is ``snr * sigma``; for ``accel`` the change of slope across the record is
    ``snr * sigma`` per decade). ``when`` is the step position as a share of the record
    (random in [0.2, 0.8] when None).
    """
    x = np.asarray(series, dtype=np.float64)
    rng = np.random.default_rng(seed)
    sigma = float(np.nanstd(x))
    n = x.size
    t_dec = np.arange(n) * step_years / 10.0
    slope = step_size = accel = 0.0
    idx: int | None = None
    out = x.copy()
    if kind in ("linear", "trend_plus_step"):
        slope = snr * sigma * float(rng.choice([-1.0, 1.0]))
        out = out + slope * t_dec
    if kind in ("step", "trend_plus_step"):
        pos = when if when is not None else float(rng.uniform(0.2, 0.8))
        idx = int(round(pos * n))
        step_size = snr * sigma * float(rng.choice([-1.0, 1.0]))
        out[idx:] += step_size
    if kind == "accel":
        span = max(t_dec[-1], 1e-12)
        accel = snr * sigma / (2 * span) * float(rng.choice([-1.0, 1.0]))
        out = out + accel * t_dec**2
    if kind not in ("none", "linear", "step", "accel", "trend_plus_step"):
        raise ValueError(f"unknown kind {kind!r}")
    return out, Label(kind, slope, step_size, idx, accel)


def deseasonalize(x: np.ndarray, period: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Remove the mean cycle; returns (anomalies, cycle) so IAAFT works on anomalies."""
    cycle = np.array([np.nanmean(x[i::period]) for i in range(period)])
    reps = np.resize(cycle, x.size)
    return x - reps, reps


def skewed_ar1(
    n: int, phi: float, rng: np.random.Generator, shape: float = 2.0, scale: float = 1.0
) -> np.ndarray:
    g = ar1_noise(n, phi, np.sqrt(1 - phi**2), rng)  # unit-variance Gaussian AR(1)
    u = stats.norm.cdf(g)
    return stats.gamma.ppf(u, a=shape, scale=scale)


def with_witness(
    n: int, phi: float, rng: np.random.Generator, shared: float = 0.8
) -> tuple[np.ndarray, np.ndarray]:
    """Two null series with correlation ``shared`` in their (AR(1)) weather signal."""
    common = ar1_noise(n, phi, 1.0, rng)
    own_a = ar1_noise(n, phi, 1.0, rng)
    own_b = ar1_noise(n, phi, 1.0, rng)
    w = np.sqrt(shared)
    v = np.sqrt(1 - shared)
    return w * common + v * own_a, w * common + v * own_b


def insert_trend(x: np.ndarray, slope_per_decade: float, step_years: float = 1 / 12) -> np.ndarray:
    t = np.arange(x.size) * step_years
    return x + slope_per_decade / 10.0 * t


def insert_step(x: np.ndarray, at: int, size: float) -> np.ndarray:
    out = x.copy()
    out[at:] += size
    return out


def apply_gaps(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """``mask`` True where the value is missing (e.g. taken from a real record)."""
    out = x.astype(np.float64).copy()
    out[np.asarray(mask, dtype=bool)] = np.nan
    return out
