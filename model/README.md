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
