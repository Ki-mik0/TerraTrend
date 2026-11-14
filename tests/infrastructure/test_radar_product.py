import json
from dataclasses import asdict
from pathlib import Path

import pytest

from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.domain.radar.model import RadarError
from earthtrend.api.infrastructure.radar import wiring
from earthtrend.api.infrastructure.radar.files import FileRadarProduct
from earthtrend.api.infrastructure.radar.memory import MemoryRadarProduct, seed_radar
from earthtrend.api.infrastructure.radar.seed import SEED_VERSION, seed_product
from earthtrend.api.infrastructure.shared.cache import MemoryCache, RedisCache


def _write_product(root: Path, version: str, *, extra_rows: list[dict] | None = None) -> None:
    seed = seed_product()
    rows = [asdict(item) for item in seed.items[:3]] + (extra_rows or [])
    clusters = [{**asdict(item), "region_ids": list(item.region_ids)} for item in seed.clusters]
    clusters.append({"id": "broken", "pattern": "x", "signs": {}})
    payload = {"version": version, "generated_at": "2026-12-01T00:00:00Z", "items": rows, "clusters": clusters}
    (root / f"{version}.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / "latest.json").write_text(json.dumps({"version": version}), encoding="utf-8")


async def test_file_product_falls_back_to_seed_then_reads_new_versions(tmp_path: Path) -> None:
    product = FileRadarProduct(tmp_path)
    assert await product.latest_version() == SEED_VERSION
    assert (await product.load(SEED_VERSION)).version == SEED_VERSION

    bad_row = {**asdict(seed_product().items[0]), "id": "bad", "verdict_level": "likely"}
    _write_product(tmp_path, "2026-12", extra_rows=[bad_row, {"id": "half"}])
    assert await product.latest_version() == "2026-12"
    loaded = await product.load("2026-12")
    assert len(loaded.items) == 3 and "bad" not in {item.id for item in loaded.items}
    assert len(loaded.clusters) == 3
    assert await product.load("2026-12") is loaded

    _write_product(tmp_path, "2027-01")
    assert (await product.load(await product.latest_version())).version == "2027-01"


async def test_file_product_rejects_unsafe_versions(tmp_path: Path) -> None:
    product = FileRadarProduct(tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({"version": "../etc"}), encoding="utf-8")
    with pytest.raises(RadarError):
        await product.latest_version()
    with pytest.raises(RadarError):
        await product.load("../../secret")


async def test_service_caches_pages_and_picks_up_a_new_version() -> None:
    now = [0.0]
    cache = MemoryCache(clock=lambda: now[0])
    product = MemoryRadarProduct()
    service = RadarService(product=product, cache=cache)

    first = await service.page(feed="strongest", page_size=2)
    again = await service.page(feed="strongest", page_size=2)
    assert first == again and product.loads == 1
    assert first.total == 4 and [item.score for item in first.items] == sorted(
        (item.score for item in first.items), reverse=True
    )
    version, clusters = await service.typology(variables=["merra2_t2m"])
    assert version == SEED_VERSION and {item.id for item in clusters} == {"typ_warmer_drier_browner", "typ_warmer_greener"}
    assert (await service.typology(variables=["merra2_t2m"]))[1] == clusters
    assert product.loads == 2

    product.product = seed_product().__class__(version="v2", generated_at="later", items=(), clusters=())
    # The version pointer is cached for a minute, so the cached seed page is still served.
    assert (await service.page(feed="strongest", page_size=2)).version == SEED_VERSION
    now[0] = 61
    newer = await service.page(feed="strongest")
    assert newer.version == "v2" and newer.total == 0


async def test_feed_keeps_the_assistant_contract() -> None:
    items = await seed_radar().feed(feed="strongest")
    assert items and all(item.feed == "strongest" for item in items)


def test_radar_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.delenv("REDIS_URL", raising=False)
    service = wiring.radar_from_env()
    assert isinstance(service._cache.inner, MemoryCache)
    assert service._product.root == tmp_path / "radar"
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert isinstance(wiring.radar_from_env()._cache.inner, RedisCache)
