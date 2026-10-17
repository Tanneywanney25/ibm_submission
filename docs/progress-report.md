# HeatAhead — progress report (October 17, 2026, ~20h before submission)

One page on everything the team has built, verified and frozen so far.
Each line traces to an owning doc, a script, or a CSV; nothing here is aspirational.

## The product (live)

- **Public site**: https://ibmsubmission.vercel.app — Flask in LITE mode on Vercel,
  FULL mode on the LinuxONE guest (`heatahead-web` systemd service, port 8080).
  Deploy contract in `docs/VERCEL.md`; a push to `main` deploys.
- **Design**: building-architecture design language (skyline hero, building-elevation
  risk card, skyline history bars, silhouette footer) per `docs/design-language.md`,
  implemented site-wide with features unchanged.
- **Real email alerts (T4)**: registration welcome email + forecast-driven cold-snap
  alerts from `web/alerts.py`, hourly cron on the instance via Gmail SMTP
  (secrets in `/home/linux1/heatahead.env`, never in the repo). Thresholds:
  p_season ≥ 0.35 or p_calibrated ≥ 0.20; dedupe via `alerts_sent`; unsubscribe links.
- **Model swap into the replay service (T3a)** done by Sid; **landlord contacts (T5)**
  by Tanush; model/out bundle shared (`model_out_share.tar.gz`).

## The model stream (closed and frozen)

- **Frozen submission numbers (M1)**: precision@100 **69.1** (48h) / **86.1** (spell) /
  **96.6** (30d) / **99** (season); forward-chaining backtest wins **6 of 6 winters**;
  Snap ML scores **481,356 buildings/second** on the z17. These never change.
- **M13, the final per-spell scorer (frozen)**: spell-level target + 12-trial HPO
  (validation-winter selected) + 5-seed bag → **90.1 / 65.4 / 51.4 / 35.2** on the 8
  held-out 2025-26 spells, test touched exactly once. Artifacts:
  `final_spell_ensemble.json` + 5 member JSONs. Full ledger: `docs/model-catalog.md`
  (M1–M13, B1–B3), leaderboard and headroom analysis: `docs/model-final-comparison.md`.
- **Honest rejections**: XGBRanker (M7), GraphSAGE on the landlord/block graph (M9) —
  both built, evaluated under the identical protocol, and beaten by target design.
- **Other jobs**: M4 calibrated season risk (the tenant-facing number, capped 99%,
  banded ≥20%); M8 verified-violation enforcement queue (30.2 @100 vs 16.5 baseline).

## Statistical rigor (T7, T11c)

- Bootstrap 95% CIs on every headline (B=2000), plus a 16-block consecutive-day
  bootstrap to respect within-cold-snap correlation — conclusions hold under both.
- Paired permutation tests: model vs baseline p ≈ 1e-5 daily; exact per-spell sign
  test 7/8 wins, p = 0.0078. Calibration verified bin-by-bin inside Wilson intervals.
- **Leakage test suite**: 9 pytest tests (`tests/test_leakage.py`) — banned-column
  scan of model code, trailing windows end at d−1, universe rules, no apartment
  numbers in anything shipped — green throughout.
- Evaluators take `--model/--label` and write **suffixed** result files, after an
  experiment run was caught overwriting canonical CSVs (fixed, canon restored).

## T12 — the inspector dispatch simulator (in verification now)

`sim/run.py` replays the real 2025-26 complaint stream (183,384 building-day cases)
under a fixed inspection capacity, three policies: FCFS / last-season / HeatAhead
(frozen M13 spell scores). Outcome rates come from stream 2's measured confirmation
rates — never our model (circularity guard); violations are exact Poisson-binomial
expectations. Calibration IS the validation: FCFS must reproduce reality — both the
season total (10,886 violations, matched exactly) and the measured ~3.5-day busy-period
lag (matched at capacity 700/day after the first run failed this test and was redone).
Current recalibrated result, pending the final checks (saturation shape, expiry-window
and capacity sensitivity, honest reporting of the expired-case trade-off):
**same 700 inspections/day → +7.8% confirmed violations, median wait 2→0 days,
cold-household-days −50.2%**.

## Infrastructure

- Everything heavy runs on the IBM z17 LinuxONE guest (s390x, 3 cores, 8 GB):
  full pipeline `model/01–24`, Snap ML benchmark, GraphSAGE in pure torch, the
  simulator. JSON-only model exchange (big-endian discipline); pinned numpy/pandas/
  xgboost. Three clones on the guest: stream2, ibm_submission (pipeline), site (services).
- Repo hygiene: data and model outputs gitignored; only `public/data/` ships.

## Task board (docs/tasks/README.md)

Done: T1 site, T3a model swap, T4 alerts, T5 contacts, T6 graph-ML comparison,
T7 statistical inference, T11c leakage suite. In flight: T12 (final verification).
Open if time allows: T8 conformal alerts, T9 SHAP via `pred_contribs`, T10 hazard
timing, T11a borough CV, T11b drift/PSI. Slides done (`slides/presentation-script.md`).

## What is left before submission

1. Close T12: sensitivity grid + saturation-shape check, write results into
   `docs/experiments-report.md`, mark the board.
2. Team items: deadline confirmation on Hack2skill, team number in README/title, video.
