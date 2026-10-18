# Model catalog — every model in HeatAhead

One entry per model (and baseline): what it predicts, what it eats, where it
lives, its measured numbers, and how to load it. Companion to
`model-iterations.md` (how we got here) and `engineering-log.md` (what happened).

All metrics are on the held-out 2025-26 winter unless marked otherwise.

---

## M1 — The cold-day ranker (the headline model)

- **Predicts:** P(building has 2+ distinct heat complaints within the next 48h),
  for one building on the eve of a freezing day.
- **Type:** ensemble — XGBoost 3.4.1 + sklearn HistGradientBoosting, probabilities
  averaged. 400 trees each, depth 6, lr 0.08.
- **Features (31):** building (units, floors, area, year built + 1900 flag,
  altered, CD, boiler defects, oil fuel, landlord portfolio size + portfolio
  complaints), history (2 prior seasons of complaints/violations, chronic,
  band reaction rates frigid/freezing/cold, days-since complaint/violation,
  whole-building outages last season), live (trailing 2/7/14/30-day counts,
  whole-building 14d, same-block 48h neighbors), weather (TMIN, TMAX, lag,
  3-day roll min, drop, snow, wind, weekday, days into cold season).
- **Trained on:** 622,362 building-days, seasons 2018-19 → 2024-25 (panel:
  positives + 2× sampled negatives, history universe).
- **Files:** `model/out/heat_model.json` (XGBoost, portable) +
  `heat_model.joblib` (sklearn, same-machine only). Built by `model/02_train.py`;
  loaded by 03/07 via the ensemble `predict()`.
- **Numbers @100:** 69.1% exact 48h · 86.1% per spell · 96.6% within 30d ·
  AUC-PR 0.981 on the panel. 6-fold forward-chaining CV: 6/6 winters won
  (mean 0.673 vs 0.634). Top features: days_since_c, c_last2, c_prev30,
  days_into_cold.
- **Serving speed (s390x, 3 cores):** 358,629 buildings/sec (p99 0.71 ms).

## M2 — The deployment twin (final scores for the demo)

- Same recipe as M1 but **trained on all eight seasons including 2025-26** —
  the model you'd actually ship this winter. Never used for any reported metric
  (it has seen the test winter by design).
- **Files:** `model/out/heat_model_final.json`; produced by `model/06_final_scores.py`,
  which also writes the demo artifact `ranked_inspection_list.csv` (67,125
  buildings: rank, score, p_calibrated, tenants_at_risk, lat/lon, history chips)
  under replayed Feb 8, 2026 weather.

## M3 — The daily calibrator

- **Maps M1's raw score → honest 48h probability.** Isotonic regression fit on
  142,000 full-universe (score, outcome) pairs sampled across the 71 test days
  (2,000/day) — full-universe pairs, because panel pairs carry a sampled base
  rate (~70%) that would inflate displayed probabilities ~60-fold.
- **File:** `model/out/calibration.csv` (pairs; 06 refits the isotonic at load).
- **Verified:** predicted matches observed in every bin across 9 splits (random,
  day-wise, mild→coldest). Below 20% predicted: within ~1pp everywhere. Display
  rule: exact % under 20, bands above; monotone, so ranking is unchanged.

## M4 — The season-risk model (the tenant number)

- **Predicts:** P(building loses heat at least once this winter), one row per
  building per season, features as of Oct 1 (21 features — M1's set minus live
  trailing counts and weather, since none exist at season start).
- **Type:** HistGradientBoosting (400 iters, depth 6) + its own isotonic
  calibrator (fit on half the held-out winter, verified on the other half).
- **Trained on:** 305,413 building-seasons, 2018 → 2024 (18.5% fail a season).
- **Files:** `model/09_season_risk.py` → `model/out/season_risk_2026.csv`
  (63,727 buildings: p_season capped at 0.99, rank, raw_score, history chips)
  and `season_reliability.csv` (the accuracy table for the app).
- **Verified:** bin-by-bin on 2025-26 — e.g. predicted 89–91% → actual 89–91%;
  every bin within ~2pp. For winter 2026-27: ~3,700 buildings ≥80%, ~8,000 ≥50%,
  median building ~8%.

