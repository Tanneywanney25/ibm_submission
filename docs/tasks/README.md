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
| [T7](T7-statistical-inference.md) | error bars + significance on every number (cluster bootstrap, paired permutation) | new | — |
| [T8](T8-conformal-alerts.md) | conformal risk control: alerts with a provable guarantee | new | — |
| [T9](T9-shap-explanations.md) | SHAP per building + "why this number" on the site | new | — |
| [T10](T10-time-to-failure.md) | M10 discrete-time hazard: predict WHEN, survival curves | new (first to drop) | — |
| [T11](T11-robustness-audit.md) | leave-one-borough-out CV, drift PSI, pytest leakage suite | new | — |
| [T12](T12-policy-simulator.md) | inspector dispatch simulator: violations caught and cold-days averted per policy | new | — |

Build order: T1–T6 are landed or owned; the rigor sprint runs **T11c (leakage
tests) → T7 → T9 ∥ T12 → T8 → T10**. The submission needs T1–T3 for the video;
T7–T12 are the technical-rigor push with ~20 hours left.

Shared constraints (every task): building-level only · probabilities calibrated
and capped at 99% · no pickles across machines · change the Jupyter token before
opening instance ports · push early and often · frozen numbers never change —
new work gets new names and its own catalog entries.
