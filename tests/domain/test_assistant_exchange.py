from datetime import UTC, datetime

import pytest

from earthtrend.api.domain.assistant.exchange import (
    MAX_STEPS,
    AssistantExchange,
    ExchangeError,
    ToolStep,
    accept_plan,
    answer_stays_inside_facts,
    check_step,
    collect_numbers,
    fallback_answer,
    message,
    numbers_in,
    split_chunks,
    teach_answer_ok,
)

CATALOG = {"gldas_sm", "merra2_t2m"}
REGIONS = {"ukraine_south"}


def _exchange(**overrides) -> AssistantExchange:
    values = {"question": "Чи сохне ґрунт?", "language": "uk", "role": "user", "owner_id": "u1"}
    values.update(overrides)
    return AssistantExchange(**values)


def test_unknown_variable_is_rejected() -> None:
    step = ToolStep("analyze_case", "перевірити", {"variable_id": "not_in_catalog"})
    with pytest.raises(ExchangeError) as caught:
        check_step(step, CATALOG)
    assert caught.value.code == "variable_not_in_catalog"
    assert "not_in_catalog" in caught.value.message


def test_unknown_region_is_rejected_only_when_regions_are_known() -> None:
    step = ToolStep("analyze_case", "r", {"variable_id": "gldas_sm", "region_id": "mars"})
    with pytest.raises(ExchangeError) as caught:
        check_step(step, CATALOG, REGIONS)
    assert caught.value.code == "region_not_in_catalog"
    check_step(step, CATALOG)


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ExchangeError) as caught:
        check_step(ToolStep("delete_everything", "", {}), CATALOG)
    assert caught.value.code == "tool_not_allowed"


def test_invented_number_in_plan_is_rejected_even_nested() -> None:
    for payload in (
        {"variable_id": "gldas_sm", "p_mk": 0.01},
        {"case_ids": [{"slope": 1.0}]},
        {"filters": {"snr": 3}},
    ):
        with pytest.raises(ExchangeError) as caught:
            check_step(ToolStep("compare_cases", "x", payload), CATALOG)
        assert caught.value.code == "model_invented_number"


def test_new_spec_tools_are_allowed() -> None:
    for tool in ("get_profile", "get_urban", "compare_cases"):
        check_step(ToolStep(tool, "", {}), CATALOG)


def test_accept_plan_keeps_valid_steps_warns_in_language_and_caps_length() -> None:
    exchange = _exchange(language="en")
    proposed = [
        ToolStep("analyze_case", "", {"variable_id": "nope"}),
        ToolStep("analyze_case", "", {"variable_id": "gldas_sm", "region_id": "mars"}),
        ToolStep("hack", "", {}),
        ToolStep("get_radar", "", {"p_value": 0.1}),
    ] + [ToolStep("search_variables", "", {"q": str(index)}) for index in range(MAX_STEPS + 2)]
    accepted = accept_plan(exchange, proposed, CATALOG, REGIONS)
    assert len(accepted) == MAX_STEPS
    assert exchange.warnings == [
        "Variable nope is not in the catalog",
        "Region mars is not in the catalog",
        "Tool hack is not allowed",
        "A plan step contains a number the model made up",
        f"The plan is longer than {MAX_STEPS} steps, the rest was dropped",
    ]


def test_answer_number_outside_facts_is_rejected() -> None:
    assert answer_stays_inside_facts("нахил 0.99", {"0.42", "0.002"}) is False
    assert answer_stays_inside_facts("Висновок без чисел.", {"0.42"}) is True


def test_sign_and_comma_decimal_are_kept() -> None:
    assert numbers_in("нахил -0.42 і 0,5 та 3.10") == {"-0.42", "0.5", "3.1"}
    assert answer_stays_inside_facts("-0.42", {"0.42"}) is False
    assert numbers_in("-0") == {"0"}


def test_ids_with_digits_are_not_numbers() -> None:
    assert numbers_in("case_mem_1 і merra2_t2m, v1.2") == set()


def test_collect_numbers_walks_values() -> None:
    facts = [{"a": 0.42, "b": True, "c": None, "d": ["7", (3,)], "e": {}, "f": [], "g": object()}]
    assert collect_numbers(facts) == {"0.42", "7", "3"}
    assert collect_numbers({1, 2}) == {"1", "2"}


def test_teach_answer_must_be_a_question_without_verdict() -> None:
    assert teach_answer_ok("Що могло б пояснити цей тренд?") is True
    assert teach_answer_ok("Тренд доведено.") is False
    assert teach_answer_ok("Чи вирок strong?") is False


def test_exchange_validates_mode_and_language() -> None:
    with pytest.raises(ExchangeError) as caught:
        _exchange(mode="chat")
    assert caught.value.code == "mode_unknown"
    with pytest.raises(ExchangeError) as caught:
        _exchange(language="fr")
    assert caught.value.code == "language_unknown"


def test_exchange_lifecycle_and_note_roles() -> None:
    exchange = _exchange(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    exchange.add_case("case_1")
    exchange.add_case("case_1")
    exchange.cite({"case_id": "case_1"})
    exchange.cite({"case_id": "case_1"})
    assert exchange.case_ids == ["case_1"]
    assert exchange.citations == [{"case_id": "case_1"}]
    assert exchange.writes_note is True
    assert _exchange(role="guest").writes_note is False
    exchange.finish("готово")
    assert (exchange.status, exchange.answer) == ("answered", "готово")
    exchange.fail()
    assert exchange.status == "failed"


def test_fallback_answer_per_mode_and_language() -> None:
    assert fallback_answer(_exchange()) == "Недостатньо доказів у каталозі."
    with_case = _exchange(language="en")
    with_case.add_case("case_7")
    assert fallback_answer(with_case) == "The conclusion uses only the facts of case case_7."
    assert fallback_answer(_exchange(mode="teach")).endswith("?")


def test_message_defaults_to_ukrainian_for_unknown_language() -> None:
    assert message("rate_limited", "de") == message("rate_limited", "uk")


def test_split_chunks_keeps_sentences() -> None:
    assert split_chunks("Один. Два! Три") == ["Один. ", "Два! ", "Три"]
    assert split_chunks("") == [""]
