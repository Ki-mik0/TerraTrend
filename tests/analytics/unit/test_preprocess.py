from datetime import date

import numpy as np

from earthtrend.analytics.preprocess.aggregate import (
    annual_means,
    decimal_year,
    seasonal_means,
    split_dates,
)
from earthtrend.analytics.preprocess.anomalies import anomalies, standardized_anomalies
from earthtrend.analytics.preprocess.climatology import monthly_climatology
from earthtrend.analytics.preprocess.qc import qc_flags
from earthtrend.analytics.preprocess.stable_mask import stable_mask


def _months(start_year: int, n_years: int) -> tuple[np.ndarray, np.ndarray]:
    dates = [date(start_year + i // 12, i % 12 + 1, 1) for i in range(n_years * 12)]
    return split_dates(dates)


def test_decimal_year_is_mid_month() -> None:
    y, m = split_dates([date(2000, 1, 1), date(2000, 12, 1)])
    np.testing.assert_allclose(decimal_year(y, m), [2000 + 0.5 / 12, 2000 + 11.5 / 12])


def test_djf_is_tied_to_january_year() -> None:
    years, months = _months(1999, 3)  # 1999..2001
    values = years * 100.0 + months  # unique, readable values
    sy, sv = seasonal_means(values, years, months, "DJF")
    # DJF 1999 lacks Dec 1998 -> skipped; DJF 2000 = Dec 1999, Jan 2000, Feb 2000
    assert sy.tolist() == [2000, 2001]
    assert sv[0] == np.mean([199912, 200001, 200002])


def test_season_with_missing_month_is_invalid() -> None:
    years, months = _months(2000, 2)
    values = np.ones(years.size)
    values[(years == 2000) & (months == 7)] = np.nan
    sy, sv = seasonal_means(values, years, months, "JJA")
    assert np.isnan(sv[sy == 2000][0])
    assert sv[sy == 2001][0] == 1.0


def test_annual_mean_validity_rules() -> None:
    years, months = _months(2000, 3)
    values = np.ones(years.size)
    values[(years == 2000) & np.isin(months, [1, 5])] = np.nan  # 10 valid, different seasons
    values[(years == 2001) & np.isin(months, [6, 7])] = np.nan  # 2 missing in JJA
    values[(years == 2002) & np.isin(months, [1, 4, 7])] = np.nan  # only 9 valid
    _, av = annual_means(values, years, months)
    assert av[0] == 1.0
    assert np.isnan(av[1])
    assert np.isnan(av[2])


def test_anomalies_remove_the_seasonal_cycle() -> None:
    years, months = _months(2000, 5)
    values = 10.0 * months + 0.0
    mean, std = monthly_climatology(values, years, months)
    np.testing.assert_allclose(anomalies(values, months, mean), 0.0)
    assert np.all(np.isnan(standardized_anomalies(values, months, mean, std)))  # std = 0


def test_climatology_respects_baseline() -> None:
    years, months = _months(2000, 4)
    values = years.astype(float)
    mean, _ = monthly_climatology(values, years, months, baseline=(2002, 2003))
    np.testing.assert_allclose(mean, 2002.5)


def test_stable_mask_drops_cells_with_too_many_gaps() -> None:
    cube = np.ones((10, 1, 3))
    cube[:3, 0, 0] = np.nan  # 70% valid -> dropped
    cube[:1, 0, 1] = np.nan  # 90% valid -> kept
    assert stable_mask(cube).tolist() == [[False, True, True]]


def test_qc_flags() -> None:
    values = np.r_[np.full(30, np.nan), np.arange(70.0)]
    z = np.zeros(100)
    z[50] = 6.0
    codes = {f.code for f in qc_flags(values, z, 0.4, 70 / 12, 10)}
    assert codes == {"many_gaps", "low_stable_coverage", "short_record", "outliers"}
    assert "constant_series" in {f.code for f in qc_flags(np.ones(240), z, 1.0, 20, 10)}
