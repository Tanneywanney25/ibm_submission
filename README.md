# HeatAhead — forecast-triggered heat-failure prediction for NYC buildings

**Live website:** [Open HeatAhead](https://ibmsubmission.vercel.app/)

> **Set the team number in the title above and in the Hack2skill project title before submitting.**

NYC tenants filed **300,000+ no-heat complaints** last winter. Since Oct 1, 2026, HPD must
attempt an inspection for every non-anonymous heat complaint — with ~350 inspectors and no
way to prioritize. HeatAhead reads the weather forecast, and **before** the cold arrives,
ranks every residential building by the probability it loses heat — so inspectors knock
before tenants freeze.

Built at the IBM Z Datathon, Oct 17–18, 2026, on an IBM z17 LinuxONE guest (s390x).

## Start here

- [Try the live website](https://ibmsubmission.vercel.app)
- [Read the submission story](docs/SUBMISSION.md)
- [See the models, methods and validation results](docs/models-complete-report.md)
- [Inspect the IBM Z benchmark and reproduction steps](docs/benchmarks/2026-10-18-emerson/README.md)
- [Find the presentation scripts](slides/README.md)
- [Browse all project documentation](docs/README.md)

Contributing code? Read [CLAUDE.md](CLAUDE.md) for project rules and
[the deployment guide](docs/VERCEL.md) before changing the website.

## The results (all on the held-out 2025-26 winter)

One model, one list, four honest clocks — of the **top 100** ranked buildings:

| horizon | model | best baseline (14-day recency) |
|---|---|---|
| fail within the exact 48h | **69.1%** | 61.7% |
| fail during that cold spell | **86.1%** | 77.1% |
| fail within 30 days | **96.6%** | 91.0% |
| preseason list: fail that winter | **99%** (95.4% @1000) | 96% |

- **Validation:** 6-fold forward-chaining cross-validation — train only on past winters,
  test on the next, six times. The model wins **6 of 6** (mean p@100 0.673 vs 0.634).
- **Calibrated probabilities:** when we say 15%, 15% fail — verified bin-by-bin on
  held-out data, nine splits, including fit-on-mild-days → test-on-coldest.
- **Per-building winter risk:** every building gets its own number
  (`model/out/season_risk_2026.csv`); 3,801 buildings enter 2026-27 at ≥80%.
- **IBM Z, measured:** Snap ML re-scores all 172,485 buildings at **481,356
  buildings/sec (p99 0.51 ms)** on a 3-core s390x guest — 1.3–1.4× XGBoost. `nnpa`
  (Telum accelerator) present on the guest.

## Why IBM Z

HeatAhead can compare CPU and on-chip accelerator inference on the same IBM Z
guest, using the same exported model. A supplementary October 18 benchmark
verified both paths on `s390x`, machine type `9175`, with `nnpa` present and three
requested threads per engine:

| Snap ML engine | Median time for 62,487 building rows | Scores/second | Single-row p99 |
|---|---:|---:|---:|
| CPU (`compress_trees`) | 97.624 ms | 640,081 | 0.028010 ms |
| IBM zDNN (`zdnn_tensors`) | 459.850 ms | 135,886 | 0.067346 ms |

Both paths closely matched the original XGBoost scores across every tested row.
CPU batch scoring was **4.71× faster in this run**, supporting CPU inference for
this workload. The comparison uses 62,487 complete rows from a February 6 feature
snapshot, excludes 229 incomplete rows, and times model inference with setup,
calibration and web/replay processing excluded. It is a separate workload from
the frozen 172,485-row benchmark above.

[Full benchmark, raw timings, hardware metadata, execution diagram and reproduction steps](docs/benchmarks/2026-10-18-emerson/README.md).

## Repo map

| Folder | Contents |
|---|---|
| [docs/](docs/README.md) | Submission story, model reports, deployment guides and task notes |
| [web/](web/) | Flask application, website templates and static assets |
| [api/](api/) | Vercel entry point for the Flask application |
| [public/](public/) | Precomputed assets included in the public deployment |
| [model/](model/README.md) | Training, evaluation, calibration and LinuxONE benchmark scripts |
| [realtime/](realtime/README_MODEL.md) | Complaint replay, building re-scoring and service API |
| [analysis/](analysis/README.md) | Weather bands, building-type reaction rates and heatmaps |
| [task 2/](task%202/README.md) | Violation confirmation, Bronx geography, Forecast-Only buildings, boiler joins and hardware logs |
| [R/](R/) | Early Quarto exploration and preparation of the master tables |
| [assistant/](assistant/) | Assistant service code; see [the assistant guide](docs/ASSISTANT.md) |
| [sim/](sim/) | Policy simulation |
| [tests/](tests/) | Website and service checks |
| [slides/](slides/README.md) | Presentation and explainer scripts |

## Reproduce

Data (not in git — complaints CSV is 345 MB) comes from the sources below into `data/`;
names and layout in [the documentation index](docs/README.md). Then:

```
python model/00_second_tier.py   # landlord + boiler feature tables
python model/01_build_panel.py   # label + features (leak-checked)
python model/02_train.py         # XGBoost + sklearn ensemble
python model/03_evaluate.py      # 71 cold days, precision@k vs 3 baselines
python model/05_backtest.py      # 6-winter forward-chaining CV
python model/07_spell_eval.py    # per-spell + season horizons, error autopsy
python model/09_season_risk.py   # per-building winter risk (the tenant number)
python model/04_snapml_bench.py  # LinuxONE: Snap ML throughput (s390x)
```

LinuxONE setup: [model/linuxone_setup.md](model/linuxone_setup.md).

## Data sources (NYC Open Data unless noted)

- HPD Housing Maintenance Code Complaints and Problems — https://data.cityofnewyork.us/d/ygpa-z7cr
- HPD Housing Maintenance Code Violations — https://data.cityofnewyork.us/d/wvxf-dwi5
- HPD Multiple Dwelling Registrations — https://data.cityofnewyork.us/d/tesw-yqqr
- HPD Registration Contacts — https://data.cityofnewyork.us/d/feu5-w2e2
- DOB NOW Safety: Boiler inspections — https://data.cityofnewyork.us/d/52dp-yji6
- DOB Boiler registrations (fuel) — https://data.cityofnewyork.us/d/f4rp-2kvy
- DCP PLUTO 26v2 — https://www.nyc.gov/site/planning/data-maps/open-data/dwn-pluto-mappluto.page
- NOAA GHCN-Daily, Central Park station USW00094728 — https://www.ncdc.noaa.gov/cdo-web/
- Open-Meteo historical weather + Previous Runs (archived forecasts) — https://open-meteo.com/
- NYC GeoSearch (address → BBL) — https://geosearch.planninglabs.nyc/

## Open-source libraries

[pandas](https://pandas.pydata.org/) · [NumPy](https://numpy.org/) ·
[scikit-learn](https://scikit-learn.org/) · [XGBoost](https://xgboost.ai/) ·
[Snap ML](https://www.zurich.ibm.com/snapml/) · [Flask](https://flask.palletsprojects.com/) ·
[Folium](https://python-visualization.github.io/folium/) · [data.table](https://rdatatable.gitlab.io/data.table/) (R EDA) ·
[Quarto](https://quarto.org/) · [Jupyter](https://jupyter.org/)

## Team

NYU Tingineers — IBM Z Datathon 2026. Prior art and what's new vs it:
[the project brief, §9](docs/heat-project-brief.md) (short version: building-level heat prediction exists;
a short-horizon, forecast-triggered, calibrated inspection ranking scored per fixed
inspection budget does not — that is the contribution).

### Team contributions

- **Sid — Backend engineering:** Built backend services, data APIs and real-time complaint-processing integrations.
- **Emerson — Predictive modeling:** Trained machine-learning models using building and weather data to estimate heat-failure risk.
- **Tin — IBM LinuxONE and interactive mapping:** Handled LinuxONE setup and benchmarking, developed the interactive risk map, and improved website functionality and usability.
- **Allen — Presentation design and editing:** Created the Google Slides presentation and edited the team’s presentation and demo materials.
- **Tanush — Frontend engineering and UI design:** Developed the website frontend and designed its interface, page layouts and user flows.
