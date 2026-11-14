"""Calibration fingerprint: a hash of everything that decides a verdict.

The calibration report stores the fingerprint it was produced with. A test compares it
with the current one, so changing a threshold or a rule without re-running
``make calibrate`` fails CI (ROADMAP stage 4 completion criterion).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from earthtrend.analytics import config
from earthtrend.analytics.evidence import alibi, protocol, quality, triangle
from earthtrend.analytics.evidence.rules import RULES_DIR
from earthtrend.analytics.trend import jackknife, mann_kendall, nonlinear


def thresholds() -> dict[str, Any]:
    return {
        "config": {
            k: getattr(config, k)
            for k in (
                "ALPHA",
                "STABLE_MASK_MIN_VALID",
                "MONTH_MIN_COVERAGE",
                "LOW_STABLE_FRACTION",
                "MAX_GAP_SHARE",
                "DEFAULT_MIN_YEARS",
                "OUTLIER_Z",
                "ANNUAL_MIN_MONTHS",
                "N_EFF_MIN",
                "N_EFF_UNRELIABLE",
                "SNR_MODERATE",
                "SNR_STRONG",
                "MK_CONFIRM_P",
            )
        },
        "triangle": [triangle.SIG_P, triangle.PASS_SAME, triangle.PASS_SIG, triangle.PARTIAL_SAME],
        "quality": [
            quality.LONG_MEMORY_P,
            list(quality.LONG_MEMORY_LAGS),
            quality.ARTIFACT_WINDOW_MONTHS,
            quality.EDGE_SHARE,
            sorted(quality.FAIL_FLAGS),
            sorted(quality.WARNING_FLAGS),
        ],
        "alibi": [list(alibi.LAGS), alibi.N_FOLDS, alibi.OVERLAP_R, alibi.MIN_OVERLAP],
        "protocol": [protocol.PARTIAL_P],
        "jackknife": [jackknife.REL_CHANGE_LIMIT],
        "mann_kendall": [mann_kendall.MAX_CORRECTION, mann_kendall.TIE_RESOLUTION],
        "nonlinear": [nonlinear.DELTA_AIC, nonlinear.Z_CRIT],
    }


def calibration_fingerprint(ruleset: str = "verdict_rules_v1") -> str:
    h = hashlib.sha256()
    h.update((RULES_DIR / f"{ruleset}.yaml").read_bytes().replace(b"\r\n", b"\n"))
    h.update(json.dumps(thresholds(), sort_keys=True).encode())
    return h.hexdigest()[:16]
