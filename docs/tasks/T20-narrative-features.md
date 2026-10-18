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

- [ ] Coverage table: how many building-seasons have usable text/categories.
- [ ] M11 variants evaluated on the same universe, days and k's as M4/M13;
      the table says plainly whether text helps, hurts, or is a wash.
- [ ] Leakage suite extended with one test asserting narrative features use
      only prior-season complaints; suite green.
- [ ] Frozen numbers untouched; new entries only.
