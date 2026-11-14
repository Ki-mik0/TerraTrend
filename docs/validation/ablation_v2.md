# Verdict ablation - v1 against v2 candidates with `ai_expert`

Oracle: `simulated(accuracy=0.85)` · 200 cases per scenario

**Decision: NOT_EVALUATED** → `verdict_rules_v1` stays (simulated_oracle_planning_only)

False = `proven`/`strong` on a case without a real change (or with the wrong sign).
Power = `proven`/`strong` with the right sign on a real change.

| Ruleset | false | false on negatives | power | removed / added false | hits lost | p (false) | p (power) | accepted |
|---|---|---|---|---|---|---|---|---|
| v1 | 10.6% | 19.1% | 54.2% | – | – | – | – | – |
| v2 veto | 1.3% | 2.3% | 50.2% | 169 / 1 | 33 | 2.3e-49 | 4.1e-09 | no (fewer_false_significant, adds_false_verdicts, power_drop_too_large, power_loss_significant) |
| v2 strict | 1.3% | 2.3% | 50.2% | 169 / 1 | 33 | 2.3e-49 | 4.1e-09 | no (fewer_false_significant, adds_false_verdicts, power_drop_too_large, power_loss_significant) |

## By scenario

| Scenario | metric | v1 | veto | strict | AI disagrees |
|---|---|---|---|---|---|
| accelerating | power | 35.0% | 30.0% | 30.0% | 27.5% |
| linear | power | 88.0% | 82.5% | 82.5% | 6.5% |
| linear_no_witness | power | 92.0% | 86.5% | 86.5% | 6.0% |
| null_ar1_0.3 | false_rate | 0.0% | 0.0% | 0.0% | 16.5% |
| null_ar1_0.7 | false_rate | 0.0% | 0.0% | 0.0% | 13.5% |
| null_no_witness | false_rate | 0.0% | 0.0% | 0.0% | 17.5% |
| sensor_step | false_rate | 0.0% | 0.0% | 0.0% | 87.5% |
| sensor_step_no_witness | false_rate | 95.5% | 11.5% | 11.5% | 87.0% |
| trend_plus_step | power | 2.0% | 2.0% | 2.0% | 7.0% |

## How good must M1 be? (simulated oracle, planning only)

| AI accuracy | v1 false | best v2 false | v1 power | best v2 power | would pass the rule |
|---|---|---|---|---|---|
| 0.85 | 11.0% | 1.6% | 52.8% | 47.8% | no |
| 0.95 | 11.0% | 0.3% | 52.8% | 51.2% | yes |
| 0.99 | 11.0% | 0.1% | 52.8% | 52.8% | yes |

Rule (section 13.3): accept only with significantly fewer false verdicts (paired exact
McNemar, p < 0.05) and power not lower by more than 2 percentage
points, with opinions from a real model. Re-run after every M1 version.
