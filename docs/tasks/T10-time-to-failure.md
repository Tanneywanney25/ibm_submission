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

- [ ] Hazard rows strictly respect time discipline (asserted like 01)
- [ ] S(t) calibration within ~5pp per decile at the three horizons
- [ ] Expected-failure-week for the top-1000: median error ≤ ~2 weeks
- [ ] Clearly labeled where weather is climatology vs forecast

**Effort ~5h (first to drop under pressure). Depends on:** panel machinery.
**Feeds:** building page, deck's "we also know when" beat.
