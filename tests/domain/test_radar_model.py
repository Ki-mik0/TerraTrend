import pytest

from earthtrend.api.domain.radar.model import (
    RadarError,
    RadarItem,
    RadarProduct,
    TypologyCluster,
    require_page,
    require_season,
)


def _item(**overrides) -> RadarItem:
    base = dict(
        id="r1",
        feed="strongest",
        variable_id="gldas_sm",
        region_id="ukraine_south",
        direction="decreasing",
        slope_decade=-0.03,
        pct_decade=-1.8,
        snr=0.5,
        p_mk=0.01,
        p_ols=0.02,
        q_fdr=0.03,
        split_flag=False,
        score=0.8,
        verdict_level="strong",
        case_id="c1",
    )
    return RadarItem(**{**base, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"feed": "invented"},
        {"season": "summer"},
        {"direction": "up"},
        {"verdict_level": "maybe"},
        {"novelty": "fresh"},
        {"q_fdr": 1.5},
        {"p_mk": -0.1},
    ],
)
def test_item_rejects_invalid_fields(overrides) -> None:
    with pytest.raises(RadarError):
        _item(**overrides)


@pytest.mark.parametrize(
    ("feed", "fields", "ok"),
    [
        ("strongest", {"verdict_level": "proven"}, True),
        ("strongest", {"verdict_level": "likely"}, False),
        ("almost", {"verdict_level": "suspicious", "years_to_detect": 8.0}, True),
        ("almost", {"verdict_level": "suspicious", "years_to_detect": 12.0}, False),
        ("almost", {"verdict_level": "suspicious"}, False),
        ("stable", {"verdict_level": "no_evidence", "direction": "none"}, True),
        ("stable", {"verdict_level": "likely"}, False),
        ("opposite", {"verdict_level": "inadmissible", "split_flag": True}, True),
        ("opposite", {"verdict_level": "suspicious"}, False),
        ("ai_flagged", {"verdict_level": "suspicious"}, True),
        ("ai_flagged", {"verdict_level": "no_evidence"}, False),
        ("accelerating", {"verdict_level": "likely"}, True),
        ("breakpoints", {"verdict_level": "suspicious"}, False),
    ],
)
def test_feed_rules_are_checked_not_recomputed(feed, fields, ok) -> None:
    if ok:
        assert _item(feed=feed, **fields).feed == feed
    else:
        with pytest.raises(RadarError):
            _item(feed=feed, **fields)


def test_page_sorts_by_score_filters_and_counts() -> None:
    items = (
        _item(id="b", score=0.5),
        _item(id="a", score=0.5),
        _item(id="c", score=0.9, season="JJA"),
        _item(id="d", score=0.7, region_id="sahel"),
    )
    product = RadarProduct(version="v1", generated_at="t", items=items)
    first = product.page(feed="strongest", page=1, page_size=2)
    assert [item.id for item in first.items] == ["c", "d"]
    assert first.total == 4 and first.version == "v1"
    second = product.page(feed="strongest", page=2, page_size=2)
    assert [item.id for item in second.items] == ["a", "b"]
    assert [item.id for item in product.page(feed="strongest", season="JJA").items] == ["c"]
    assert [item.id for item in product.page(feed="strongest", region_id="sahel").items] == ["d"]
    assert product.page(feed="strongest", variable_id="other").total == 0
    assert product.page(feed="stable").items == []


@pytest.mark.parametrize(("page", "size"), [(0, 20), (1, 0), (1, 101), (-1, 5)])
def test_page_bounds(page, size) -> None:
    with pytest.raises(RadarError):
        require_page(page, size)


def test_season_check() -> None:
    assert require_season(None) is None
    assert require_season("DJF") == "DJF"
    with pytest.raises(RadarError):
        require_season("winter")


def test_typology_filters_by_variables_and_season() -> None:
    hot_dry = TypologyCluster(id="k1", pattern="warmer_drier", signs={"t2m": 1, "sm": -1}, season="JJA")
    greener = TypologyCluster(id="k2", pattern="greener", signs={"ndvi": 1})
    product = RadarProduct(version="v1", generated_at="t", clusters=(hot_dry, greener))
    assert [item.id for item in product.typology()] == ["k1", "k2"]
    assert [item.id for item in product.typology(variables=["t2m", "sm"])] == ["k1"]
    assert [item.id for item in product.typology(variables=["t2m", "ndvi"])] == []
    assert [item.id for item in product.typology(season="annual")] == ["k2"]
    with pytest.raises(RadarError):
        TypologyCluster(id="bad", pattern="x", signs={"t2m": 2})
    with pytest.raises(RadarError):
        TypologyCluster(id="bad", pattern="x", signs={})


def test_case_url() -> None:
    assert _item(case_id="case_7").case_url == "/api/v1/cases/case_7"
