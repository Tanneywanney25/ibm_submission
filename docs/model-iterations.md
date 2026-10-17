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

## Honest limitations (say out loud)

- The label is "tenants called 311 twice in 48h", not "the boiler died" — reporting
  bias is real and documented (NYU 2025); the verified-violation tier is the check.
- Backtests use observed temperature as the stand-in forecast; we measured archived
  24-48h forecasts at ~2°F error, so live performance should be close.
- Cold spells are only knowable ~7 days out; the system triggers 1-2 days ahead.
- The history cut means never-complained buildings are not ranked; the Heat Sensors
  Program and physical-risk screening are the complement for those.
