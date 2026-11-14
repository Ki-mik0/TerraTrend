"""Comparison with NASA Giovanni (section 13.4): our regional series vs Giovanni's.

Run the comparison on a regional mean built **without** the stable mask
(``regional_series(..., use_stable_mask=False)``), as Giovanni does; compare the masked
series separately to show how much the stable mask changes it.

Giovanni "Time Series, Area-Averaged" CSV: a metadata header, then ``time,<variable>``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

MISSING = {"", "NaN", "nan", "-9999", "-9999.0"}


def load_giovanni_csv(path: Path) -> tuple[list[date], list[float | None]]:
    dates: list[date] = []
    values: list[float | None] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            try:
                d = datetime.fromisoformat(row[0].strip()[:10]).date()
            except ValueError:
                continue  # header / metadata line
            raw = row[1].strip()
            dates.append(date(d.year, d.month, 1))
            values.append(None if raw in MISSING else float(raw))
    return dates, values


MIN_CORRELATION = 0.99
MAX_MAD_SHARE = 0.02  # mean absolute difference < 2% of Giovanni's range (section 13.4)


@dataclass(frozen=True)
class Agreement:
    n_common: int
    correlation: float
    mean_abs_diff: float
    bias: float  # ours - giovanni
    range_giovanni: float

    @property
    def mad_share_of_range(self) -> float:
        return self.mean_abs_diff / self.range_giovanni if self.range_giovanni > 0 else np.inf

    def passes(self) -> bool:
        """Section 13.4: correlation > 0.99 and mean abs diff < 2% of the range."""
        return (
            self.n_common >= 24
            and self.correlation > MIN_CORRELATION
            and self.mad_share_of_range < MAX_MAD_SHARE
        )


def compare(
    ours: tuple[list[date], list[float | None]], giovanni: tuple[list[date], list[float | None]]
) -> Agreement:
    a = {d: v for d, v in zip(*ours, strict=True) if v is not None}
    b = {d: v for d, v in zip(*giovanni, strict=True) if v is not None}
    common = sorted(a.keys() & b.keys())
    if len(common) < 3:
        return Agreement(len(common), float("nan"), float("nan"), float("nan"), float("nan"))
    x = np.array([a[d] for d in common])
    y = np.array([b[d] for d in common])
    return Agreement(
        n_common=len(common),
        correlation=float(np.corrcoef(x, y)[0, 1]),
        mean_abs_diff=float(np.mean(np.abs(x - y))),
        bias=float(np.mean(x - y)),
        range_giovanni=float(np.ptp(y)),
    )
