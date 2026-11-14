"""Training data for M1 TrendNet (PLAN_ANALYTICS section 11.2), generated on the fly.

Every example: a null noise series (true structure, no trend) + a planted signal of known
kind and strength + nuisances + a gap mask -> model input and exact labels.

Noise families and the leakage-proof split
-------------------------------------------
Real cell series are not available yet, so noise comes from synthetic families that mimic
what real variables look like. The split keeps families and template seeds apart:

* ``train`` / ``val`` - the training families; val uses a disjoint seed range
  (the stand-in for "other cells, spatial blocks");
* ``new_places`` - training families, yet another seed range (held-out geography);
* ``new_variables`` - families the model never sees in training (log-normal skewed
  "NO2-like", very smooth red "GRACE-like", long memory);
* ``theory`` - plain Gaussian AR(1), to compare with the classical tests.

When real data exists, IAAFT surrogates of real cells replace the synthetic templates
(``iaaft`` family) without changing anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from earthtrend.analytics.simulate.surrogates import iaaft
from earthtrend.analytics.simulate.synthetic import ar1_noise, fractional_noise

CLASSES = ("no_trend", "linear", "step", "accelerating", "trend_plus_step")
N_CLASSES = len(CLASSES)
MAX_YEARS = 45
MIN_YEARS = 10
MAX_LEN = MAX_YEARS * 12
N_CHANNELS = 5  # z, missing, sin(month), cos(month), time position

Split = Literal["train", "val", "new_places", "new_variables", "theory"]
TRAIN_FAMILIES = ("ar1", "arma", "student_t", "iaaft_red", "seasonal_amp")
NEW_VARIABLE_FAMILIES = ("lognormal", "smooth_red", "long_memory")
SEED_BASE = {
    "train": 0,
    "val": 10_000_000,
    "new_places": 20_000_000,
    "new_variables": 30_000_000,
    "theory": 40_000_000,
}
NO_SIGNAL_SHARE = 0.4


@dataclass(frozen=True)
class Example:
    features: np.ndarray  # (N_CHANNELS, MAX_LEN) float32
    mask: np.ndarray  # (MAX_LEN,) float32, 1 = real time step (even if the value is missing)
    label: int  # index into CLASSES
    slope: float  # trend component, robust-z units per decade
    step_target: np.ndarray  # (MAX_LEN,) float32, step position (smoothed +-1 month)
    family: str
    snr: float
    n_years: int
    scale: float  # robust scale used for z (to convert slopes back to data units)


# ---------------------------------------------------------------- noise families


def _unit(x: np.ndarray) -> np.ndarray:
    s = float(np.std(x))
    return (x - x.mean()) / s if s > 0 else x


def noise(family: str, n: int, rng: np.random.Generator) -> np.ndarray:
    """Unit-variance null series of a family (no trend)."""
    if family == "ar1":
        x = ar1_noise(n, float(rng.uniform(0.0, 0.9)), 1.0, rng)
    elif family == "arma":
        phi1, phi2 = float(rng.uniform(0.2, 0.9)), float(rng.uniform(-0.3, 0.0))
        e = rng.normal(size=n + 200)
        x = np.zeros(n + 200)
        for i in range(2, n + 200):
            x[i] = phi1 * x[i - 1] + phi2 * x[i - 2] + e[i] + 0.3 * e[i - 1]
        x = x[200:]
    elif family == "student_t":
        phi = float(rng.uniform(0.0, 0.8))
        e = rng.standard_t(4, n)
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = phi * x[i - 1] + e[i]
    elif family == "iaaft_red":
        tpl = ar1_noise(4 * n, float(rng.uniform(0.3, 0.8)), 1.0, rng)
        tpl += float(rng.uniform(0.0, 0.8)) * fractional_noise(4 * n, 0.2, rng)
        start = int(rng.integers(0, 3 * n))
        x = iaaft(tpl, rng, n_iter=30)[start : start + n]
    elif family == "seasonal_amp":
        x = ar1_noise(n, float(rng.uniform(0.2, 0.7)), 1.0, rng)
        month = np.arange(n) % 12
        x = x + float(rng.uniform(0.3, 1.0)) * np.sin(2 * np.pi * month / 12) * np.linspace(
            -1, 1, n
        )  # residual seasonality whose amplitude changes (not a trend)
    elif family == "lognormal":
        x = np.exp(0.6 * ar1_noise(n, float(rng.uniform(0.2, 0.7)), 1.0, rng))
    elif family == "smooth_red":
        x = ar1_noise(n, float(rng.uniform(0.93, 0.98)), 1.0, rng)
    elif family == "long_memory":
        x = fractional_noise(n, float(rng.uniform(0.15, 0.4)), rng)
    elif family == "theory":
        x = ar1_noise(n, float(rng.uniform(0.0, 0.8)), 1.0, rng)
    else:
        raise ValueError(family)
    return _unit(x)


def _families(split: Split) -> tuple[str, ...]:
    if split == "new_variables":
        return NEW_VARIABLE_FAMILIES
    if split == "theory":
        return ("theory",)
    return TRAIN_FAMILIES


# ---------------------------------------------------------------- signals and nuisances


def _signal(
    kind: str, n: int, rng: np.random.Generator, min_snr: float
) -> tuple[np.ndarray, float, int | None, float]:
    """Return (signal, slope per decade of the trend component, step index, snr)."""
    t_dec = np.arange(n) / 120.0
    sig = np.zeros(n)
    slope = 0.0
    idx: int | None = None
    snr = 0.0
    sign = float(rng.choice([-1.0, 1.0]))
    if kind in ("linear", "trend_plus_step"):
        snr = float(np.exp(rng.uniform(np.log(min_snr), np.log(2.0))))
        slope = sign * snr
        sig += slope * t_dec
    if kind in ("step", "trend_plus_step"):
        idx = int(rng.integers(int(0.15 * n), int(0.85 * n)))
        size = float(np.exp(rng.uniform(np.log(0.3), np.log(3.0)))) * float(rng.choice([-1, 1]))
        sig[idx:] += size
        snr = max(snr, abs(size))
    if kind == "accelerating":
        end_snr = float(np.exp(rng.uniform(np.log(max(min_snr, 0.1)), np.log(3.0))))
        span = t_dec[-1]
        if rng.random() < 0.5:  # quadratic: slope grows from 0 to end_snr
            sig = sign * end_snr * t_dec**2 / (2 * span)
        else:  # hinge: flat, then a trend from a random knot
            knot = float(rng.uniform(0.3, 0.7)) * span
            sig = sign * end_snr * np.clip(t_dec - knot, 0, None)
        slope = float(np.polyfit(t_dec, sig, 1)[0])  # mean slope of the record
        snr = end_snr
    return sig, slope, idx, snr


def _nuisance(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = x.size
    if rng.random() < 0.3:  # ENSO-like oscillation: natural variability, not a trend
        x = x + float(rng.uniform(0.1, 0.6)) * ar1_noise(n, 0.93, np.sqrt(1 - 0.93**2), rng)
    if rng.random() < 0.2:  # outliers
        k = int(rng.integers(1, 4))
        x = x.copy()
        x[rng.integers(0, n, k)] += rng.choice([-1, 1], k) * rng.uniform(4, 6, k)
    return x


def _gaps(n: int, rng: np.random.Generator) -> np.ndarray:
    miss = np.zeros(n, dtype=bool)
    r = rng.random()
    if r < 0.3:
        miss |= rng.random(n) < rng.uniform(0.0, 0.2)
    elif r < 0.5:
        length = int(rng.integers(6, max(7, n // 6)))
        start = int(rng.integers(0, n - length))
        miss[start : start + length] = True
    return miss


# ---------------------------------------------------------------- features


def featurize(
    values: np.ndarray, months: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Model input from a monthly anomaly series (gaps as NaN), padded to MAX_LEN.

    Channels: robust z = (x - median) / (1.4826 MAD), missing flag, sin/cos of the month,
    time position in [0, 1]. Returns (features, mask, center, scale).
    """
    n = values.size
    if n > MAX_LEN:
        values, months, n = values[-MAX_LEN:], months[-MAX_LEN:], MAX_LEN
    ok = np.isfinite(values)
    center = float(np.median(values[ok])) if ok.any() else 0.0
    mad = float(np.median(np.abs(values[ok] - center))) * 1.4826 if ok.any() else 1.0
    scale = mad if mad > 1e-12 else (float(np.std(values[ok])) or 1.0)
    z = np.where(ok, (values - center) / scale, 0.0)
    feats = np.zeros((N_CHANNELS, MAX_LEN), dtype=np.float32)
    feats[0, :n] = np.clip(z, -10, 10)
    feats[1, :n] = (~ok).astype(np.float32)
    feats[2, :n] = np.sin(2 * np.pi * (months - 1) / 12)
    feats[3, :n] = np.cos(2 * np.pi * (months - 1) / 12)
    feats[4, :n] = np.linspace(0.0, 1.0, n)
    mask = np.zeros(MAX_LEN, dtype=np.float32)
    mask[:n] = 1.0
    return feats, mask, center, scale


