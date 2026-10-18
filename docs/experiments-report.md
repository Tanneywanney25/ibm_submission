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
| **M11** spell-direct | train on the spell-level task itself (54 snapshots) | **89.9% @100 (+3.8)**, no depth regression | **adopted** for the per-spell queue |
| **M12** tuned day-model | first randomized HPO, validated on 2024-25 spells only | 89.2 / 65.2 / 51.8 / 34.8 — ≥ frozen at every k | **adopted** as the post-freeze config |
| **T12** dispatch simulator | replay the real 2025-26 complaint stream under 3 dispatch policies | same capacity: **+7.8% violations confirmed, cold-household-days −50.2%** vs FCFS | **the policy punchline** — prediction → dispatch, measured |

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

## T12 — the dispatch simulator (sim/run.py, sim/out/)

What a city buys by ranking with HeatAhead instead of first-come-first-served,
measured by replaying the **real** 2025-26 complaint stream (183,384 building-day
cases) day by day under a fixed inspection capacity.

**Grounding.** Outcome probabilities come from stream 2's measured 7-day
confirmation rates by 48h-cluster tier — never from our model (circularity
guard). Calibration is the validation: FCFS must reproduce reality, and it
does on **both** anchors — the season total (10,886 violations, matched
exactly) and the measured ~3.5-day busy-period congestion (capacity 700/day
gives FCFS mean wait 3.02d; the first calibration matched only the total,
left the system unloaded, and was redone). The outcome rescale k=1.30 means
P(violation | inspected) of 6.2/11.6/13.8% by tier — plausibly above the
unconditional 7-day rates, since not every complaint is inspected within 7
days. Violations are exact Poisson-binomial expectations (analytic CIs, no
Monte Carlo noise).

**Result (capacity 700/day, expiry 14d):**

| policy | violations confirmed | median wait | failing-case wait (mean, expiries=14d) | cold-household-days | expired (failing) |
|---|---|---|---|---|---|
| FCFS (status quo) | 10,886 | 2d | 3.12d | 13,780,436 | 0 (0) |
| last-season count | 11,522 | 0d | 2.10d | 7,052,143 | 23,742 (6,874) |
| **HeatAhead (M13)** | **11,730 ± 201** | **0d** | **2.03d** | **6,861,709** | 23,977 (**5,546**) |

Same inspectors, same winter: **+7.8% violations confirmed, failing buildings
reached in 2.0 vs 3.1 days, cold-household-days −50.2%**. The gap to FCFS
(+844) is far outside the ±201 CI. HeatAhead also beats the obvious smart
baseline (last-season counts) on every column — fewer failing cases abandoned
(5,546 vs 6,874) while confirming more.

**The honest trade-off.** Prioritization abandons ~24k uninspected cases
(mostly single-complaint, tier-1) that FCFS would eventually have reached;
5,546 of them are failing buildings. Their cold-days are charged in full
(units × 14d), so the −50.2% already pays that cost. The failing-case wait
metric counts every expiry as a 14-day wait — no survivorship bias.

**Sensitivity (capacity 600/700/800 × expiry 7/14/28, k fixed).** HeatAhead
beats FCFS in all 9 cells: violations +5.9% to +10.2%, cold-household-days
−27.6% to −65.1%. No ranking flips (`sim/out/sensitivity.csv`).

**Known limitation (reported, not hidden).** The sim holds P(violation |
inspected) constant in wait — it does not model the confirmation decay behind
stream 2's measured one-third yield drop on 4,000+ complaint days (heat comes
back before a late inspection). This simplification is **conservative**: decay
would penalize slow policies, so modeling it would only widen HeatAhead's
margin. The quoted numbers are therefore a floor.

## The rules that made these experiments safe

New model names (M7–M9) and catalog entries; frozen numbers untouched; same
evaluators via `--model`/`--label` flags so no experiment ever got a friendlier
test; features strictly pre-date the ranking moment; everything trained where
it runs (M9 on s390x — no cross-endian artifacts). Full specs per model:
`docs/model-catalog.md`. Adoption bars: `docs/tasks/T6-models-next.md`.

## Still untried (post-hackathon shelf)

Severity regression (expected cold households, T6c) · per-borough specialists
(T6d) · richer graphs (shared
boiler BINs, management companies across LLC shells) — the LLC-shell one is
the real research paper hiding in this repo.

Watchlist v2 with trajectory features (T6e) has since been run as M15, a
measured negative: 96.5% vs M4's 96.7% @1000 on 2025-26, not adopted (see the
catalog).
