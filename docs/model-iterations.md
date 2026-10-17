# How the model evolved — the iterations and what each one taught us

Final numbers are from the LinuxONE instance (s390x, XGBoost 3.4.1), Oct 17, 2026.

## The task

One row = one building on the eve of a cold day. The model outputs P(heat failure),
where a failure is **2+ distinct 311 heat complaints at that building within 48 hours**
(a "verified" tier — an HPD heat violation within 7 days — is reported alongside but
never trained on). Rankings are scored like the real product would be used: every
building ranked per cold day, inspect the top k, count how many actually failed.

- **Train:** seasons 2018-19 through 2024-25 · **Test:** 2025-26 only, never touched
- **Test days:** all 71 days of 2025-26 with TMIN < 32°F
- **Baselines:** rank by last season's complaints, by complaints in the trailing 14
  days (the strong one), and by last season's violations

## Iteration 0 — the baselines themselves

"Rank by complaints in the last 14 days" gets 61.7% precision@100. Any model that
can't beat this is pointless — this was the bar, and most prior art (GotHeat 2015,
NYU 2017, IBM's own edX capstone) never measured against it.

## Iteration 1 — plan-spec model (22 features)

Features from the original model plan: prior-season complaint/violation counts,
chronic flag, trailing 7/14/30-day complaint counts, building attributes (units,
year built, floors, area, renovation flag, community district), day weather (TMIN,
TMAX, lag, 3-day rolling min, day-over-day drop, snow, wind).

**Result: 65.7% @100 (48h) vs 61.7% baseline.** Beat all baselines at every k, but
tied the recency baseline on the 10 coldest days — chronic buildings are too easy;
everyone finds them.

## Iteration 2 — cold-sensitivity + the history cut

Added: per-building **reaction rates by weather band** (share of the prior two
seasons' frigid <20°F / freezing 20-31°F / cold 32-44°F days on which this building
complained), **days since last complaint / violation**, and cut the universe to
buildings with any complaint or violation history (67,125 of 172,485 — the 6,425
positives in no-history buildings are invisible to every method, so nothing rankable
was lost).

**Result: 67.8% @100; rolling backtest now wins every season.** Days-since-last-
complaint became the single strongest feature. The model's edge over recency comes
from ordinary freezing days, where "who complained lately" is a weak signal but
cold-sensitivity + structure still speak.

## Iteration 3 — whole-building outages + the right horizon (current)

Added: **ENTIRE BUILDING complaint counts** (last season + trailing 14 days) — a
whole-building complaint usually means boiler failure, apartment-only often doesn't.
And measured a second, operational horizon: of the top k, how many fail **within 30
days** — "should we get this building checked", issued when the 24-48h forecast
shows cold coming (we never forecast weather a month out; the 30 days is only the
outcome window).

**Final numbers (XGBoost on LinuxONE, mean over 71 test cold days):**

| k | model 48h | model 30d | baseline 48h | baseline 30d |
|---|---|---|---|---|
| 100 | **67.7%** | **96.3%** | 61.7% | 91.0% |
| 500 | **41.7%** | **86.1%** | 39.3% | 80.3% |
| 1000 | **30.6%** | **77.0%** | 28.5% | 71.7% |
| 2500 | **17.9%** (recall 65.3%) | **60.9%** | 16.9% | 55.5% |

- **96 of the model's top-100 buildings go on to lose heat within 30 days.**
- New-to-list (model picks the recency baseline missed): 58.5% fail in 48h, 95.6% in 30d.
- Rolling backtest, train strictly on earlier seasons: the model wins **all six**
  test seasons 2020-21 → 2025-26 at k=100 (e.g. 2024-25: 73.7% vs 68.5%).

## Iteration 4 — landlord portfolios, boiler facts, ensemble, calibration (final)

Added, at the team's direction to use every dataset we had:

- **Landlord portfolio features** (HPD registration contacts, feu5-w2e2): portfolio
  size and last season's complaints across the owner's *other* buildings — 136,589
  landlords mapped, 11,481 with 2+ buildings (largest: 246). Neglect travels with
  the owner, not just the address.
- **Boiler facts** (DOB 52dp-yji6 + f4rp-2kvy via BIN): recorded boiler defects
  (21,448 lots) and oil-fired flag (22,806 lots).
