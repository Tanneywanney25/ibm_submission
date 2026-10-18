# Task board — the build backlog

One MD per task; each has the goal, what already exists, contracts, steps and
acceptance boxes. Claim a task by putting your name here and check boxes in
your PRs. Roles doc: `docs/roles-endgame.md`.

| task | what | status | owner |
|---|---|---|---|
| [T1](T1-website-signup.md) | website core: signup + roles (tenant/landlord/gov/viewer) | done: live on Vercel, sign-ups stored on LinuxONE | Tanush |
| [T2](T2-risk-map-3d.md) | the risk map (3D hexagons / heat map, deck.gl) | spec + `/api/map_data` ready | — |
| [T3](T3-live-monitor.md) | live monitor on the realtime replay + real model swap | stub running (Sid) | — |
| [T4](T4-alerts.md) | forecast-triggered email alerts | done: real sends from the instance, welcome email, dedupe, cron | Emerson |
| [T5](T5-messaging-landlord.md) | landlord contact + drafted messages | T5a+b done: owner, managing agent and HPD link on every building page; tenant notice and landlord self-audit drafts (nothing sent); T5c roadmap | Tanush |
| [T6](T6-models-next.md) | further models (ranker, verified, severity…) | done: M7/M8/M9 run on the guest — see docs/experiments-report.md | Emerson |
| [T7](T7-statistical-inference.md) | error bars + significance on every number (cluster bootstrap, paired permutation) | done: daily edge p<1e-5 every k/horizon, spell edge exact p=1/256 (won all 8 spells), all calibration bins inside Wilson CIs | Emerson |
| [T8](T8-conformal-alerts.md) | conformal risk control: alerts with a provable guarantee | done: guarantee held on the test winter (α=0.10 → 7.4% missed, α=0.25 → 21.1%); alerts.py reads the json, falls back when absent | Emerson |
| [T9](T9-shap-explanations.md) | SHAP per building + "why this number" on the site | new | — |
| [T10](T10-time-to-failure.md) | M10 discrete-time hazard: predict WHEN, survival curves | done (honest misses recorded): C-index 0.871; M10b horizon recalibration cuts the S(t) overshoot 8–42pp → ≤4.7pp at Jan/Feb (Dec 1 top decile +8.0pp remains), week error 11.1→10.0w — not shipped, holdout spent | Emerson |
| [T11](T11-robustness-audit.md) | leave-one-borough-out CV, drift PSI, pytest leakage suite | 11c done: 10 leakage tests green (T20 added one) (caught and fixed an eval-clobber bug); 11a/11b open | Emerson (11c) |
| [T12](T12-policy-simulator.md) | inspector dispatch simulator: violations caught and cold-days averted per policy | done: calibrated to the real total AND lag; +7.8% violations, cold-days −50.2% vs FCFS, ranking stable across 9-cell sensitivity grid — see docs/experiments-report.md | Emerson |
| [T13](T13-ui-overhaul.md) | UI overhaul to the Opendoor standard (reskin, features frozen) | new | — |
| [T14](T14-account-platform.md) | clean sign-in/profile; roles → customizable dashboard panels | code done: one account type, email + Google sign-in with inline validation, profile with panel toggles (`/api/account/panels`), role-free "Save a building", four dashboard panels; Google project, client, instance key and restart done Oct 18; live once the two Secret values are in Vercel Production and it redeploys; email links wait for SMTP on the instance (T14 doc, Status); visual polish rides on T13 | Emerson |
| [T15](T15-live-data.md) | live polling: NYC Open Data complaints/violations/buildings + weather | new | — |
| [T16](T16-info-methods.md) | public About/Methods section: models, bootstrap ranges, open source | copy drafted (docs/about-copy.md, numbers from frozen docs); build + open-source sign-off open | Emerson (copy) |
| [T17](T17-address-search.md) | address search with autocomplete, map-free path to building pages | built: GeoSearch autocomplete in nav + landing + building page, `/map?bbl=` focus, embedded map panel | Emerson |
| [T18](T18-location-accuracy.md) | location accuracy: mega-lot pins + centroid audit (the "park pin" report is Stuy Town's lot centroid, not a geocode bug) | new, investigated | — |
| [T19](T19-ask-heatahead.md) | Ask HeatAhead: LLM chat over our data replaces the complaints feed (tool-calling, grounded, guardrailed) | new | — |
| [T20](T20-narrative-features.md) | M14 (renamed; M11 was taken): complaint category text as features + per-unit rates | done, not adopted: no prose exists; category features tie the control on the held-out spells (89.0 vs 89.0 @100, 4-4 per spell), ahead in 5 of 6 backtest winters by ≤2pp (p≈0.11) — a wash; leakage test added | Emerson |
| [T21](T21-fairness-audit.md) | fairness & equity audit: precision/calibration by borough, CD, income band | new | — |
| [T22](T22-telum-nnpa.md) | real Telum/NNPA offload via zDLC: earn the accelerator claim (distilled MLP benchmark) | new | — |
Build order: T1–T6 are landed or owned; the rigor sprint runs **T11c (leakage
tests) → T7 → T9 ∥ T12 → T8 → T10**. The submission needs T1–T3 for the video;
T7–T12 are the technical-rigor push.

Shared constraints (every task): building-level only · probabilities calibrated
and capped at 99% · no pickles across machines · change the Jupyter token before
opening instance ports · push early and often · frozen numbers never change —
new work gets new names and its own catalog entries.
