# The experiments report — everything we tried beyond the headline model

T6 + the graph experiment, consolidated: four alternative models, trained and
scored under the **identical frozen protocol** (same 8 held-out 2025-26 spells /
71 cold days, same universe, same k's). The submission numbers never moved —
that's the rule — but every "did you try X?" question now has a measured answer.

The frozen reference (M1 ensemble): **86.1 / 64.6 / 51.4 / 34.8** spell-level
precision@100/500/1000/2500.

## Scoreboard

| experiment | what | headline result | verdict |
|---|---|---|---|
| **M7** ranking objective | XGBRanker `rank:pairwise`, grouped by day | spell p@100 **87.9 (+1.8)**, but k=1000 **−0.7**, k=2500 **−1.1** | **not adopted** — sharper top-100, worse at HPD's real scale, uncalibrated margins |
| **M8** enforcement ranker | same recipe, target = verified violation ≤7d | **30.2% @100 vs 16.5%** best baseline (2×); 48% confirmed ≤30d | **kept as a second product** — the enforcement queue beside the tenant queue |
| **M9** GraphSAGE | 2-layer GNN over landlord/block hub graph, **trained on LinuxONE (s390x PyTorch)** | 84.9 / 63.0 / 49.4 / 33.8 — **1–2pp below M1 at every k** | **not adopted** — M1 already carries the graph as explicit features |
| earlier: perfect-forecast check | observed temps vs archived 48h forecasts | 48h forecast ≈ 2.2°F MAE; detection 118/123 freezing days | forecast-driven design validated |

## What each one taught us (the Q&A ammunition)

- **"Why not learning-to-rank?"** We ran it. It wins the very top of the list
  (one spell's top-100 went 100/100 at 30 days) and pays below k=100. Since the
  city inspects thousands, not hundreds, we kept the classifier.
  (`model/11_ranker.py`, 07 with `--model`)
- **"Why not deep learning / GNNs?"** We trained a GraphSAGE **on the mainframe
  itself** — landlord hubs, block hubs, 54 spell snapshots, honest time
  discipline — and it came in 1–2 points under the GBM everywhere. The reason
  is instructive: the graph's two useful relations (landlord portfolios, block
  contagion) were already hand-built into M1 as `lord_c_other_last1` and
  `nb_block_2d`; message passing could only smooth them.
  (`model/13/14`, `model/out/graph/m9_results.csv`)
- **"Aren't verified-violation rates low?"** They're capped by inspection
  throughput, not predictability: even known failures get confirmed within 7
  days only 9–12% of the time (stream 2's saturation proof). Against that
  ceiling, M8's 30-in-100 confirmed (48 by day 30) is ~2× today's best
  targeting and ~43× random. Low absolute, high lift — and the gap *is* the
  case for prioritization. (`model/12`, 03 with `--label verified`)
- **"Is the model just recency?"** The whole catalog says no: beats the 14-day
  baseline at every k on every horizon, wins all 6 backtest winters, and its
  new-to-list picks (the ones recency misses) still fail at 96% within 30 days.

## The rules that made these experiments safe

New model names (M7–M9) and catalog entries; frozen numbers untouched; same
evaluators via `--model`/`--label` flags so no experiment ever got a friendlier
test; features strictly pre-date the ranking moment; everything trained where
it runs (M9 on s390x — no cross-endian artifacts). Full specs per model:
`docs/model-catalog.md`. Adoption bars: `docs/tasks/T6-models-next.md`.

## Still untried (post-hackathon shelf)

Severity regression (expected cold households, T6c) · per-borough specialists
(T6d) · watchlist v2 with trajectory features (T6e) · richer graphs (shared
boiler BINs, management companies across LLC shells) — the LLC-shell one is
the real research paper hiding in this repo.
