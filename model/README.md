# Model — workstream 5

P(heat failure | building, weather). Python/pandas so the same code runs on the laptop and LinuxONE. Follow `docs/model-plan.md` phase by phase:

0. Load and clean (cast `bbl` to int64 before every join)
1. Label: 2+ distinct complaints at a building within 48h; verified tier = heat violation within 7 days
2. Panel: positives + 2× sampled negatives
3. Features: prior-season history only — nothing from the row's own season
4. Train XGBoost, 2018-19 → 2024-25; test 2025-26 only; save with `save_model("heat_model.json")`, never pickle
5. Precision/recall@k (100/500/1000/2500) vs three baselines, scored on the full building universe
6. Snap ML import + events/sec and p99 latency on LinuxONE

Outputs land here: `heat_model.json`, `results_precision_at_k.csv`, per-building scores CSV.

## How to run

From the repo root (needs `data/` populated from the team Drive):

```
python model/01_build_panel.py      # phases 0-3 -> model/out/panel.csv (~5 min)
python model/02_train.py            # phase 4   -> model/out/heat_model.json
python model/03_evaluate.py [days]  # phase 5   -> model/out/results_precision_at_k.csv
python model/04_snapml_bench.py     # phase 6, LinuxONE only
```

`03_evaluate.py 10` scores only the 10 coldest test days (fast smoke run); no argument = every 2025-26 day with TMIN < 32. Uses XGBoost when installed (the LinuxONE container has it), else sklearn's HistGradientBoostingClassifier.

## First results (laptop, sklearn backend, all 71 cold days of 2025-26)

Universe: every building with any complaint/violation history (team decision; no-history
lots are unrankable by any method and are cut from training and scoring alike). Features
now include per-building reaction rates by weather band (frigid/freezing/cold), days
since last complaint/violation, and ENTIRE BUILDING (whole-building outage) counts.

Precision@k per TMIN<32 day of 2025-26, mean over 71 days. "48h" = failed within 48
hours; "30d" = failed within 30 days (the "should we get it checked" number):

| k | model 48h | model 30d | base 14-day 48h | base 14-day 30d |
|---|---|---|---|---|
| 100 | **0.674** | **0.963** | 0.617 | 0.910 |
| 500 | **0.417** | **0.861** | 0.393 | 0.803 |
| 1000 | **0.303** | **0.768** | 0.285 | 0.717 |
| 2500 | **0.178** (recall 0.651) | **0.607** | 0.169 (0.616) | 0.555 |

**Headline: 96.3% of the model's top-100 buildings go on to fail within 30 days.**
The model beats all three baselines at every k on both horizons. New-to-list cut
(model's top-100 picks the recency baseline missed): 60.2% fail within 48h, 96.5%
within 30 days — the failures recency cannot see coming.

## All-season rolling backtest (05, 10 coldest days per season)

Train strictly on earlier seasons, test on the full universe — model vs the 14-day baseline, precision@100:

| Test season | Model | 14-day baseline |
|---|---|---|
| 2020-21 | **0.571** | 0.551 |
| 2021-22 | **0.642** | 0.625 |
| 2022-23 | **0.633** | 0.600 |
| 2023-24 | **0.653** | 0.646 |
| 2024-25 | **0.714** | 0.685 |
| 2025-26 | 0.693 | 0.699 |

The model wins 5 of 6 seasons on their coldest days (and wins 2025-26 too once all 71 cold days count, not just the 10 coldest — see above). The edge holds at k=500/1000/2500 in every season. Full table: `model/out/backtest_by_season.csv`.

## LinuxONE run (Oct 17, real XGBoost 3.4.1 on s390x)

Confirmed on the instance (`uname -m` = s390x, `nnpa` present in /proc/cpuinfo, 3 cores):

- **Evaluation (71 cold days of 2025-26): model 65.7% precision@100 vs 61.8% for the 14-day baseline** — beats all three baselines at every k; recall 64.0% of all failures at k=2500. Matches the laptop run.
- Rolling backtest with XGBoost: model ahead at k=500/1000/2500 in all six seasons; at k=100 it wins 4 of 6 coldest-day sets.
- **Throughput (172,485 buildings × 22 features, measured):**

| engine | batch scoring | p99 single-row |
|---|---|---|
| XGBoost 3.4.1 | 351,610 buildings/sec | 0.33 ms |
| **Snap ML 1.17** | **487,293 buildings/sec (1.4×)** | 0.41 ms |

The entire city re-ranks in ~0.35 s on a 3-core guest. Snap ML was trained natively on the instance (XGBoost 3.x JSON lacks the objective field its importer wants). Honest caveat for the pitch: nnpa (the Telum accelerator) is present on the guest, but the gain shown is Snap ML's CPU tree engine; we don't claim accelerator offload.
