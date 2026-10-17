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

Full-universe precision@k (all 172,485 buildings ranked per TMIN<32 day), mean over days:

| k | model | 14-day baseline | last-season baseline | violations baseline |
|---|---|---|---|---|
| 100 | **0.658** | 0.618 | 0.433 | 0.149 |
| 500 | **0.406** | 0.392 | 0.271 | 0.092 |
| 1000 | **0.294** | 0.286 | 0.198 | 0.084 |
| 2500 | **0.176** (recall 0.639) | 0.169 (0.612) | 0.126 | 0.062 |

The model beats all three baselines at every k. On only the 10 coldest days it ties the 14-day baseline (everyone chronic is already complaining); the edge comes from ordinary freezing days, where recency is a weaker signal. **New-to-list cut:** among the model's top-100 picks the 14-day baseline missed, **56.3% still failed** — the failures recency cannot see coming.

Numbers to beat on LinuxONE with real XGBoost. Next feature to try: per-building reaction rates by weather band (stream 1 handoff).

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
