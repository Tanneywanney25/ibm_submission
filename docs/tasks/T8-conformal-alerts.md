# T8 — Conformal risk control: alerts with a provable guarantee

**Goal:** replace the hand-picked alert threshold with one carrying a
distribution-free guarantee, then verify the guarantee held on the test
winter. The alert email's quality line becomes a theorem: "this threshold
bounds the missed-failure rate at α, by construction."

## Method (conformal risk control; pure numpy)

1. **Choose the risk to control** (team decision via this doc; recommended:
   false negative rate among alerted-eligible buildings): FNR = share of
   buildings that fail within the spell whose score fell below the threshold.
2. **Calibrate:** split the pre-test cold days chronologically (e.g. seasons
   2021-2024 full-universe day scores — regenerate per-day scores with
   `05_backtest.py`-style scoring or reuse saved `scores_coldest_day`-type
   dumps; a new flag in 03 to dump per-day (score, y) pairs for chosen seasons
   is the clean path). Pick the smallest threshold λ whose empirical risk on
   calibration days satisfies the conformal bound
   `(n/(n+1))·R̂(λ) + B/(n+1) ≤ α` (B=1 for bounded loss), per
   Angelopoulos et al. conformal risk control.
3. **Verify on 2025-26:** compute realized FNR across the 71 held-out days;
   report realized vs guaranteed α; also report the induced alert volume
   (buildings alerted per cold day) at that λ.
4. Do it for two αs (e.g. 0.10 and 0.25) → a "strict" and a "broad" alert tier.

## Deliverables

- `model/16_conformal.py` → `model/out/conformal_thresholds.json`
  (α, λ, calibration n, realized test risk, mean alert volume)
- `web/alerts.py` reads the json when present (threshold swap, copy line:
  "this alert level is calibrated to miss fewer than α of failures")
- Short method note appended to `docs/experiments-report.md`

## Acceptance

- [ ] Guarantee computed on calibration days that strictly pre-date 2025-26
- [ ] Realized test FNR ≤ α for both tiers (or the miss honestly reported)
- [ ] Alert volume per tier stated (the operational cost of the guarantee)
- [ ] alerts.py falls back to current thresholds when the json is absent

**Effort ~3-4h. Depends on:** per-day score dumps (small 03 extension), T7 helps
but not required. **Feeds:** T4 alerts, deck ("provable guarantees").
