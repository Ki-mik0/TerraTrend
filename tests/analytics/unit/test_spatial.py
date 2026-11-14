import numpy as np
import pytest

from earthtrend.analytics import GridSummary, analyze_grid
from earthtrend.analytics.simulate.synthetic import generate_grid
from earthtrend.analytics.spatial.fdr import benjamini_hochberg
from earthtrend.analytics.spatial.split import split_region
from earthtrend.analytics.spatial.zones import cell_area_km2, find_zones, is_cyclic


def test_bh_matches_hand_calculation() -> None:
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, np.nan])
    sig, q, thr = benjamini_hochberg(p, alpha=0.05)
    # m = 8: thresholds 0.05*k/8 -> only the first two pass
    assert sig.tolist() == [True, True] + [False] * 7
    assert thr == 0.008
    assert np.isnan(q[-1])
    assert q[0] == pytest.approx(0.008)  # min(0.001*8, 0.008*4)
    assert np.all(np.diff(q[:8]) >= -1e-12)  # monotone in p order


def test_bh_edge_cases() -> None:
    sig, q, thr = benjamini_hochberg(np.full((2, 2), np.nan))
    assert not sig.any() and thr is None and np.isnan(q).all()
    sig, _, thr = benjamini_hochberg(np.array([0.5, 0.9]))
    assert not sig.any() and thr is None


def test_split_shares_and_flag() -> None:
    slope = np.array([[1.0, 1.0, -1.0, 0.1]])
    sig = np.array([[True, True, True, False]])
    w = np.ones((1, 4))
    r = split_region(sig, slope, w)
    assert (r.sig_pos, r.sig_neg, r.nonsig) == pytest.approx((0.5, 0.25, 0.25))
    assert r.split_flag
    r = split_region(sig, slope, np.array([[1.0, 1.0, 0.1, 1.0]]))
    assert not r.split_flag  # the cooling share is < 10%


def test_zone_filtering_and_label_map() -> None:
    lat = np.arange(-10.0, 10.0, 1.0)
    lon = np.arange(0.0, 20.0, 1.0)  # regional, not cyclic
    slope = np.zeros((20, 20))
    slope[2:8, 2:8] = 1.0  # big warming patch
    slope[12:16, 12:15] = -1.0  # cooling patch
    slope[18, 18] = 1.0  # single cell -> dropped
    sig = slope != 0
    zones, labels = find_zones(sig, slope, lat, lon, np.ones_like(sig))
    assert [z.sign for z in zones] == [1, -1]
    assert [z.id for z in zones] == [1, 2]
    assert zones[0].n_cells == 36 and zones[1].n_cells == 12
    assert labels[18, 18] == 0
    assert set(np.unique(labels)) == {0, 1, 2}
    assert zones[0].mean_slope_per_decade == pytest.approx(1.0)
    assert zones[0].bbox == (-8.0, 2.0, -3.0, 7.0)


def test_zones_wrap_around_the_antimeridian() -> None:
    lat = np.arange(-2.5, 3.0, 1.0)
    lon = np.arange(-179.5, 180.0, 1.0)
    assert is_cyclic(lon) and not is_cyclic(lon[:100])
    slope = np.zeros((lat.size, lon.size))
    slope[1:4, :3] = 1.0
    slope[1:4, -3:] = 1.0
    zones, _ = find_zones(slope > 0, slope, lat, lon, np.ones(slope.shape, bool))
    assert len(zones) == 1 and zones[0].n_cells == 18
    assert abs(zones[0].centroid[1]) == pytest.approx(180.0, abs=1e-6)


def test_cell_area_sums_to_earth_surface() -> None:
    lat, lon = np.arange(-89.5, 90, 1.0), np.arange(-179.5, 180, 1.0)
    assert cell_area_km2(lat, lon).sum() == pytest.approx(510.07e6, rel=1e-3)


def test_product_on_synthetic_field() -> None:
    lat, lon = np.arange(-29.5, 30, 1.0), np.arange(0.5, 60, 1.0)
    truth = np.zeros((lat.size, lon.size))
    truth[5:25, 5:25] = 1.0
    truth[35:55, 35:55] = -1.0
    dates, cube = generate_grid(slope_field=truth, n_years=40, phi=0.3, seed=4)
    prod = analyze_grid(cube, lat, lon, dates)
    s = prod.summary
    assert isinstance(s, GridSummary)
    assert {z.sign for z in s.zones} == {1, -1}
    assert s.split.split_flag
    false_disc = (prod.sig_fdr & (truth == 0)).sum() / max(int(prod.sig_fdr.sum()), 1)
    assert false_disc <= 0.15  # BH at q = 0.10, with Monte-Carlo slack
    labels_used = set(np.unique(prod.zone_id)) - {0}
    assert labels_used == {z.id for z in s.zones}
    assert GridSummary.model_validate_json(s.model_dump_json()) == s


def test_null_field_has_few_discoveries() -> None:
    lat, lon = np.arange(0.5, 40, 1.0), np.arange(0.5, 40, 1.0)
    dates, cube = generate_grid(slope_field=np.zeros((40, 40)), n_years=40, phi=0.3, seed=5)
    prod = analyze_grid(cube, lat, lon, dates)
    assert prod.sig_fdr.mean() < 0.01
