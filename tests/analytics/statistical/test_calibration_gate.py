"""Stage 4 gate: the committed calibration report must match the current thresholds.

If this fails after you changed a threshold, a rule in verdict_rules_v1.yaml, or a
constant listed in validation/fingerprint.py: run ``make calibrate`` and commit the new
docs/validation/calibration_v1.{json,md}. Thresholds are not changed without evidence.
"""

import json
from pathlib import Path

import pytest

from earthtrend.analytics.validation.benchmarks import SYNTHETIC
from earthtrend.analytics.validation.fingerprint import calibration_fingerprint

REPORT = Path(__file__).parents[3] / "docs" / "validation" / "calibration_v1.json"


@pytest.fixture(scope="module")
def report() -> dict:  # type: ignore[type-arg]
    assert REPORT.exists(), "calibration report missing: run `make calibrate`"
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_report_matches_current_thresholds(report: dict) -> None:  # type: ignore[type-arg]
    assert report["fingerprint"] == calibration_fingerprint(), (
        "verdict thresholds or rules changed since the last calibration; "
        "run `make calibrate` and commit docs/validation/calibration_v1.*"
    )


def test_report_passed_all_acceptance_criteria(report: dict) -> None:  # type: ignore[type-arg]
    failed = [k for k, ok in report["acceptance"].items() if not ok]
    assert report["passed"] and not failed, failed


def test_report_used_enough_runs(report: dict) -> None:  # type: ignore[type-arg]
    assert report["runs"]["method"] >= 10_000  # PLAN_ANALYTICS 13.1
    assert report["runs"]["verdict"] >= 1000


def test_synthetic_benchmarks_still_hold() -> None:
    """Cheap re-check without re-running the Monte-Carlo."""
    for b in SYNTHETIC:
        pr = b.run()
        assert pr.verdict in b.expected, (b.name, pr.verdict)
        assert b.must_caveat <= set(pr.caveats), (b.name, pr.caveats)
