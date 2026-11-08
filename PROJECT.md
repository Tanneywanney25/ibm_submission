# HeatAhead — predicting NYC heat outages before the cold arrives

**NYU Tingineers · IBM Z Datathon, October 17–18, 2026 · built on an IBM z17 LinuxONE (s390x)**

**Live site:** https://ibmsubmission.vercel.app

## The problem

NYC tenants filed **300,000+ no-heat complaints** last winter — 5,751 on the single worst
day. Since October 1, 2026, HPD must attempt an inspection for every non-anonymous heat
complaint, with roughly 350 inspectors and no way to prioritize. The Comptroller's #1
recommendation — data-driven prioritization — was still unimplemented.

## What we built

HeatAhead reads the weather forecast and, **before** the cold arrives, ranks every
residential building in NYC by the probability it loses heat — so inspectors knock before
tenants freeze. One model, one ranked list, scored per fixed inspection budget.

Prior work (GotHeat 2015, Kontokosta et al. 2017, IBM's own edX capstone, Localize.city)
built building-level heat classifiers. None is forecast-triggered, none scores per
inspection budget, none ships calibrated probabilities. That combination is the
contribution.

## Results (held-out 2025–26 winter, top 100 ranked buildings)

| horizon | HeatAhead | best baseline (14-day recency) |
|---|---|---|
| fails within the exact 48h | **69.1%** | 61.7% |
| fails during that cold spell | **86.1%** | 77.1% |
| fails within 30 days | **96.6%** | 91.0% |
| preseason list: fails that winter | **99%** (95.4% @1000) | 96% |

- **Validation:** 6-fold forward-chaining cross-validation — train only on past winters,
  test on the next, roll forward. The model wins **6 of 6** winters (mean p@100 0.673 vs
  0.634), with no per-fold tuning.
- **Calibrated probabilities:** isotonic calibration, verified bin-by-bin on held-out data
  across nine splits, including fit-on-mild-days → test-on-coldest. When the model says
  15%, 15.2% of buildings fail.
- **Per-building winter risk:** every ranked building gets its own number. For 2026–27,
  3,801 buildings enter the winter at ≥80% risk — the city's Heat Sensors Program watches
  about 250.

## The data

All public: 2.2M HPD heat complaints (2017–2026), 223k violations, PLUTO (172,485 lots
with 3+ units), landlord registrations, DOB boiler inspections and fuel records, NOAA and
Open-Meteo weather — including **archived 24/48-hour forecasts**, so backtests use what
was actually forecast (~2°F error at 48h), not hindsight.

Traps found and handled along the way: BBL identifiers read as floats (silently breaking
joins), placeholder build years, leaky status columns, pre-2010 data-entry noise, and 45%
duplicate-flagged / 50% anonymous complaints — the label counts distinct complaint IDs
only, and the feature build asserts that every feature strictly pre-dates the ranking
moment.

## The model

One row = one building on the eve of a cold day; label = 2+ distinct heat complaints
within 48 hours. 31 features in four families: building fabric (PLUTO + boiler + landlord
portfolio), complaint history (prior seasons, per-temperature-band reaction rates),
live activity (trailing 2/7/14/30-day counts, whole-building outages, same-block neighbor
complaints), and weather (TMIN/TMAX, rolling minimum, temperature drop, snow, wind).
XGBoost + scikit-learn ensemble, improved across five iterations from 65.7% to 69.1%
precision@100.

Supporting analysis gave the label teeth: clusters of 2+ complaints are confirmed by a
heat violation within 7 days at 1.87× the single-complaint rate, stable across training
and holdout. We also measured inspector saturation (on 4,000+ complaint days, inspections
per 100 complaints fall by a third) and identified 18,814 "Forecast-Only" buildings that
only ever complain on freezing/frigid days — buildings only a weather-triggered system
sees. Community impact: three Bronx community districts hold 4.6% of the city's units but
14.6% of its 2025–26 heat complaints.

## IBM Z — measured, not claimed

The full pipeline runs end to end on an IBM z17 LinuxONE guest (s390x, 3 cores, Telum
`nnpa` accelerator present):

| engine | batch (172,485 buildings) | p99 single row |
|---|---|---|
| XGBoost 3.4.1 | 358,629 /sec | 0.71 ms |
| **Snap ML 1.17** | **481,356 /sec (1.34×)** | **0.51 ms** |

The entire city re-ranks in ~0.36 seconds. A supplementary benchmark compared Snap ML's
CPU tree engine against the IBM zDNN (Telum) tensor path on the same guest, with full raw
timings, hashes and reproduction steps published — CPU won this tree-model workload
4.71×, and we say so.

## The product

- **Real-time replay:** the Feb 7–9, 2026 cold snap (13,222 complaints, 6,382 buildings)
  replayed as a live event stream — complaint arrives → rolling features update → model
  re-scores → inspector queue re-sorts. Flask API on the LinuxONE guest.
- **Inspector map:** every ranked building, sortable by probability of failure or by
  tenants at risk (calibrated probability × units).
- **Tenant lookup:** type an address, get "your building has an N% chance of losing heat
  this winter," with complaint/violation history, landlord portfolio and boiler record.
- **Alerts:** register a building and an email; when the 7-day forecast shows a freezing
  run, buildings crossing the calibrated threshold get one email per spell with the 311
  action line.
- **Public site:** Next-to-live architecture — the page is served by Vercel, while
  sign-ups, geocoding, storage and the live replay all run on the s390x guest. Later
  additions: Google + email sign-in, user accounts, and an "Ask the data" natural-language
  question page.

## Honest limitations

1. The label is "tenants called 311 twice in 48h," not "the boiler died" — quiet
   suffering is undercounted; the violation-confirmation tier is the check.
2. Backtests use observed temperature as the forecast stand-in (archived forecasts
   measure ~2°F error at 48h, so live performance should be close).
3. Landlord/boiler tables are current snapshots applied to past seasons.
4. Buildings with no complaint history aren't individually ranked; sensor programs and
   physical-risk screening complement them.
5. Cold spells are knowable ~7 days out; we trigger 1–2 days ahead, never a month.

## Stack

Python · pandas · NumPy · scikit-learn · XGBoost · IBM Snap ML · Flask · Folium ·
R/data.table + Quarto (EDA) · Next.js on Vercel · IBM z17 LinuxONE (s390x)

## Repo map

| where | what |
|---|---|
| `model/` | the full pipeline, numbered `00`–`09` |
| `analysis/` | weather bands, building-type × cold reaction rates |
| `task 2/` | label credibility, Bronx geography, boiler join, z17 hardware log |
| `realtime/` | live replay event loop + Flask API |
| `web/`, `api/` | the public site |
| `docs/` | the full story (`SUBMISSION.md`), model iterations, deployment contract |
