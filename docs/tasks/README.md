# Task board â€” the build backlog

One MD per task; each has the goal, what already exists, contracts, steps and
acceptance boxes. Claim a task by putting your name here and check boxes in
your PRs. Roles doc: `docs/roles-endgame.md`.

| task | what | status | owner |
|---|---|---|---|
| [T1](T1-website-signup.md) | website core: signup + roles (tenant/landlord/gov/viewer) | done: live on Vercel, sign-ups stored on LinuxONE | Tanush |
| [T2](T2-risk-map-3d.md) | the risk map (3D hexagons / heat map, deck.gl) | spec + `/api/map_data` ready | â€” |
| [T3](T3-live-monitor.md) | live monitor on the realtime replay + real model swap | stub running (Sid) | â€” |
| [T4](T4-alerts.md) | forecast-triggered email alerts | specced, DB ready | â€” |
| [T5](T5-messaging-landlord.md) | landlord contact + drafted messages | stretch â€” T5a/b only if time | â€” |
| [T6](T6-models-next.md) | further models (ranker, verified, severityâ€¦) | optional, rules inside | â€” |

Build order: **T1 â†’ T3a âˆ¥ T2 â†’ T4 â†’ T3b â†’ T5a**. The submission needs T1â€“T3
working for the video; T4 strengthens it; T5/T6 are stretch.

Shared constraints (every task): building-level only Â· probabilities calibrated
and capped at 99% Â· no pickles across machines Â· change the Jupyter token before
opening instance ports Â· push early and often.
