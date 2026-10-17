# T11 — Robustness audit: attack our own model three ways

**Goal:** the pre-emptive red team. Spatial generalization, temporal drift,
and an automated leakage test suite — so "did you stress it?" is answered with
tables, and no future edit can silently break the time discipline.

## 11a — Leave-one-borough-out CV

Train on four boroughs, test on the fifth (borough = bbl // 1e9), five folds,
M1 recipe, spell-level p@k on each held-out borough's buildings (2025-26
spells). Report per borough vs the all-borough model restricted to that
borough. Question answered: does the model learn heat physics + behavior, or
memorize Bronx geography? Expect some drop in Staten Island (thin data) — say
so. ~2h via a loop over 02/07 with a borough mask.

## 11b — Feature & label drift

Per feature, PSI between each train season and 2025-26 (universe rows at the
first spell of each season); flag PSI > 0.2. Separately quantify the known
2023 enforcement shift (violations per complaint by season) and the label-rate
drift. One table + three sentences in experiments-report.md: which features
moved, why the model survives them (within-season percentile features, the
seasonal clock). ~1.5h, pandas only.

## 11c — The leakage test suite (pytest)

Codify every time rule as tests that run anywhere:
- a 2025 panel row's `c_last1` equals its recomputed 2024 count (existing
  assert, promoted to a test over a sample)
- no feature column correlates with the SAME-day label via future info:
  rebuild 50 random rows with data truncated at day-1 and diff
- `currentstatus`/`problem_status_date` never appear in any FEATS or loader
- trailing windows end at d-1 (recompute vs stored for sampled rows)
- universe rule: every scored bbl has history before the scoring day
`tests/test_leakage.py`; `python -m pytest tests/ -q` green becomes part of
the README reproduce block. ~1.5h.

## Deliverables

- `model/19_borough_cv.py` → `model/out/borough_cv.csv`
- `model/20_drift.py` → `model/out/drift_psi.csv`
- `tests/test_leakage.py` + README line
- "Robustness" section in docs/experiments-report.md with all three tables

## Acceptance

- [ ] 5 borough folds reported, gaps explained, no silent failures
- [ ] PSI table complete; >0.2 features each get one explaining sentence
- [ ] pytest suite green locally AND in the instance container
- [ ] Frozen numbers untouched

**Effort ~4-5h total; 11c first (it protects everything else).**