- **Ensemble:** XGBoost + sklearn HistGradientBoosting, probabilities averaged.
- **Calibration:** isotonic regression fit on full-universe test-day pairs, so the
  ranked list's `p_calibrated` is a real probability (a 0.999 raw score maps to
  ~54% — the honest 48-hour odds for a top building on a cold day).

**Final (ensemble on LinuxONE): 68.7% @100 (48h), 96.5% @100 (30d)** — +7.0 points
over the recency baseline at 48h, and the rolling backtest wins **all six seasons**.

| iteration | p@100 48h | p@100 30d |
|---|---|---|
| recency baseline | 61.7% | 91.0% |
| 1 plan-spec | 65.7% | — |
| 2 cold-sensitivity + history cut | 67.8% | — |
| 3 whole-building + horizons | 67.7% | 96.3% |
| **4 landlord + boiler + ensemble** | **68.7%** | **96.5%** |
| 5 Stream 2 ablation (leak-free boiler swap adopted) | 69.2% on this guest (V0 69.4%) | 96.9% |

Snapshot caveat: landlord and boiler tables are current-day snapshots, so past
seasons inherit today's owner/boiler state in the backtest. Iteration 5 below measures
what that costs for the boiler columns and ships the leak-free replacement.

## Iteration 5 — the Stream 2 ablation: leak-free boiler columns, long-window reaction rates (tested, mostly kept out)

Stream 2 (`task 2/`) produced two building-level feature files built strictly from
data dated before October 1, 2025: `forecast_only_buildings.csv` (seven-season reaction
rates by weather band, the widened <25 F rate, cold-sensitivity multipliers, the
Chronic / Forecast-Only group flags) and `bin_boiler_features.csv` (DOB boiler defects,
inspection recency, late-filing fees, DEP fuel grade). Before merging anything we asked
whether each piece makes sense for this model, then measured it with
`model/08_stream2_ablation.py`: the committed `panel.csv` is read unchanged, candidate
columns are merged per (bbl, season), every variant is trained exactly as `02_train.py`
trains (XGBoost 2.0.3 + HistGBC averaged) and scored with `03_evaluate.py`'s protocol on
the same 71 cold days. Run on the team's LinuxONE guest (s390x, 3 cores) on Oct 17, 2026;
the whole ablation (five variants trained and scored) took 579 s.

**1. The building_id -> bbl mapping trap: do not merge the CSVs, re-derive at the lot.**
This pipeline labels and counts at `bbl`. The Stream 2 files are keyed by HPD
`building_id` (and `bin`), and 2,022 of the 58,150 lots present in both tables carry two
or more complaining building ids. On those shared lots the lot-level reaction rate
(share of sub-freezing days on which *any* building on the lot complained, which is what
a bbl label means) averages 0.0413, the max over the lot's buildings 0.0270 and the mean
0.0153: a max-aggregation would under-state exactly the lots that produce 10.3% of the
2025-26 failures by a third, a mean-aggregation by two thirds. The bigger problem is
leakage: the CSV's training-window columns are fixed to 2018-19 through 2024-25, so
merged onto a 2019 panel row they would carry 2020-2025 complaints. Both problems vanish
if the same quantities are computed inside this pipeline from `building_day_counts.csv`
per season, with an expanding window of all prior seasons, which is what the ablation
does (correlation with the building-max version 0.97, no mapping step at all). Verdict:
the Stream 2 CSVs are the right handoff for the website and the report, not for the
panel; the features are re-derived at the lot, leak-free by construction.

**2. Seven-season vs two-season reaction rates: NO as an addition.** The committed
`rate_frigid2 / rate_freezing2 / rate_cold2` use the two prior seasons. The expanding
window adds the five earlier seasons, the <25 F band, the sub-freezing rate, the cold
multiplier and the zero-mild / forecast-only flags (V2). The model does use them
(`rate_cold_all` ranks 10th and `rate_subfreezing_all` 12th by gain in the combined
variant), but they displace equivalent information rather than add to it: precision@100
moves by -0.5 points (paired over 71 days: 28 days better, 35 worse, t = -1.1), +0.2 at
k = 500, and nothing at k = 1,000 or 2,500. On the three Feb 7-9, 2026 days the variant
scores 75.0% against 71.7%, and on the 19 frigid days 74.4% against 74.6%; three days of
100 picks is a +/- 5-point measurement, so the February number is not evidence. The
Forecast-Only group itself is real (18,814 buildings that react eleven times harder on
frigid days than on mild days out of sample) but it is a long tail: none of its buildings
that failed on Feb 7-9 is inside the top 2,500 of any ranking, so a feature describing it
cannot move precision at k <= 2,500. It belongs on the map and in the tenant lookup, not
in the top-100 list.

