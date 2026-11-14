import pytest

from earthtrend.api.domain.cases.model import Case, CaseError, CaseSpec, Verdict, assert_storable


def _spec() -> CaseSpec:
    return CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12")


def test_completed_case_without_verdict_is_not_stored() -> None:
    case = Case(id="c1", owner_id="u1", role="user", spec=_spec())
    case.status = "completed"
    with pytest.raises(CaseError) as caught:
        assert_storable(case)
    assert caught.value.code == "verdict_required"


def test_verdict_code_must_belong_to_ruleset() -> None:
    with pytest.raises(CaseError):
        Verdict(code="significant", ruleset="verdict_rules_v1", direction="up", summary="")


def test_assignment_case_is_deleted_only_by_admin() -> None:
    case = Case(id="c1", owner_id="u1", role="user", spec=_spec(), assignment_linked=True)
    with pytest.raises(CaseError) as caught:
        case.assert_deletable("u1", "user")
    assert caught.value.code == "assignment_locked"
    case.assert_deletable("admin", "admin")


def test_guest_case_is_hidden_from_the_list() -> None:
    case = Case(id="c1", owner_id="guest-1", role="guest", spec=_spec(), ephemeral=True)
    assert case.visible_to("guest-1", "guest") is True
    assert case.listed_for("guest-1", "guest") is False
    assert case.visible_to("other", "user") is False


def test_short_period_and_compare_count_are_rejected() -> None:
    from earthtrend.api.domain.cases.model import require_compare_count, require_period

    require_period("2000-01", "2002-01")
    with pytest.raises(CaseError) as caught:
        require_period("2000-01", "2001-12")
    assert caught.value.code == "period_too_short"
    require_compare_count(2)
    require_compare_count(4)
    with pytest.raises(CaseError) as caught:
        require_compare_count(1)
    assert caught.value.code == "compare_invalid"
    with pytest.raises(CaseError) as caught:
        require_compare_count(5)
    assert caught.value.code == "compare_invalid"
