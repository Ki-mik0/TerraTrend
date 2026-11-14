import pytest

from earthtrend.api.domain.education.model import (
    Assignment,
    DemoProgress,
    EducationError,
    LabParams,
    LabRun,
    Quiz,
    badge_key,
    badges_for_case,
    require_language,
)


def _case_badges(verdict: str, *, split: bool = False, raw: float = -0.04, adjusted: float = -0.04, year=None):
    return badges_for_case(
        verdict_code=verdict, split_flag=split, b_raw=raw, b_adjusted=adjusted, influential_year=year
    )


@pytest.mark.parametrize("verdict", ["proven", "strong", "likely"])
def test_significant_verdicts_earn_first_trend(verdict: str) -> None:
    assert _case_badges(verdict) == ["first_significant_trend"]


def test_split_region_earns_found_split() -> None:
    assert _case_badges("strong", split=True) == ["first_significant_trend", "found_split"]
    assert _case_badges("inadmissible", split=True) == ["found_split"]


@pytest.mark.parametrize(
    ("verdict", "raw", "adjusted", "year", "expected"),
    [
        ("no_evidence", -0.04, -0.01, None, ["refuted_false_trend"]),
        ("suspicious", -0.04, -0.03, 2010, ["refuted_false_trend"]),
        ("suspicious", -0.04, -0.03, None, []),
        ("no_evidence", 0.0, 0.0, None, []),
        ("likely", -0.04, -0.01, 2010, ["first_significant_trend"]),
    ],
)
def test_refuted_false_trend_needs_alibi_or_jackknife(verdict, raw, adjusted, year, expected) -> None:
    assert _case_badges(verdict, raw=raw, adjusted=adjusted, year=year) == expected


def test_badge_key_dedupes_case_badges_per_user() -> None:
    assert badge_key("u1", "found_split", "case_1") == badge_key("u1", "found_split", "case_2")
    assert badge_key("u1", "demo", "demo_a") != badge_key("u1", "demo", "demo_b")
    with pytest.raises(EducationError):
        badge_key("u1", "made_up", "x")


def test_assignment_join_and_case_rules() -> None:
    assignment = Assignment(id="a1", teacher_id="t1", title="T", student_ids=("s1",), case_ids=("c1",))
    assert assignment.join("s2", "user") is True
    assert assignment.join("s2", "user") is False
    assert assignment.join("t1", "teacher") is False
    with pytest.raises(EducationError):
        assignment.join("g1", "guest")
    assert assignment.student_ids == ("s1", "s2")
    assert assignment.accepts_case("c1", "t1", "s1") is True
    assert assignment.accepts_case("c2", "s1", "s1") is True
    assert assignment.accepts_case("c2", "s9", "s1") is False
    assert assignment.owned_by("t1", "teacher") and assignment.owned_by("x", "admin")
    assert not assignment.owned_by("s1", "user")


def test_demo_progress_finishes_once() -> None:
    progress = DemoProgress(user_id="u1", demo_id="d1")
    assert progress.complete_step(1, 2) is False
    assert progress.complete_step(2, 2) is True
    assert progress.complete_step(2, 2) is False
    assert progress.finished(2)
    assert not DemoProgress(user_id="u1", demo_id="d0").finished(0)
    with pytest.raises(EducationError):
        progress.complete_step(3, 2)


def test_quiz_check_and_language() -> None:
    quiz = Quiz(id="q", language="uk", question="?", options=("a", "b"), answer=1, explanation="")
    assert quiz.check(1) and not quiz.check(0)
    with pytest.raises(EducationError):
        quiz.check(2)
    assert require_language("en") == "en"
    with pytest.raises(EducationError):
        require_language("fr")


@pytest.mark.parametrize(
    "params",
    [
        {"noise": -1, "years": 30, "autocorrelation": 0.1},
        {"noise": 11, "years": 30, "autocorrelation": 0.1},
        {"noise": 1, "years": 4, "autocorrelation": 0.1},
        {"noise": 1, "years": 30, "autocorrelation": 0.95},
    ],
)
def test_lab_params_bounds(params) -> None:
    with pytest.raises(EducationError):
        LabParams(**params)


def test_lab_run_ready_flag() -> None:
    params = LabParams(noise=1, years=30, autocorrelation=0.2)
    assert LabRun(params=params, status="ready").ready
    assert not LabRun(params=params, status="not_ready").ready
