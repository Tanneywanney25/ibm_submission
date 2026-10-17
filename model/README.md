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

## First results (laptop, sklearn backend, 10 coldest 2025-26 days)

Full-universe precision@k (all 172,485 buildings ranked per day):

| k | model | 14-day baseline | last-season baseline |
|---|---|---|---|
| 100 | 0.697 | 0.699 | 0.515 |
| 500 | 0.515 | 0.515 | 0.372 |
| 2500 | **0.276** | 0.269 | 0.205 |

Headline ties the strongest (recency) baseline — expected, 70% of chronic buildings stay chronic. The pitch number is the **new-to-list cut**: among the model's top-100 picks that the 14-day baseline *missed*, **64.8% still failed** — those are the failures recency cannot see coming (precision 0.648/0.368/0.161 at k=100/500/2500).
