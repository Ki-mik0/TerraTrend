"""Default parameters, QC thresholds and versions of the analytics core.

Thresholds follow docs/PLAN_ANALYTICS.md section 4.2. Changing any of them
changes numerical behaviour and must be reflected in docs/methods/.
"""

from typing import Final

ANALYTICS_VERSION: Final = "0.1.0"
VERDICT_RULESET: Final = "verdict_rules_v0"  # Stage 1 slice: statistics + quality only

ALPHA: Final = 0.05

# Stable mask and regional reduction (section 4.4)
STABLE_MASK_MIN_VALID: Final = 0.80  # cell valid in >= 80% of months
MONTH_MIN_COVERAGE: Final = 0.70  # month is a gap below 70% of the stable-mask area

# QC (section 4.2)
LOW_STABLE_FRACTION: Final = 0.50  # flag low_stable_coverage
MAX_GAP_SHARE: Final = 0.20  # flag many_gaps
DEFAULT_MIN_YEARS: Final = 10  # below -> inadmissible
OUTLIER_Z: Final = 5.0  # flag outliers (values are kept)

# Aggregation (section 4.1)
DAILY_MIN_VALID: Final = 0.80  # month valid with >= 80% of days
ANNUAL_MIN_MONTHS: Final = 10

# OLS with AR(1) correction (section 5.1)
N_EFF_MIN: Final = 3.0
N_EFF_UNRELIABLE: Final = 8.0

# Statistics decision (Stage 4 calibration, docs/validation/calibration_v1.md):
# primary test = OLS + AR(1) n_eff on annual means (monthly AR(1) corrections over-reject
# under long memory); Mann-Kendall must confirm with the same sign at p < MK_CONFIRM_P.
# Requiring MK at alpha as well pushed false alarms below 3% (lost power).
MK_CONFIRM_P: Final = 0.20

# Magnitude (section 6.1): SNR = |slope_per_decade| / sigma_anom
SNR_MODERATE: Final = 0.2
SNR_STRONG: Final = 0.5

# strength weights from verdict_rules_v1; in the slice only these items exist,
# so the maximum reachable strength is their sum (45).
STRENGTH_WEIGHTS: Final = {"statistics": 30, "quality": 10, "magnitude": 5}

SEASON_MONTHS: Final = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}
# Month used to date a seasonal value on charts.
SEASON_LABEL_MONTH: Final = {"DJF": 1, "MAM": 4, "JJA": 7, "SON": 10}

# Spatial analysis (section 8)
FDR_ALPHA: Final = 0.10  # Benjamini-Hochberg over valid cells (Wilks 2016)
SPLIT_MIN_SHARE: Final = 0.10  # split_flag if both significant shares >= 10%
ZONE_MIN_CELLS: Final = 3
ZONE_MIN_AREA_SHARE: Final = 0.005  # of the analysed area
EARTH_RADIUS_KM: Final = 6371.0
