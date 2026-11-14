# Calibration report — verdict_rules_v1

Fingerprint `0e3ad8ca7894a426` · analytics 0.1.0 · 2026-11-14T13:14:57+00:00 · runs: {'method': 10000, 'verdict': 1000, 'power': 1000}

**Overall: PASSED**

## False alarms on null scenarios (rate, 95% CI)

| Scenario | decision rule | OLS annual | OLS monthly | MK monthly | proven | strong |
|---|---|---|---|---|---|---|
| ar1_phi0.0 | 0.043 (0.039–0.047) | 0.043 (0.039–0.047) | 0.047 (0.043–0.052) | 0.048 (0.044–0.053) | 0.000 | 0.002 |
| ar1_phi0.3 | 0.050 (0.046–0.054) | 0.050 (0.046–0.054) | 0.055 (0.051–0.060) | 0.057 (0.052–0.061) | 0.000 | 0.001 |
| ar1_phi0.6 | 0.054 (0.050–0.059) | 0.054 (0.050–0.059) | 0.056 (0.052–0.061) | 0.057 (0.053–0.062) | 0.000 | 0.000 |
| ar1_phi0.8 | 0.057 (0.053–0.062) | 0.057 (0.053–0.062) | 0.052 (0.048–0.057) | 0.061 (0.057–0.066) | 0.000 | 0.005 |
| ar1_phi0.5_gaps15 | 0.038 (0.035–0.042) | 0.043 (0.040–0.048) | 0.045 (0.041–0.049) | 0.057 (0.052–0.061) | 0.000 | 0.004 |
| skewed_gamma_phi0.4 | 0.060 (0.056–0.065) | 0.047 (0.043–0.051) | 0.056 (0.051–0.060) | 0.060 (0.056–0.065) | 0.000 | 0.000 |
| iaaft_synthetic_long_memory | 0.051 (0.047–0.056) | 0.051 (0.047–0.056) | 0.111 (0.105–0.117) | 0.110 (0.103–0.116) | 0.000 | 0.005 |
| witness_shared0.8_phi0.5 | 0.053 (0.049–0.058) | 0.053 (0.049–0.058) | 0.055 (0.051–0.060) | 0.058 (0.054–0.063) | 0.002 | 0.000 |

The decision rule is what the verdict uses: OLS with AR(1) n_eff on annual means at alpha, confirmed by Mann-Kendall (AR(1) rank correction) with the same sign at p < MK_CONFIRM_P (skewed variables: MK and seasonal MK at alpha). The monthly tests over-reject under long memory and are reported only.

## Power

AR(1) φ = 0.5, 40 years; Weatherhead slope = 0.261 per decade (formula promises ~90% detection there).

| × Weatherhead slope | slope / decade | decision rule | OLS monthly | MK monthly |
|---|---|---|---|---|
| 0.25 | 0.065 | 0.122 | 0.143 | 0.147 |
| 0.5 | 0.130 | 0.353 | 0.393 | 0.404 |
| 0.75 | 0.196 | 0.668 | 0.698 | 0.698 |
| 1.0 | 0.261 | 0.881 | 0.909 | 0.909 |
| 1.25 | 0.326 | 0.971 | 0.982 | 0.979 |
| 1.5 | 0.391 | 0.994 | 0.999 | 0.999 |
| 2.0 | 0.522 | 1.000 | 1.000 | 1.000 |

## Verdicts on a real trend (2 × Weatherhead slope, with a witness)

proven: 0.862 · strong: 0.015 · likely: 0.123 · suspicious: 0.000 · no_evidence: 0.000 · inadmissible: 0.000

## Reference cases