# ---------------------------------------------------------------- examples


def make_example(
    split: Split, index: int, min_snr: float = 0.05, label: int | None = None
) -> Example:
    """Deterministic in (split, index): the same call always returns the same example."""
    rng = np.random.default_rng(SEED_BASE[split] + index)
    n_years = int(rng.integers(MIN_YEARS, MAX_YEARS + 1))
    n = n_years * 12
    fam = str(rng.choice(_families(split)))
    if label is None:
        label = 0 if rng.random() < NO_SIGNAL_SHARE else int(rng.integers(1, N_CLASSES))
    x = noise(fam, n, rng)
    sig, slope, idx, snr = _signal(CLASSES[label], n, rng, min_snr)
    x = _nuisance(x + sig, rng)
    x[_gaps(n, rng)] = np.nan
    start_month = int(rng.integers(1, 13))
    months = (np.arange(n) + start_month - 1) % 12 + 1
    feats, mask, _, scale = featurize(x, months)
    step = np.zeros(MAX_LEN, dtype=np.float32)
    if idx is not None:
        step[idx] = 1.0
        step[max(idx - 1, 0)] = max(step[max(idx - 1, 0)], 0.5)
        if idx + 1 < n:
            step[idx + 1] = 0.5
    return Example(
        features=feats,
        mask=mask,
        label=label,
        slope=slope / scale,  # noise is unit-variance; express slope in robust-z units
        step_target=step,
        family=fam,
        snr=snr,
        n_years=n_years,
        scale=scale,
    )


def batch(split: Split, indices: range | list[int], min_snr: float = 0.05) -> dict[str, np.ndarray]:
    exs = [make_example(split, i, min_snr) for i in indices]
    return {
        "features": np.stack([e.features for e in exs]),
        "mask": np.stack([e.mask for e in exs]),
        "label": np.array([e.label for e in exs], dtype=np.int64),
        "slope": np.array([e.slope for e in exs], dtype=np.float32),
        "step": np.stack([e.step_target for e in exs]),
        "snr": np.array([e.snr for e in exs], dtype=np.float32),
        "n_years": np.array([e.n_years for e in exs], dtype=np.int64),
    }