## M5 — The Snap ML twin (IBM Z benchmark)

- Snap ML BoostingMachineClassifier (200 rounds, depth 6) **trained natively on
  the instance** on the M1 panel (XGBoost-3.x JSON import is incompatible with
  snapml's importer — "no objective defined"; NaNs imputed to −1 since its tree
  builder asserts on NaN).
- **Purpose:** measured s390x serving numbers, not accuracy claims:
  **481,356 buildings/sec batch, p99 0.51 ms** — 1.34× XGBoost on the same guest.
  Built/benchmarked by `model/04_snapml_bench.py`; not persisted to disk.

## M6 — The backtest fleet (validation only)

- Six single-backend XGBoost models, one per test winter 2020-21 → 2025-26, each
  trained only on the seasons before its test winter (`model/05_backtest.py`).
  Same features and hyperparameters as M1, no per-fold tuning; discarded after
  scoring. Results: `model/out/backtest_by_season.csv` — model ahead of the
  14-day baseline in all six winters.

## M7 — The ranking-objective experiment (T6a; NOT adopted)

- XGBRanker, `rank:pairwise` grouped by calendar day — optimizes list order
  directly. Same 31 features, split and budget as M1; no tuning.
  `model/11_ranker.py` → `heat_model_ranker.json` (margins, not probabilities).