| Case | verdict | expected | passed |
|---|---|---|---|
| steady_warming_with_witness | proven | proven | True |
| sensor_step_artifact | suspicious | likely, no_evidence, suspicious | True |
| trend_explained_by_enso | likely | likely, no_evidence, suspicious | True |
| short_record | inadmissible | inadmissible | True |
| poor_stable_coverage | suspicious | suspicious | True |
| witness_with_opposite_sign | likely | likely, suspicious | True |
| arctic_t2m (real) | — | fixture `giovanni_m2tmnxslv_t2m_arctic.csv` missing | not run |
| us_no2 (real) | — | fixture `giovanni_omno2_no2_usa.csv` missing | not run |
| stratosphere_t (real) | — | fixture `giovanni_airs_t_50hpa_global.csv` missing | not run |
| grace_india_tws (real) | — | fixture `giovanni_grace_tws_north_india.csv` missing | not run |

## Acceptance

- [x] ar1_phi0.0: decision FA in 3-7%
- [x] ar1_phi0.0: annual OLS FA in 3-7%
- [x] ar1_phi0.0: monthly OLS FA in 3-7%
- [x] ar1_phi0.0: monthly MK FA in 3-7%
- [x] ar1_phi0.0: false proven < 1%
- [x] ar1_phi0.0: false strong-or-better < 5%
- [x] ar1_phi0.3: decision FA in 3-7%
- [x] ar1_phi0.3: annual OLS FA in 3-7%
- [x] ar1_phi0.3: monthly OLS FA in 3-7%
- [x] ar1_phi0.3: monthly MK FA in 3-7%
- [x] ar1_phi0.3: false proven < 1%
- [x] ar1_phi0.3: false strong-or-better < 5%
- [x] ar1_phi0.6: decision FA in 3-7%
- [x] ar1_phi0.6: annual OLS FA in 3-7%
- [x] ar1_phi0.6: monthly OLS FA in 3-7%
- [x] ar1_phi0.6: monthly MK FA in 3-7%
- [x] ar1_phi0.6: false proven < 1%
- [x] ar1_phi0.6: false strong-or-better < 5%
- [x] ar1_phi0.8: decision FA in 3-7%
- [x] ar1_phi0.8: annual OLS FA in 3-7%
- [x] ar1_phi0.8: monthly OLS FA in 3-7%
- [x] ar1_phi0.8: monthly MK FA in 3-7%
- [x] ar1_phi0.8: false proven < 1%
- [x] ar1_phi0.8: false strong-or-better < 5%
- [x] ar1_phi0.5_gaps15: decision FA in 3-7%
- [x] ar1_phi0.5_gaps15: annual OLS FA in 3-7%
- [x] ar1_phi0.5_gaps15: monthly OLS FA in 3-7%
- [x] ar1_phi0.5_gaps15: monthly MK FA in 3-7%
- [x] ar1_phi0.5_gaps15: false proven < 1%
- [x] ar1_phi0.5_gaps15: false strong-or-better < 5%
- [x] skewed_gamma_phi0.4: decision FA in 3-7%
- [x] skewed_gamma_phi0.4: false proven < 1%
- [x] skewed_gamma_phi0.4: false strong-or-better < 5%
- [x] iaaft_synthetic_long_memory: decision FA in 3-7%
- [x] iaaft_synthetic_long_memory: annual OLS FA in 3-7%
- [x] iaaft_synthetic_long_memory: false proven < 1%
- [x] iaaft_synthetic_long_memory: false strong-or-better < 5%
- [x] witness_shared0.8_phi0.5: decision FA in 3-7%
- [x] witness_shared0.8_phi0.5: annual OLS FA in 3-7%
- [x] witness_shared0.8_phi0.5: false proven < 1%
- [x] witness_shared0.8_phi0.5: false strong-or-better < 5%
- [x] detection at Weatherhead slope in 80-97% (decision rule)
- [x] benchmark steady_warming_with_witness
- [x] benchmark sensor_step_artifact
- [x] benchmark trend_explained_by_enso
- [x] benchmark short_record
- [x] benchmark poor_stable_coverage
- [x] benchmark witness_with_opposite_sign
