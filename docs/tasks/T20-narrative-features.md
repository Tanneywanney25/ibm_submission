# T20 — M11: complaint narrative text as features

## Goal

The models see only counts and timing. The 311/HPD records carry free text
(problem descriptions, complaint types) that encodes *severity* counts miss —
"no heat 3 days, entire building" vs "lukewarm radiator". Embed the text,
compress it, and test whether a new model (M11) beats M4/M13 on the same
frozen evaluation. Also the home for the per-unit normalization experiment
(complaints-per-100-units), which may fix the mega-lot inflation T18
documents at the ranking level.

## Rules of the game

- **New model name (M11), new catalog entry.** The frozen numbers never move.
- **Time discipline**: only text from complaints dated before the row's
  season; aggregation at building level; apartment fields dropped at ingest,
  and no narrative fragment ever ships to the site (building-level only —
  free text can leak unit/tenant detail, so embeddings and aggregates only).
- Embeddings computed once, offline, on the training guest; cached as
  parquet/npz under `model/out/` (gitignored). No new pinned-library
  upgrades; pick a model that runs on what the guest has (or compute on a
  laptop and ship the *vectors*, which are not pickles — npz/parquet is fine
  cross-arch).

## Steps

1. Inventory what text we actually have in the raw extracts (311 descriptor/
   resolution fields, HPD problem `majorcategory`/`minorcategory`/`code`);
   many are categorical, not prose — count coverage per building-season.
2. Cheap baseline first: one-hot/frequency features of problem categories
   per building-season (no embeddings needed) → train M11a, evaluate with
   `03_evaluate.py`-style precision@k on 2025-26.
3. If prose exists at useful coverage: sentence embeddings, mean-pool per
   building-season, PCA to ~16 dims → M11b.
4. Add per-unit rate features (complaints/100 units, by weather band) → M11c.
5. Backtest the winner across all six winters (`05_backtest.py` pattern);
   write the comparison into `docs/model-iterations.md` as a new entry.

## Acceptance

- [x] Coverage table: how many building-seasons have usable text/categories.
      **No prose exists** in the extract (0 free-text fields); four
      categorical fields cover every complaint; 28–36k buildings per season
      have heat complaints, 10–14k have hot-water-only complaints, 50–69% of
      complaints carry a unit. `model/out/narrative_coverage.csv`.
- [x] Variants evaluated on the same universe, spells and k's as M13 (the 8
      held-out 2025-26 spells), 3 seeds each — **a wash** (table below).
- [x] Leakage suite extended (`test_narrative_features_use_only_prior_complaints`,
      synthetic, runs in CI); suite green 10/10.
- [x] Frozen numbers untouched; new entries only.

## Result (built 2026-10-18, run on the LinuxONE guest)

Renamed **M14**: "M11" was already taken (spell-direct) when this task was
written. `model/narrative.py` (feature builder) + `model/20_narrative.py`
(experiment). Step 3 (embeddings) was skipped: there is no prose to embed.

Same recipe for every variant (M11's config, early-stopped on the 2024-25
spells, refit, test once); mean of 3 seeds, spell precision@k:

| variant | features | val @100 | test @100 | @500 | @1000 | @2500 |
|---|---|---|---|---|---|---|
| control | the 31 | 87.8 | 89.0 | 64.8 | 51.1 | 34.9 |
| **M14a** | + 7 category/flag features | **88.7** | 89.0 | 65.0 | 51.1 | 35.0 |
| M14c | + 3 per-unit rates | 86.8 | 88.9 | 64.6 | 51.1 | 34.9 |
| M14ac | + both | 88.2 | 89.1 | 64.6 | 51.1 | 35.0 |

Validation picked M14a. On the held-out spells it ties the control: 4 wins,
4 losses @100, mean −0.1pp; seed spread (control 88.0–89.9) is larger than
any variant gap. Forward-chaining backtest (2 seeds, train ≤ T−1): M14a ahead
@100 in **5 of 6 winters** (+2.2, +0.8, +1.0, +0.8, +0.6; −0.2 in 2020-21)
and ≥ control @2500 in all 6, but by 0.1–0.5pp: a sign-test p ≈ 0.11, not
distinguishable from noise. **Verdict: not adopted.** Category text is
mostly already captured by `bw_last1`/`bw_prev14` (ENTIRE BUILDING) and the
complaint counts; per-unit normalization did not help the ranking either, so
the T18 mega-lot inflation needs a display fix, not a model fix.