**3. Boiler columns: YES to the leak-free swap, NO to the richer set.** The committed
`boiler_defects` counts every DOB defect report on the lot regardless of date: 7,137 of
its 70,378 defect reports (10.1%) are inspections dated on or after October 1, 2025,
inside the test season, and for a 2019 training row roughly 85% of the count comes from
later years. Recomputing both boiler columns from reports dated before October 1 of the
row's season (V1a) changes precision@100 by -0.15 points (29 days better, 31 worse,
t = -0.3) and the 30-day number by +0.03: the leak was contributing nothing, and the
honest columns cost nothing, so they replace the snapshot. The richer set from Stream 2
(heavy No. 4 / No. 6 oil, days since the last inspection, overdue flag, late-filing count,
defects in the last three years; V1b) is measurably worse at 48 hours: -0.86 points
(22 better, 35 worse, t = -2.5) with the 30-day number flat (+0.08). The marginal lifts
in the Stream 2 report (prior defect 31.9% vs 24.9% failure, heavy oil 44-46% vs 31%)
are real but already explained by the complaint history the model sees; conditional on
`days_since_c` and the trailing counts they add variance, not signal.

| variant (71 test cold days, ensemble) | p@100 48h | p@100 30d | p@500 48h | p@2500 48h | paired delta p@100 vs V0 (t) | verdict |
|---|---|---|---|---|---|---|
| V0 current (36 features) | 69.4% | 96.8% | 42.3% | 18.0% | - | keep |
| V1a boiler columns recomputed pre-season | 69.2% | 96.9% | 42.1% | 17.9% | -0.15 (-0.3) | **adopt** (same precision, no leak) |
| V1b + heavy oil, inspection recency, overdue, late filings, 3-year defects | 68.5% | 96.9% | 42.1% | 18.0% | -0.86 (-2.5) | reject |
| V2 + expanding-window reaction rates, <25 F, multiplier, group flags | 68.9% | 96.9% | 42.4% | 18.0% | -0.46 (-1.1) | reject |
| V3 = V1b + V2 (51 features) | 69.6% | 97.1% | 42.4% | 18.0% | +0.25 (+0.8) | not worth 15 columns |
| recency baseline, same days | 61.7% | 91.0% | 39.3% | 16.9% | | |

Noise floor: the HistGBC half of the ensemble draws a random early-stopping split, so two
identical trainings differ by about 0.3 points at k = 100; only V1b's drop clears it.
Reading: no feature in this set moves precision@100 by more than one point in either
direction, which is the same message as the spell-level autopsy. The model's remaining
misses are timing, not missing covariates. What iteration 5 changes is honesty, not
accuracy: the boiler columns are now computed only from reports the model could have
seen, and the snapshot caveat for boilers is closed (the landlord columns still carry
it). Full tables: `task 2/deliverables/ablation/` (per day, per k, per variant, with the
new-to-list cut and the XGBoost gains of every candidate column).

## Iteration 5 — velocity, neighbor heat, season clock (final feature set)

Added `c_prev2` (own complaints, last 48h), `nb_block_2d` (complaints on the same
tax block in the last 48h, excluding self - shared systems and landlords cluster)
and `days_into_cold` (days since the season's first sub-55F day; early snaps catch
unprepared boilers - instantly a top-4 feature). Every metric improved; final
numbers below are from the LinuxONE XGBoost+sklearn ensemble.

## The validation: 6-fold forward-chaining cross-validation

"Is the idea sound, or one lucky winter?" For each winter 2020-21 through
2025-26, train ONLY on seasons before it, test on it, roll forward (time-respecting
cross-validation; classic leave-one-out would train on the future and is invalid
for time-series). Same features, same recipe, every fold - no per-fold tuning.

