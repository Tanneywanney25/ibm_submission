# T7 — Statistical inference suite: every number gets error bars

**Goal:** upgrade every headline from a point estimate to an estimate with
uncertainty and a significance test. After T7, the table reads
`69.1% [66.8, 71.4]` and "beats the baseline, p < 0.001, paired over 71 days."

## Method (all pure numpy/pandas; no new deps)

1. **Cluster bootstrap** for CIs. Days inside a spell are correlated, so
   resample at the right unit: for daily metrics, bootstrap the 71 days with
   replacement (B=2,000) recomputing mean precision@k each draw; for spell
   metrics, bootstrap the 8 spells (report percentile 95% CIs; 8 units is few —
   say so, also give the per-spell min/max). For the season/backtest table,
   bootstrap winters is meaningless (n=6) — report per-winter values only.
2. **Paired permutation test** model vs base_14d: per day d, the difference
   `delta_d = prec_model(d) - prec_base(d)`; randomly flip signs of deltas
   100,000 times; p = share of |mean| ≥ observed. Do per k, for 48h and 30d.
   Same for the spell table over 8 spells (exact 2^8 enumeration — do all 256).
3. **Calibration CIs:** Wilson intervals on each reliability bin
   (both daily and season tables).
4. **M8 and new-to-list** get the same treatment.

## Inputs (all exist)

`model/out/results_precision_at_k.csv` (per-day rows), `spell_results.csv`
(per-spell rows), `season_reliability.csv`, `calibration.csv`. No model re-runs
needed — this is post-processing of saved per-day/per-spell results.

## Deliverables

- `model/15_inference.py` → `model/out/stats_inference.csv`
  (metric, k, horizon, estimate, ci_lo, ci_hi, p_vs_base, n_units, B)
- A 10-line "Statistical notes" section appended to `docs/model-iterations.md`
  (what was resampled, why cluster bootstrap, the n=8 caveat)
- The headline ladder restated with CIs for the deck owner

## Acceptance

- [ ] CIs for every cell of the daily (71-day) and spell (8-spell) tables
- [ ] Paired p-values model-vs-base_14d at every k, both horizons
- [ ] Wilson CIs on all calibration bins
- [ ] Sanity: bootstrap mean within 0.2pp of the frozen point estimate
- [ ] Frozen numbers unchanged — CIs annotate them, never replace them

**Effort ~3h. Depends on:** saved eval CSVs (done). **Feeds:** deck, SUBMISSION.md, T8.
