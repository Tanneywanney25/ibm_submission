# Task 2: analysis, second thread (Workstream 2)

Owner: Tanush Bhatia (Person 3). Everything here was executed on the team's IBM z17 LinuxONE guest (`148.100.77.112`, s390x, machine type 9175, 3 virtual cores, 8 GB) under `~/heatahead/stream2/` on October 17, 2026.

Start with `deliverables/02_stream2_report.md`. It is written so Stream 4 can lift numbers straight into the slides and the video, and every number in it is also in `deliverables/numbers_*.json`.

## What is in here

| path | contents |
|---|---|
| `deliverables/02_stream2_report.md` | the report: label credibility, Bronx Community Districts 7/4/5 and citywide geography, the Forecast-Only building group, the boiler and fuel join on BIN, the IBM z17 hardware execution log |
| `deliverables/*.csv`, `deliverables/*.png`, `deliverables/z17_hardware_log.*` | the four deliverable table sets, the three charts and the hardware log (see the table at the end of the report) |
| `code/02_stream2_analysis.ipynb` | the executed notebook (run on the server with `nbconvert`) that reproduces every table and figure |
| `code/s2_common.py` | shared rules: int64 keys, heat-only filter, the six logging-gap dates, the season clock, the TMIN bands, size and era buckets |
| `code/s2_00_stage_protect.py` | stages the raw tables on the z17, pseudonymizes apartment numbers with HMAC-SHA256, writes zlib (DFLTCC) compressed and AES-256-GCM (CPACF) encrypted extracts, and benchmarks each operation hardware on vs off |
| `code/s2_01_clean.py` | enforces the team traps and the Person 3 join rules, builds the working tables and the building universe |
| `code/s2_02_violation_tier.py` | Deliverable 1: 48-hour cluster tiers against verified heat violations, inspector saturation by day |
| `code/s2_03_geography.py` | Deliverable 2: Community District and Council District tables with centroids and bounds |
| `code/s2_04_forecast_only.py` | Deliverable 3: Chronic vs Forecast-Only groups, 2025-26 holdout, February 7 to 9 2026, archived forecast cross-check, Stream 5 handoff |
| `code/s2_05_boiler_join.py` | Deliverable 4: DOB boiler inspections (`52dp-yji6`) and DEP boiler fuel (`f4rp-2kvy`) joined on BIN, leak-free features and lift |
| `code/pull_open_data.sh` | pulls the five Open Data tables onto the server with `curl` in `$limit=50000` pages |
| `code/run_all.sh` | runs the six steps in order and executes the notebook |
| `code/make_bundle.py` | zips the deliverables on the server (never raw/ or work/) |
| `../model/08_stream2_ablation.py` | the ablation that tests the Stream 2 features inside Stream 5's pipeline without touching its schema (five variants, 71 test cold days); verdicts in `docs/model-iterations.md`, Iteration 5 |
| `deliverables/ablation/` | the ablation tables (per day, per k, per variant, paired per-day deltas, XGBoost gains), the baseline `03_evaluate.py` results from this guest, and `bbl_boiler_by_season.csv`, the leak-free (bbl, season) boiler table that replaces the all-time snapshot |
| `code/boiler_by_season.py` | builds `bbl_boiler_by_season.csv` from the DOB and DEP tables with a per-season October 1 cutoff |

## The ablation in one paragraph

Merging the two Stream 2 CSVs into the model panel would have been wrong twice over: their training-window columns are fixed to 2018-19 through 2024-25, so a 2019 panel row would see 2020-2025 complaints, and aggregating building-level rates to the tax lot with a max under-states the lot-level rate by a third on the 2,022 shared lots. So the same quantities were re-derived at the lot level inside Stream 5's pipeline with an expanding window of prior seasons, and the boiler columns were recomputed from reports dated before October 1 of each season. Measured on the 71 test cold days with the committed ensemble: the leak-free boiler swap costs nothing (precision@100 69.2% against 69.4%, paired t = -0.3) and is adopted; the richer boiler set is worse (-0.86 points, t = -2.5); the long-window reaction rates and group flags add nothing at any k; all five variants sit within one point of each other. The Forecast-Only group is a long tail for the map and the tenant lookup, not a top-100 feature.

## How to reproduce on the LinuxONE server

```
ssh -i datathon.pem linux1@148.100.77.112
mkdir -p ~/heatahead/stream2/raw && cd ~/heatahead/stream2
# copy the code/ files here, then put in raw/: ygpa-z7cr.csv.gz, wvxf-dwi5.csv.gz, days.csv, buildings.csv,
# noaa_daily_centralpark.csv, weather_archived_forecast_features_2024_onward.csv (all from the team Drive)
./pull_open_data.sh      # DOB boiler, DEP fuel, HPD registrations, HPD Buildings (Active), PLUTO all lots
./run_all.sh             # about 10 minutes on the 3-core guest
```

The raw data are not in git (the complaint file alone is 361 MB); they live in the team Drive `Raw/` folder. The two 32-byte keys that `s2_00_stage_protect.py` generates in `work/` never leave the server, and the raw apartment column exists only in `raw/`.

## Rules every script follows

- `building_id`, `bbl` and `bin` are cast to int64 after stripping decimal strings; HPD tables join to each other on `building_id` only; `bbl` is used only to attach PLUTO (all 858,284 lots, so 1-2 unit homes count); `bin` is used only for the boiler tables.
- Heat only: `problem_code` in `NO HEAT`, `NO HEAT AND NO HOT WATER`; distinct `complaint_id` per `building_id`, never rows; the duplicate and anonymous flags are kept and reported.
- The six Christmas-week logging-gap dates are dropped; violations before 2010-01-01 are dropped; heat orders 666/966/674 are separated from hot-water orders 670/970.
- Training features use heat seasons 2018-19 through 2024-25 and nothing dated on or after 2025-10-01; 2025-26 is the untouched holdout; `currentstatus` and `problem_status_date` are never loaded.
- Nothing below building level is ever shown; apartment identifiers are replaced by keyed hashes in step 0.

## Open-source libraries used

pandas 2.1.4, numpy 1.26.4, matplotlib 3.6.3, cryptography 41.0.7 (OpenSSL 3.0.13), zlib 1.3 with the IBM DFLTCC patch (Ubuntu 24.04 s390x), nbconvert 6.5.3, curl, GNU coreutils.