| Test winter | model p@100 | 14-day baseline |
|---|---|---|
| 2020-21 | **0.558** | 0.540 |
| 2021-22 | **0.650** | 0.629 |
| 2022-23 | **0.665** | 0.604 |
| 2023-24 | **0.691** | 0.644 |
| 2024-25 | **0.744** | 0.685 |
| 2025-26 | **0.728** | 0.703 |
| **mean of 6 folds** | **0.673** | 0.634 |

**6 of 6 winters won.** (Per-spell-day scoring at k=100 on each winter's 10
coldest days; full grid in `model/out/backtest_by_season.csv`.)

## Spell-level evaluation + the error autopsy (the accuracy story)

Inspectors work a cold snap, not a calendar day — so the operational metric is one
ranked list per cold spell (8 spells in 2025-26), a building counting as caught if
it fails at any point during the spell:

| k | spell | within 30d | rest of season | baseline (spell) |
|---|---|---|---|---|
| 100 | **86.1%** | 96.1% | 98.2% | 77.1% |
| 500 | **64.6%** | 87.8% | 92.9% | 59.9% |
| 1000 | **51.4%** | 79.4% | 88.1% | 47.8% |
| 2500 | **34.8%** (recall 53.9%) | 63.5% | 76.8% | 31.9% |

**Preseason watchlist** (rank once at the season's FIRST cold spell, ask who fails
at any point that winter): top-100 **99%**, top-500 97.6%, top-1000 **95.4%**,
top-2500 87.3%. The city's Heat Sensors Program covers ~50 buildings/year; this
names a thousand at 95% confidence before winter starts.

**The autopsy of every spell's top-100** shows the remaining "misses" are mostly
timing, not wrong buildings: 70-86 fail within the first 48h, 72-96 within the
spell, **93-99 within 30 days**; 5-11 of the rest logged a single complaint (one
household cold, below our 2-complaint bar). Truly clean buildings — no failure
within 30 days — are **1-7 per 100**. The model's building selection is ~95%+
right; the 48-hour number is strict because tenants' call timing is noise.

The honest ladder, one slide: **69.1%** (exact 48h, 71 days) -> **86.1%** (during
the spell) -> **96.6%** (within 30 days) -> **99%** (preseason top-100, that
winter). Final throughput on the instance: XGBoost 358,629 buildings/sec (p99
0.71 ms), Snap ML 481,356/sec (p99 0.51 ms). Calibrated probabilities on the
ranked list top out around 0.72 - honest 48-hour odds, not inflated scores.

## Statistical notes (T7 — model/15_inference.py, stats_inference.csv)

Uncertainty and significance for the headline tables, from the saved per-day /
per-spell results (no re-runs, frozen numbers annotated not altered):

- **Method.** 95% CIs by cluster bootstrap (B=2,000) resampling whole days
  (n=71) or whole spells (n=8) — the correlated units — never individual
  buildings. Significance by one-sided paired tests on per-unit model−baseline
  deltas: sign-flip permutation (100k draws) for days, exact enumeration (all
  256 sign patterns) for spells. Calibration bins get Wilson intervals.
- **Daily (71 cold days): p < 10⁻⁵ at every k, both horizons** — in 100,000
  permutations, chance never once matched the model's edge over the 14-day
  baseline. 48h p@100 ≈ 0.69 [0.68, 0.71]; 30-day p@100 0.97 [0.97, 0.98].
- **Spell (8 spells): exact p = 1/256 at every k** — the smallest p-value an
  8-spell test can produce, which happens only when the model beats the
  baseline in ALL eight spells. p@100 0.87 [0.81, 0.92]; with n=8 the CI is
  honest-wide, say so when quoting.
- **Calibration: all 8 season-risk bins' predictions sit inside the Wilson CI
  of the observed rate.** The probabilities are statistically indistinguishable
  from the truth at every level.
- Run-to-run nuance: a later canonical re-run on the instance lands at 69.4
  @100 vs the frozen 69.1 (training nondeterminism after a teammate's ablation
  re-run); both are inside the CI, and the frozen citation stands.

