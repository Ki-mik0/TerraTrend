"""Story texts from an external LLM with number check and template fallback (PLAN 10.4,
11.5; team decision: M4 is not trained, the backend connects an LLM)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from earthtrend.analytics.ml.storywriter import (
    PROMPT_VERSION,
    build_messages,
    check_numbers,
    repair_message,
    template_story,
    write_story,
)
from earthtrend.analytics.ml.storywriter_eval import evaluate_llm, synthetic_facts


@pytest.fixture(scope="module")
def cases() -> list:
    return synthetic_facts(6, seed=1)


def test_template_passes_number_check_for_all_cases(cases: list) -> None:
    for c in cases:
        for lang in ("uk", "en"):
            text = template_story(c.facts, lang)
            chk = check_numbers(text, c.facts, lang)
            assert chk.passed, (c.case_id, lang, chk)


def test_invented_number_and_missing_caveat_are_caught(cases: list) -> None:
    f = next(c.facts for c in cases if c.facts.caveats)
    chk = check_numbers("Температура зросла на 123.45 K за десятиліття.", f, "uk")
    assert not chk.passed
    assert "123.45" in chk.unmatched
    assert chk.missing_caveats == list(f.caveats)


def test_messages_carry_rules_facts_and_caveats(cases: list) -> None:
    f = cases[0].facts
    system, user = build_messages(f, "en")
    assert "Use ONLY numbers" in system
    assert user.startswith(f"[{PROMPT_VERSION}]")
    payload = json.loads(user.split("\n", 1)[1])
    assert payload["numbers"] == dict(sorted(f.numbers.items()))
    assert [c["code"] for c in payload["caveats"]] == list(f.caveats)
    assert "Використовуй ЛИШЕ числа" in build_messages(f, "uk")[0]


def test_no_llm_uses_template(cases: list) -> None:
    out = write_story(cases[0].facts, "uk")
    assert out.method == "template" and out.fallback_reason == "no_llm"
    assert out.attempts == 0 and out.check.passed


def test_good_llm_text_is_used(cases: list) -> None:
    f = cases[0].facts
    good = template_story(f, "en")
    out = write_story(f, "en", llm=lambda s, u: good, llm_label="claude")
    assert out.method == "llm" and out.model_version == "claude"
    assert out.attempts == 1 and out.text == good


def test_one_repair_then_success(cases: list) -> None:
    f = cases[0].facts
    good = template_story(f, "uk")
    seen: list[str] = []

    def llm(system: str, user: str) -> str:
        seen.append(user)
        return "Зросло на 987.6." if len(seen) == 1 else good

    out = write_story(f, "uk", llm=llm)
    assert out.method == "llm" and out.attempts == 2
    assert "987.6" in seen[1]  # the repair message names the invented number


def test_persistent_bad_llm_falls_back(cases: list) -> None:
    out = write_story(cases[0].facts, "en", llm=lambda s, u: "It rose by 987.6 units.")
    assert out.method == "template"
    assert out.fallback_reason == "failed_number_check"
    assert out.attempts == 2 and out.check.passed


def test_llm_error_falls_back(cases: list) -> None:
    def boom(system: str, user: str) -> str:
        raise TimeoutError("api down")

    out = write_story(cases[0].facts, "uk", llm=boom)
    assert out.method == "template" and out.fallback_reason == "llm_error"


def test_repair_message_lists_problems(cases: list) -> None:
    f = next(c.facts for c in cases if c.facts.caveats)
    chk = check_numbers("123.45", f, "en")
    msg = repair_message("123.45", chk, "en")
    assert "123.45" in msg and "Missing caveats" in msg


def test_unsupported_language(cases: list) -> None:
    with pytest.raises(ValueError):
        write_story(cases[0].facts, "de")  # type: ignore[arg-type]


def test_evaluate_llm_gates() -> None:
    facts = synthetic_facts(3, seed=2)
    answers = {
        build_messages(c.facts, lang)[1]: template_story(c.facts, lang)
        for c in facts
        for lang in ("uk", "en")
    }
    good = evaluate_llm(lambda s, u: answers[u], n_cases=3, seed=2)
    assert good["status"] == "pass" and good["first_try_pass_rate"] == 1.0
    assert good["gates"]["blind_human_comparison"] == "not_evaluated"
    bad = evaluate_llm(lambda s, u: "Rose by 987.6.", n_cases=3, seed=2)
    assert bad["status"] == "fail" and bad["llm_text_rate"] == 0.0
    assert bad["caveats_present_rate"] == 1.0  # the template fallback keeps every caveat


def test_core_does_not_import_ml_frameworks() -> None:
    code = (
        "import sys, earthtrend.analytics.ml.storywriter;"
        "print(any(m in sys.modules for m in ('torch', 'transformers', 'peft')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONPATH": "src"},
    )
    assert out.stdout.strip() == "False"
