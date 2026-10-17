# Task board — the build backlog

One MD per task; each has the goal, what already exists, contracts, steps and
acceptance boxes. Claim a task by putting your name here and check boxes in
your PRs. Roles doc: `docs/roles-endgame.md`.

| task | what | status | owner |
|---|---|---|---|
| [T1](T1-website-signup.md) | website core: signup + roles (tenant/landlord/gov/viewer) | done: live on Vercel, sign-ups stored on LinuxONE | Tanush |
| [T2](T2-risk-map-3d.md) | the risk map (3D hexagons / heat map, deck.gl) | spec + `/api/map_data` ready | — |
| [T3](T3-live-monitor.md) | live monitor on the realtime replay + real model swap | stub running (Sid) | — |
| [T4](T4-alerts.md) | forecast-triggered email alerts | specced, DB ready | — |
| [T5](T5-messaging-landlord.md) | landlord contact + drafted messages | T5a+b done: owner, managing agent and HPD link on every building page; tenant notice and landlord self-audit drafts (nothing sent); T5c roadmap | Tanush |
| [T6](T6-models-next.md) | further models (ranker, verified, severity…) | optional, rules inside | — |

Build order: **T1 → T3a ∥ T2 → T4 → T3b → T5a**. The submission needs T1–T3
working for the video; T4 strengthens it; T5/T6 are stretch.

Shared constraints (every task): building-level only · probabilities calibrated
and capped at 99% · no pickles across machines · change the Jupyter token before
opening instance ports · push early and often.
