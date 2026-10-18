# T6 — Further models to train (only if T1–T4 are staffed and moving)

The core model is frozen (M1–M6, see docs/model-catalog.md) and its numbers are
final for the submission. These are the next models worth training, in value
order, each with the exact recipe so any of us can run one on the instance.

## T6a — Ranking objective (1–2 hrs, instance only)

Train `xgboost.XGBRanker(objective="rank:pairwise")` on the panel, grouped by
`(event day)` — it optimizes top-of-list directly, which is our metric.
- qid = dense rank of `panel.day`; same FEATS; same train/test split
- Evaluate through `07_spell_eval.py` by saving as `heat_model.json` alongside
  the classifier and comparing spell p@100 — keep whichever wins, but **report
  stays frozen** unless it beats 86.1 by ≥1pp on BOTH spell and 30d
- Pitfall: XGBRanker has no predict_proba; use raw margins for ranking only
  (calibration M3 still maps margins → probabilities if adopted)

## T6b — Violation-within-7-days model (the "verified failure" ranker)

Same panel, target `y_verified` instead of `y_cluster` (9.6% of positives).
Gives a second queue: "most likely to produce a VERIFIED violation" — directly
useful for HPD enforcement, and Tanush's confirmation analysis (1.87× lift)
becomes its validation story. Recipe: change the target in 02, rerun 03 with
`verified_precision` as the headline column. ~1 hr.

## T6c — Spell-duration / severity model

For buildings that fail, predict complaint volume in the spell
(`n_48h` regression or Poisson) → lets the queue sort by expected cold
households, not just probability × units. Feeds the "tenants at risk" view
with something smarter than multiplication. ~2 hrs.

## T6d — Borough / district-specialized models

Six per-borough models vs the citywide one. Hypothesis from stream 2's
geography: Bronx dynamics differ. Verdict matters even if negative ("one
citywide model suffices — tested"). ~1 hr via a loop over `05_backtest.py`'s
machinery filtering the panel by `bbl // 1e9`.

## T6e — Next-winter watchlist v2 (season model + trajectory)

M4 (season risk) + slope features: complaints season-over-season delta,
age of last violation, landlord-portfolio trend. Target: beat M4's 95.4%
@1000 preseason. Recipe: add 3 features to `09_season_risk.py`'s SFEATS. ~1 hr.

**Done (M15, `model/27_watchlist_v2.py`): measured negative, not adopted.**
Held-out 2025-26 @1000 for "fails this winter": M15 96.5% vs M4 96.7%
(M4's own Oct-1 number; the 95.4 above is M1 ranked at the first cold spell).
Forward-chaining: 2 of 5 winters won, gaps at most 0.7pp. Details are in
`docs/model-catalog.md` under M15.

## Rules that still bind every experiment

- The frozen submission numbers never change; new models get NEW names
  (M7, M8…) and their own catalog entries
- Features strictly pre-date the prediction moment; test winter untouched for
  training; forward-chaining CV before any claim; calibrate before display
- Train on the instance (3 cores — budget ~10 min/panel fit), JSON artifacts only

## Not worth the hours (so nobody burns time)

- Deep learning / TabNet on 760k tabular rows — no evidence it beats GBMs here
- Hyperparameter sweeps — one depth/lr try max; feature work beats tuning
- Graph models over landlord networks — great post-hackathon paper, not a
  tonight thing
