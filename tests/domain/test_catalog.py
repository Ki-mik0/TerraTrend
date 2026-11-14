"""Catalog rules: themes, geometry, and a CMR registration that does not call NASA."""

from __future__ import annotations

import pytest

from earthtrend.api.domain.catalog.model import CatalogError, VariablePassport, register_region
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.catalog.pool import ProcessCmr, prepare_cmr
from earthtrend.api.infrastructure.shared.cache import MemoryCache


@pytest.mark.asyncio
async def test_theme_filter_keeps_only_that_group() -> None:
    catalog = seed_catalog()
    snow = await catalog.list_variables(theme="cryosphere")
    assert {item.id for item in snow} == {"modis_snow", "gldas_swe", "nsidc_ice"}
    assert all(item.domain == "snow" for item in snow)


@pytest.mark.asyncio
async def test_unknown_variable_is_rejected() -> None:
    catalog = seed_catalog()
    with pytest.raises(CatalogError) as caught:
        await catalog.get_variable("missing")
    assert caught.value.code == "variable_not_found"


def test_bad_polygon_and_point_radius() -> None:
    with pytest.raises(CatalogError) as caught:
        register_region(region_id="bad", name="Bad", geometry={"type": "Polygon", "coordinates": [[[1, 2]]]})
    assert caught.value.code == "region_invalid"
    with pytest.raises(CatalogError):
        register_region(region_id="empty", name="Empty")
    region = register_region(region_id="well", name="Well", point=(30.5, 47.0), radius_km=10)
    assert region.bbox[0] < 30.5 < region.bbox[2]
    assert region.bbox[1] < 47.0 < region.bbox[3]
    assert region.geometry["type"] == "Point"
    assert region.area_km2 == round(3.141592653589793 * 100, 1)


def test_unknown_level_is_rejected() -> None:
    with pytest.raises(CatalogError) as caught:
        VariablePassport(id="x", name="x", name_uk="x", kid_description="x", units="1", level="nope")
    assert caught.value.code == "level_invalid"


@pytest.mark.asyncio
async def test_reload_changes_the_cache_key_and_drops_custom_regions() -> None:
    catalog = seed_catalog(cache=MemoryCache())
    first = await catalog.list_variables(theme="cryosphere")
    catalog.passports["modis_snow"] = VariablePassport(
        id="modis_snow",
        name="Changed",
        name_uk="Змінено",
        kid_description="x",
        units="1",
        theme="cryosphere",
        domain="snow",
    )
    cached = await catalog.list_variables(theme="cryosphere")
    assert all(item.name != "Changed" for item in cached)
    assert {item.id for item in cached} == {item.id for item in first}
    created = await catalog.register_custom(name="Field", bbox=(30.0, 46.0, 32.0, 48.0), geometry=None)
    await catalog.search_cmr("SMAP L-band 2015")
    await catalog.reload(role="admin")
    with pytest.raises(CatalogError):
        await catalog.get_region(created.id)
    kept = await catalog.get_variable("smap_l_band_2015")
    assert kept.level == "cmr"
    fresh = await catalog.list_variables(theme="cryosphere")
    assert any(item.name == "Snow cover" for item in fresh)


@pytest.mark.asyncio
async def test_repeated_cmr_query_keeps_one_passport() -> None:
    catalog = seed_catalog()
    ready = await catalog.search_cmr("gldas_sm")
    assert ready.job_id is None and ready.passport_id == "gldas_sm"
    first = await catalog.search_cmr("SMAP L-band 2015")
    second = await catalog.search_cmr("SMAP L-band 2015")
    assert first.job_id == "cmr_1"
    assert second.job_id is None
    assert second.passport_id == first.passport_id
    assert sum(item.level == "cmr" for item in catalog.passports.values()) == 1


@pytest.mark.asyncio
async def test_cmr_worker_slug_matches_the_inline_slug() -> None:
    assert prepare_cmr("SMAP L-band 2015") == "smap_l_band_2015"
    assert await ProcessCmr().run("SMAP L-band 2015") == "smap_l_band_2015"
