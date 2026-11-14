import pytest

from earthtrend.api.domain.story.model import (
    CORRELATION_CAVEAT,
    Paper,
    RelatedVariable,
    Story,
    StoryError,
    StoryFacts,
    draft_fits,
    facts_from_dict,
    facts_to_dict,
    keep_or_template,
    require_language,
    story_title,
    template_text,
)
from earthtrend.api.domain.shared.numbers import numbers_in

FULL = StoryFacts(
    variable_id="gldas_sm",
    region_id="ukraine_south",
    direction="decreasing",
    slope_decade=-0.03,
    pattern="drying",
    related=(RelatedVariable("merra2_t2m", "driver", 0, None, "Air temperature"), RelatedVariable("ndvi", "response", 2)),
    patterns=("drying",),
    alibi=(-0.03, -0.02),
    witnesses=(2, 3),
    papers=(Paper("Version 2 of a 1999 dataset", "https://doi.org/10.1/x", "10.1/x"),),
    caveats=("split_region",),
    versions={"ruleset": "verdict_rules_v1", "analytics": "a1"},
    variable_name="Soil moisture",
    region_name="Ukraine south",
)
BARE = StoryFacts("merra2_t2m", "sahel", "increasing", 0.25, "warming")


def test_allowed_numbers_are_computed_values_only() -> None:
    assert FULL.allowed_numbers() == {"-0.03", "-0.02", "2", "3", "0"}
    assert "1999" not in FULL.allowed_numbers()
    assert "0.03" not in FULL.allowed_numbers()


def test_template_uses_only_fact_numbers_in_both_languages() -> None:
    for language in ("uk", "en"):
        text = template_text(FULL, language)
        assert numbers_in(text) <= FULL.allowed_numbers()
        assert draft_fits(text, FULL)
    uk = template_text(FULL, "uk")
    assert "Soil moisture у регіоні Ukraine south спадає: -0.03" in uk
    assert "висихання" in uk and "Air temperature, ndvi (затримка 2 міс.)" in uk
    assert "-0.02 замість -0.03" in uk and "2 з 3" in uk and "Кореляція не є причинністю." in uk
    en = template_text(FULL, "en")
    assert "ndvi (lag 2 mo)" in en and "Correlation is not causation." in en


def test_template_for_bare_facts_and_unknown_codes() -> None:
    assert template_text(BARE, "en") == "merra2_t2m in sahel is increasing: 0.25 per decade. Pattern: warming."
    odd = StoryFacts("x", "y", "flat", 0.0, "mystery")
    assert template_text(odd, "uk") == "x у регіоні y без вираженого тренду: 0.0 за десятиліття. Патерн: mystery."


def test_correlation_caveat_follows_related_variables() -> None:
    assert FULL.all_caveats() == ("split_region", CORRELATION_CAVEAT)
    assert BARE.all_caveats() == ()
    already = StoryFacts("a", "b", "increasing", 1.0, "p", related=(RelatedVariable("c", "driver"),), caveats=(CORRELATION_CAVEAT,))
    assert already.all_caveats() == (CORRELATION_CAVEAT,)


def test_keep_or_template_rejects_any_number_outside_facts() -> None:
    assert keep_or_template("Нахил -0.03 за десятиліття.", FULL, "uk") == ("Нахил -0.03 за десятиліття.", True)
    text, kept = keep_or_template("Нахил 0.03 за десятиліття.", FULL, "uk")
    assert kept is False and text == template_text(FULL, "uk")
    assert keep_or_template("   ", BARE, "en") == (template_text(BARE, "en"), False)


def test_title_and_story_helpers() -> None:
    assert story_title(FULL, "uk") == "Soil moisture · Ukraine south: висихання"
    assert story_title(BARE, "en") == "merra2_t2m · sahel: warming"
    story = Story(id="s", language="uk", text=template_text(FULL, "uk"), facts=FULL)
    assert story.uses_only_fact_numbers() and story.caveats == FULL.all_caveats()


def test_cache_tag_is_stable_and_sorted() -> None:
    assert FULL.cache_tag() == "analytics=a1,ruleset=verdict_rules_v1"
    assert BARE.cache_tag() == "none"


def test_facts_round_trip_through_dict() -> None:
    assert facts_from_dict(facts_to_dict(FULL)) == FULL
    assert facts_from_dict(facts_to_dict(BARE)) == BARE


def test_language_and_error_messages() -> None:
    assert require_language("en") == "en"
    with pytest.raises(StoryError) as caught:
        require_language("fr")
    assert caught.value.code == "language_unknown"
    assert StoryError("data_not_ready", language="en").message == "The case facts are not computed yet"
    assert StoryError("custom_code").message == "custom_code"
    assert StoryError("case_not_found", "Своє").message == "Своє"
