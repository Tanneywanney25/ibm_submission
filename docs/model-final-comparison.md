# Final model comparison — is M11 better than our XGBoost?

Short answer: **M11 IS XGBoost.** Same algorithm, same 31 features, same data —
the only change is *what it is trained to predict*: M1 learns day-level 48-hour
labels on the panel; M11 learns the spell-level task itself on the 54
full-universe spell snapshots. The +3-point jump came from **target design,
not a new algorithm** — which is the cleanest lesson of the whole model stream:
after five feature rounds and four alternative architectures, the biggest
late gain came from aligning the training objective with the evaluated task.

## The leaderboard (8 held-out 2025-26 spells, precision@k, identical protocol)

| model | what it is | @100 | @500 | @1000 | @2500 | verdict |
|---|---|---|---|---|---|---|
| **M13 FINAL (frozen)** | 5-seed bag of the spell-HPO winner (blend chose pure bag, w=1.0) | **90.1** | **65.4** | 51.4 | **35.2** | **the shipped per-spell scorer; model stream closed** |
| M11 spell-direct | XGBoost on spell snapshots, hand config | 89.9 (seeds: 88.0–89.9) | 64.8 | 51.3 | 34.9 | superseded by M13 |
| **M12 tuned day-model** | XGBoost, first HPO (val-winter selected) | 89.2 | **65.2** | **51.8** | 34.8 | best day-level config |
| M1 (frozen submission) | XGBoost+sklearn ensemble, day labels | 86.1 | 64.6 | 51.4 | 34.8 | the cited numbers; unchanged |
| M7 ranker | XGBRanker rank:pairwise | 87.9 | 64.6 | 50.7 | 33.7 | top-heavy; rejected |
| M9 GraphSAGE | GNN on landlord/block graph (s390x PyTorch) | 84.9 | 63.0 | 49.4 | 33.8 | rejected |
| base_14d | rank by last-14-day complaints | 77.1 | 59.9 | 47.8 | 31.9 | the bar |

Related but different jobs: M8 (verified-violation queue, 30.2 @100 on
violation truth — 2× best baseline), M4 (season risk, the tenant number,
calibration verified bin-by-bin), M10 (hazard/timing — unbuilt, T10).

## Why we trust the M11/M12 result (model/23, ceiling_verification.csv)

- **Seed stability:** three independent retrains: 88.0 / 89.2 / 89.9 @100 —
  every seed clears the frozen 86.1. Quote "~88–90%", not the best draw.
- **Per-spell consistency:** M11 beats M1 in **7 of 8 spells** (exact paired
  p = 0.0078), the one loss by a single building on the mildest spell; +12pp
  on the season's last spell. M12 independently also wins 7/8 — so this is
  not a lucky winner among two finalists.
- **Protocol:** validation winter (2024-25) did all selection and early
  stopping; the test spells were touched once per finalist. Leakage suite
  (tests/test_leakage.py) green throughout.

## Can we still improve? Honest headroom assessment

What the evidence says about the remaining ceiling at spell p@100:

- The mild Feb 12 spell caps everyone (~0.75–0.79 for every model) — few
  buildings genuinely fail in weak cold; that is label scarcity, not model
  error. The Jan 23 monster spell is already at 0.99. Realistic ceiling with
  this label: roughly **92–94% @100**; we are at ~89–90.
- **Worth doing (the final squeeze, ~1 hour on the guest, one script):**
  1. **Seed-bag M11** — average 5 seeds' probabilities. Kills the 2pp seed
     wobble and typically buys a few tenths. Near-free.
  2. **Small HPO on M11 itself** — M11 ran on a hand config; 10–15 trials
     selected on the validation winter, same discipline as M12's search.
  3. **Blend M11 + M12** (simple score average or rank-average, weight picked
     on the validation winter) — their errors differ (M11 wins tops, M12 wins
     depth), so a blend plausibly takes both columns.
  Expected combined gain: **+0.5 to +1.5pp @100**; anything more would be
  chasing the label-noise floor.
- **Not worth more hours:** new architectures (M7/M9 settled that), more
  graph work, deep nets, more external data (landlord/boiler/litigation
  already in or marginal). The curve has flattened everywhere except target
  design, and that card is now played.

## M13 — the final squeeze result (model/24; MODELS NOW FROZEN)

The last hour of model work, every choice made on the validation winter and
the test spells evaluated exactly once: a 12-trial HPO on the spell task
(winner: depth 7, lr 0.03, 61 trees, heavier regularization), the winner
bagged across 5 seeds for stability, then a coarse blend grid with M12 —
which chose the pure bag (M12 added nothing on top). **Test: 90.1 / 65.4 /
51.4 / 35.2 — improvement or tie at every k, +4.0 at the top.** Recipe is one
reproducible artifact (`final_spell_ensemble.json` + five member JSONs).
The remaining gap to the ~93% label-noise ceiling is the mild-spell floor;
the squeeze delivered the predicted +0.5–1.5 and the stream is closed.

## Rules unchanged

The frozen submission numbers (69.1 / 86.1 / 96.6 / 99, 6 of 6 winters,
481,356 buildings/sec) stay exactly as cited. M11/M12 are catalog entries and
deck one-liners ("our latest spell-level model reaches ~89%"), and every
claim above traces to a CSV in model/out/ or a script in model/.
