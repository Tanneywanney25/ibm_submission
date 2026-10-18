# T10 — M10, time-to-failure: predict WHEN, not just IF

**Goal:** a discrete-time hazard model giving each building a survival curve
over the winter — "50% chance of a first failure by Jan 20" — plus an expected
failure week for the watchlist. A new axis (timing) that none of the prior art
touches. New model name M10; frozen numbers untouched.

## Method (discrete-time survival = logistic hazard; our panel IS this data)

1. **Data:** building-days until FIRST failure of the season. From
   `building_day_counts` truth: for each (building, season), keep heat-season
   days up to and including the first cluster day (censor at May 31 if none).
   Hazard target: `fail on day t | alive through t-1`. Features: the standard
   31 (daily rows already buildable with 01's machinery; subsample alive-days
   for tractability, e.g. every 3rd day for never-failers).
2. **Model:** XGBoost on the hazard target (a classifier on day rows IS the
   discrete-time hazard with flexible baseline). Train seasons 2018-2024.
3. **Survival curves:** S(t) = Π(1 − h(τ)) over the season's forecastable
   path — for backtest, observed weather; for the live product, climatological
   TMIN beyond the 7-day forecast (say so on the chart).
4. **Evaluate on 2025-26:** calibration of S(t) at horizons (by Dec 1 / Jan 1 /
   Feb 1: predicted vs realized first-failure shares, by decile); C-index on
   first-failure timing; median-predicted vs realized failure week for the
   preseason top-1000.
5. **Site (stretch):** a small failure-timeline strip on the building page
   (cumulative risk by month) from a per-building `S(t)` shard.

## Deliverables

- `model/18_hazard.py` → `heat_model_hazard.json` (M10),
  `model/out/hazard_eval.csv`, per-building `expected_failure_week.csv`
- Catalog entry M10 with the calibration table

## Acceptance

- [x] Hazard rows strictly respect time discipline (asserted like 01: no row
      after first failure, c_last1 == prior-season count; both asserts green)
- [ ] S(t) calibration within ~5pp per decile at the three horizons —
      M10 MISSED (top two deciles overconfident by 8–42pp: compounding ~240
      daily hazards amplifies per-day overestimates; day-level isotonic can't
      fix the product). **M10b (`model/19_hazard_recal.py`) mostly fixes it:**
      a second isotonic mapping 1 − S(t) → realized first-failure share, fit
      on the 2024-25 full-universe curves, brings Jan 1 / Feb 1 within the
      bar (max |gap| 3.8 / 4.7pp) but Dec 1 decile 9 still misses at +8.0pp —
      a residual early-season overconfidence the pooled isotonic can't see
      (it showed in the 2024-25 in-season check too). Honestly reported in
      the catalog; the holdout is spent, so no further iteration.
- [ ] Expected-failure-week for the top-1000: median error ≤ ~2 weeks —
      **MISSED: 11.1 weeks (M10), 10.0 weeks after M10b recalibration**
      (449 of the top-1000 failed). Timing discrimination is real (C-index
      0.871 / 0.869 recalibrated) but absolute timing is not shippable.
- [x] Clearly labeled where weather is climatology vs forecast (observed
      throughout the backtest, stated in the script output and catalog; no
      site chart shipped — the stretch goal is dropped with the miss)

**Built + evaluated 2026-10-18 (trained on the LinuxONE guest).** Catalog
entry M10 has the full calibration table; outputs in `model/out/`
(`heat_model_hazard.json`, `hazard_eval.csv`, `expected_failure_week.csv`).
**M10b recalibration added 2026-10-18** (`model/19_hazard_recal.py` →
`hazard_recal_map.csv`, `hazard_eval_recal.csv`,
`expected_failure_week_recal.csv`; run on the guest): the 8–42pp overshoot
collapses to ≤4.7pp at Jan/Feb, Dec 1 top decile still +8.0pp, week error
10.0w. Neither ships to the site: displayed probabilities must be calibrated
at every horizon we'd show.

**Effort ~5h (first to drop under pressure). Depends on:** panel machinery.
**Feeds:** building page, deck's "we also know when" beat.