- **Result (8 test spells, vs M1's frozen 86.1/96.1 @100):** spell p@100
  **87.9%** (+1.8), 30d **97.4%** (+1.3) — it met the k=100 adoption bar — but
  it *regresses deeper in the list*: k=1000 50.7 vs 51.4, k=2500 33.7 vs 34.8,
  rest-of-season @2500 73.1 vs 76.8.
- **Decision: not adopted.** Sharper top-100, worse everywhere below it, and
  margins would need fresh calibration for display. Kept in the catalog as the
  honest answer to "did you try learning-to-rank?" — yes, measured, trade-off
  documented. Frozen numbers unchanged.

## M8 — The enforcement ranker (T6b; a second product surface)

- M1's recipe, target = **verified failure** (heat violation within 7 days).
  `model/12_verified_model.py` → `heat_model_verified.json`; evaluated with
  `03_evaluate.py --model ... --label verified` (identical protocol, truth =
  violations).
- **Result (71 test cold days, verified-violation truth):** precision@100
  **30.2%** vs 16.5% for the best baseline (last season's violations) and
  14.8% for 14-day recency — roughly **2× the best simple rule**, and 48.0% of
  its top-100 produce a confirmed violation within 30 days. Panel AUC-PR 0.307
  on an 8.7% base.
- **Role:** the second queue — M1/M2 rank "who loses heat" (tenant protection),
  M8 ranks "who will produce a confirmed violation" (enforcement targeting).
  Stream 2's confirmation analysis is its validation story. Not part of the
  frozen headline; reported as its own entry.

## M9 — The graph neural network (trained on LinuxONE; NOT adopted)

- Two-layer mean-aggregation **GraphSAGE in pure PyTorch on the s390x guest**
  (the IBM container ships torch — a GNN trained on the mainframe). Graph:
  63k ever-active buildings linked through landlord hubs (one per
  multi-building owner) and tax-block hubs; 54 per-spell snapshots with the
  same 31 features and the same eve-of-spell time discipline as every model.
  `model/13_build_graph_dataset.py` + `model/14_graph_train.py`;
  results in `model/out/graph/m9_results.csv`.
- **Result (same 8 held-out spells):** p@100 **84.9** vs M1's 86.1 ·
  p@500 63.0 vs 64.6 · p@1000 49.4 vs 51.4 · p@2500 33.8 vs 34.8 —
  consistently 1–2 points below the frozen model at every k (val peaked
  epoch 2, early-stopped at 7).
- **Decision: not adopted.** The graph relations it would learn (landlord
  portfolios, block contagion) are already in M1 as explicit features
  (`lord_c_other_last1`, `nb_block_2d`), so message passing added smoothing,
  not signal. Kept as the measured answer to "why not deep learning / GNNs?"
  — tried, on IBM Z, under the frozen protocol; the disciplined GBM held.

## M11 — Spell-direct (ADOPTED as the per-spell queue; the biggest late gain)

- Same 31 features, but trained **directly on the evaluated task**: the 54
  full-universe spell snapshots (label = fails during the spell), early-stopped
  on the 2024-25 winter (30 trees sufficed), refit, test touched once.
  `model/21_spell_direct.py` → `heat_model_spell.json`, `m11_results.csv`.
- **Result (8 held-out spells): p@100 89.9% (+3.8 over the frozen 86.1)** with
  no regression at depth (64.8 / 51.3 / 34.9 vs 64.6 / 51.4 / 34.8) — unlike
  M7, the top-of-list gain costs nothing below it. Clears the adoption bar.
- **Verified (model/23):** three seed retrains land at 88.0 / 89.2 / 89.9 —
  quote "~88–90%", not the best draw — and the win is consistent: **7 of 8
  spells beaten** (exact p = 0.0078), the one loss by a single building on the
  mildest spell. M12 independently also wins 7/8, dissolving the
  two-finalists multiplicity concern. `ceiling_verification.csv`.
- **Role:** powers the per-spell inspector list going forward; the frozen
  submission numbers stay frozen, and the deck may add one line: "our latest
  spell-level model reaches 89.9% precision@100 (submission figure: 86.1%)."

## M12 — The tuned day-model (first hyperparameter search; ADOPTED variant)

- 20-trial randomized search, each config scored by spell p@100 on the
  **validation winter only**; the single winner alone touched the test spells.
  Winner: shallower and more regularized than the hand config (depth 4,
  800 trees, lr 0.05, min_child_weight 20). `model/22_hpo.py` →
  `heat_model_hpo.json`, `hpo_trials.csv`.
- **Result: 89.2 / 65.2 / 51.8 / 34.8** — improvement or tie at every k, and
  val→test held (0.896 → 0.892, no selection overfit). The protocol note is
  the point: the search never saw the test winter.
- **Role:** the tuned successor to M1's day-level config for anything built
  after the freeze; M1/M2 remain the cited submission models.

## M10 — The time-to-failure hazard model (T10; timing axis — calibration miss honestly reported)

- **Predicts:** the daily hazard of a building's FIRST failed48 of the season;
  survival curve S(t) = Π(1 − h) over the season, "P(first failure by Jan 20)",
  expected failure week. A new axis (WHEN, not just IF) no prior art touches.
- **Type:** discrete-time hazard = XGBoost (M1's config) on 1.94M weighted
  at-risk building-day rows (every building alive until its first failure;
  alive days strided ×7 and Horvitz-Thompson re-weighted, never-failers
  sampled at 20%; 46,423 first-failure events; base hazard 0.00088/day).
  Trained 2018-19 → 2023-24, hazard isotonic-calibrated on 2024-25
  (out-of-sample), tested ONCE on 2025-26. Survival products consume only
  each building's at-risk path (hazards after a realized failure are never
  used). Weather observed throughout — a backtest; the live product must
  label climatology beyond the 7-day forecast.
- **Files:** `model/18_hazard.py` → `heat_model_hazard.json` (M10),
  `hazard_calibration.csv` (raw-hazard/outcome pairs),
  `hazard_eval.csv`, `expected_failure_week.csv` (59,656 buildings:
  p_fail_season, expected/median failure week).
- **Discrimination (good):** time-dependent **C-index 0.871** on first-failure
  timing (450,808 comparable pairs) — the model genuinely knows WHO fails
  earlier.
- **Calibration (the honest miss):** S(t) at the three horizons is within
  ~4pp for deciles 0–7 but strongly overconfident in the top two deciles:

  | horizon | realized overall | decile 8 pred→real | decile 9 pred→real |
  |---|---|---|---|
  | by Dec 1 | 8.3% | 28.1% → 19.6% | 58.2% → 24.8% |
  | by Jan 1 | 12.2% | 41.2% → 27.3% | 72.6% → 30.9% |
  | by Feb 1 | 16.6% | 51.0% → 34.4% | 80.7% → 40.3% |

  Mechanism: tiny per-day hazard overestimates for the riskiest buildings
  compound over ~240 multiplications into a large cumulative overshoot — the
  day-level isotonic can't see the product. Top-1000 median |expected −
  realized| failure week: **11.1 weeks** (target was ~2; 402 of the top-1000
  failed).
- **Decision: NOT shipped.** Ranking by time-to-failure works (0.871); the
  absolute curve does not meet our display bar (probabilities shown to users
  must be calibrated), so no site surface uses M10. The identified fix — a
  second, horizon-level recalibration of 1 − S(t) on the 2024-25 curves
  (M10b) — is below. Frozen numbers untouched.
- **M10b — horizon-level recalibration (the fix, built):** a second isotonic
  g: cumulative predicted risk 1 − S(t) → realized first-failure share, fit
  on the 2024-25 full-universe at-risk curves (1.91M building-day pairs from
  34 strided days; the three 2024-25 horizon day-indices held out as an
  in-season check), applied on top of M10's day-calibrated curve. Monotone in
  t by construction, so the result is still a CDF and the expected failure
  week recomputes from its increments. `model/19_hazard_recal.py` →
  `hazard_recal_map.csv` (the isotonic's knots), `hazard_eval_recal.csv`,
  `expected_failure_week_recal.csv`; M10's own outputs untouched. Verified
  ONCE on 2025-26:

  | horizon | realized overall | max \|gap\| any decile | decile 8 pred→real | decile 9 pred→real |
  |---|---|---|---|---|
  | by Dec 1 | 8.3% | **8.0pp** | 23.1% → 19.5% | 32.9% → 24.9% |
  | by Jan 1 | 12.2% | **3.8pp** | 28.8% → 27.0% | 34.8% → 31.0% |
  | by Feb 1 | 16.6% | **4.7pp** | 32.0% → 34.9% | 35.4% → 40.1% |

  The 8–42pp overshoot collapses to ≤4.7pp at Jan 1 / Feb 1 (within the ~5pp
  bar); Dec 1 decile 9 still misses at +8.0pp — a residual EARLY-season
  overconfidence the pooled (t-free) isotonic cannot remove, visible in the
  2024-25 in-season check too (+7.3pp), so it is a known limitation, not a
  holdout surprise. C-index 0.869 (vs 0.871 — only isotonic ties moved it).
  Top-1000 median failure-week error improves 11.1 → **10.0 weeks** (449 of
  1000 failed): absolute timing is still far from the ~2-week target.
- **M10b decision: still NOT shipped.** Jan/Feb horizon probabilities now
  meet the display bar but Dec 1 does not, and the failure week remains
  unusable; shipping a timing surface that is right in February and wrong in
  December fails the "calibrated probabilities only" rule. A per-horizon
  (t-indexed) recalibration would likely fix Dec 1, but the 2025-26 holdout
  has now been consumed twice for this model family — further iteration
  would be fitting to the test winter, so M10b is where this line stops for
  the submission.

## B1–B3 — The baselines (every eval runs them under the identical protocol)

- **B1 last-season complaints:** rank by prior season's distinct complaints.
  43.5% @100 (48h). The prior-art standard — what every earlier paper amounts to.
- **B2 trailing-14-day complaints:** the strong one. 61.7% @100 (48h), 77.1% per
  spell, 91.0% @100 30d. Recomputed per ranking day.
- **B3 last-season violations:** 14.7% @100 — violations alone are too sparse to
  rank with, which is also why the Heat Sensors Program's selection rule is weak.

## Lineage and reproduction

```
00_second_tier.py -> landlord + boiler tables
01_build_panel.py -> panel.csv (features + labels, leak-asserted)
02_train.py       -> M1 (heat_model.json/.joblib) + feature_importance.csv
03_evaluate.py    -> M1 metrics + M3 pairs (calibration.csv)
04_snapml_bench   -> M5 numbers        05_backtest.py -> M6 fleet + CV table
06_final_scores   -> M2 + ranked list  07_spell_eval  -> spell/season metrics
09_season_risk    -> M4 + season_risk_2026.csv
```

Rules that apply to every model here: features strictly pre-date the prediction
moment; distinct `complaint_id` only; models cross machines as JSON, never
pickles (s390x is big-endian); displayed probabilities are calibrated and capped
at 99%; nothing below building level is ever shown.
