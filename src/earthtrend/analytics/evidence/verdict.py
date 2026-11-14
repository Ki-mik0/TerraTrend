"""Verdict rules for the Stage 1 slice (``verdict_rules_v0``).

Only the ``statistics`` and ``quality`` items of the full protocol exist yet, so the
verdict has three values. ``verdict_rules_v1`` (section 6.8) replaces this in Stage 3.

* ``inadmissible`` - record shorter than ``min_years_for_trend``, constant series,
  or the tests could not run.
* ``strong``       - OLS with n_eff on annual means p < alpha AND Mann-Kendall (AR(1)-corrected)
  confirms with the same sign at p < MK_CONFIRM_P (Stage 4 calibration).
* ``no_evidence``  - anything else.

``strength`` uses the v1 weights of the items that exist (statistics 30, quality 10,
magnitude 5), so in the slice it never exceeds 45.
"""

from __future__ import annotations

import math

from earthtrend.analytics import config
from earthtrend.analytics.models import Magnitude, QualityFlag, TrendTest, Verdict

INADMISSIBLE_FLAGS = frozenset({"short_record", "constant_series"})
CAVEAT_FLAGS = ("many_gaps", "low_stable_coverage", "outliers", "low_n_eff")


def _sign(x: float | None) -> int:
    if x is None or not math.isfinite(x) or x == 0:
        return 0
    return 1 if x > 0 else -1


def decide(
    *,
    flags: list[QualityFlag],
    ols: TrendTest | None,
    mk: TrendTest | None,
    magnitude: Magnitude | None,
    alpha: float = config.ALPHA,
    ols_annual: TrendTest | None = None,
) -> Verdict:
    """Stage 1 verdict (``verdict_rules_v0``): strong when annual-mean OLS p < alpha and MK
    confirms with the same sign at p < MK_CONFIRM_P; inadmissible on QC; else no_evidence.
    """
    codes = {f.code for f in flags}
    caveats = [c for c in CAVEAT_FLAGS if c in codes]

    if codes & INADMISSIBLE_FLAGS or ols is None or mk is None:
        return Verdict(code="inadmissible", strength=0, direction="none", caveats=caveats)

    # Stage 4 calibration: annual-mean OLS is the primary test; MK confirms at a looser p.
    primary = ols_annual if ols_annual is not None and ols_annual.p_value is not None else ols
    sig_ols = primary.p_value is not None and primary.p_value < alpha
    sig_mk = mk.p_value is not None and mk.p_value < config.MK_CONFIRM_P
    s_ols, s_mk = _sign(primary.slope_per_decade), _sign(mk.statistic)
    strong = sig_ols and sig_mk and s_ols == s_mk != 0

    if sig_ols != sig_mk or (sig_ols and sig_mk and s_ols != s_mk):
        caveats.append("methods_disagree")

    w = config.STRENGTH_WEIGHTS
    strength = 0.0
    if strong:
        strength += w["statistics"]
    elif sig_ols or sig_mk:
        strength += w["statistics"] / 2
    if not any(c in codes for c in CAVEAT_FLAGS):
        strength += w["quality"]
    if magnitude is not None:
        strength += {"strong": 1.0, "moderate": 0.5, "weak": 0.0}[magnitude.snr_class] * w[
            "magnitude"
        ]

    direction = "none"
    if strong:
        direction = "increasing" if s_mk > 0 else "decreasing"
    return Verdict(
        code="strong" if strong else "no_evidence",
        strength=round(strength),
        direction=direction,
        caveats=caveats,
    )