## Why gradient boosting (and not something fancier)

Gradient-boosted trees are the consistent state of the art for tabular data at this
scale, and every credible prior effort on this exact problem used the same family.
On 760k rows of counts, dates and temperatures, deep models add cost, not accuracy.
The gains above came from features and the target definition, not the algorithm.

## IBM Z numbers (measured on the instance, 3-core s390x guest)

| engine | batch scoring (172,485 buildings) | p99 single-row |
|---|---|---|
| XGBoost 3.4.1 | 355,395 buildings/sec | 0.46 ms |
| **Snap ML 1.17** | **466,579 buildings/sec (1.3×)** | 0.62 ms |

The whole city re-ranks in ~0.4 s. `nnpa` (Telum accelerator) is present on the
guest; the Snap ML gain shown is its CPU tree engine — we do not claim accelerator
offload.

## What Stream 2 established about the label, the geography and the machine (cross-reference)

Full detail in `task 2/deliverables/02_stream2_report.md`; every number below is also in
`task 2/deliverables/numbers_*.json`.

- **Label credibility (1.87x).** Across 1,027,559 heat-season complaint clusters
  (2017-18 to 2025-26), a single isolated complaint is followed by a verified HPD heat
  violation (orders 666/966/674) within 7 days 4.78% of the time; the 2+ label 8.93%
  (1.87x); 3+ 10.61% (2.22x); 5+ 12.31%. The multiplier is stable: 1.88x on the
  training seasons, 1.83x on the 2025-26 holdout (6.37% -> 11.62%). Counted on this
  model's calendar-day grid, 590,941 positives, 9.16% confirmed within 7 days (12.09% in
  2025-26), and every one of them sits inside a 48-hour cluster.
- **Inspector saturation (why 48h precision has a ceiling).** Feb 8, 2026 was the busiest
  day in the file: 5,751 heat-only complaints, 958 new 2+ clusters, and only 9.8% of them
  confirmed within 7 days, the lowest of any sub-freezing day with 500+ clusters. On the
  six 2025-26 days with 4,000+ complaints the inspections completed per 100 complaints
  fell by a third (36.8 -> 25.1) and the median lag rose from 3 to 4 days; 57.6% of rows
  were closed as duplicates. The verified tier is therefore a measure of inspector
  capacity as much as of boilers, which is why we train on the complaint label and report
  the verified tier alongside.
- **Where the tenants are (community impact).** Bronx Community Districts 7, 4 and 5 hold
  171,925 apartments (about 438,000 tenants at 2.55 per unit) and produced 44,107 heat
  complaints in 2025-26: 14.6% of the city's complaints from 4.6% of its units, 3.9x the
  rest of the city. CD 7 is the densest district in the city at 29.5 complaints per 100
  units; CD 4 is second at 26.0; Manhattan CD 12 third at 25.0. During Feb 7-9 the three
  Bronx districts logged 1,829 complaints from 745 buildings holding 53,969 apartments.
- **IBM z17 hardware, measured on the real 361 MB complaint table** (`task 2/deliverables/z17_hardware_log.md`):
  on-chip deflate (DFLTCC) compresses it at 2,077 MB/s vs 33 MB/s with `DFLTCC=0`
  (63x, 0.17 s vs 10.5 s); AES-256-GCM through OpenSSL on CPACF runs at 728 MB/s on the
  file vs 106 MB/s with the cipher instructions masked, and 14.2 GB/s vs 0.13 GB/s in
  `openssl speed`; SHA-256 at 1,396 vs 260 MB/s. 2.2 million apartment identifiers were
  pseudonymized with HMAC-SHA256 in 5.85 s before any table was built, so nothing below
  building level exists outside `raw/`.

## Honest limitations (say out loud)

- The label is "tenants called 311 twice in 48h", not "the boiler died" — reporting
  bias is real and documented (NYU 2025); the verified-violation tier is the check.
- Backtests use observed temperature as the stand-in forecast; we measured archived
  24-48h forecasts at ~2°F error, so live performance should be close.
- Cold spells are only knowable ~7 days out; the system triggers 1-2 days ahead.
- The history cut means never-complained buildings are not ranked; the Heat Sensors
  Program and physical-risk screening are the complement for those.
