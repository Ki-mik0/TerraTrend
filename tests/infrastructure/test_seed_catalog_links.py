"""Built-in radar cards and demo cases must point at catalog variables and regions.

The frontend turns a radar card or a demo into an investigation with the same variable and region;
an id outside the catalog would open a case that fails with `region_not_found`.
"""

from earthtrend.api.infrastructure.catalog.lessons import seed_demos
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.radar.seed import seed_product


def _catalog_ids() -> tuple[set[str], set[str]]:
    catalog = seed_catalog()
    return set(catalog.passports), set(catalog.regions)


def test_radar_seed_points_at_catalog() -> None:
    variables, regions = _catalog_ids()
    product = seed_product()
    assert {item.variable_id for item in product.items} <= variables
    assert {item.region_id for item in product.items} <= regions
    for cluster in product.clusters:
        assert set(cluster.signs) <= variables
        assert set(cluster.region_ids) <= regions


def test_demo_cases_point_at_catalog() -> None:
    variables, regions = _catalog_ids()
    for demo in seed_demos():
        assert demo.variable_id in variables, demo.id
        assert demo.region_id in regions, demo.id
