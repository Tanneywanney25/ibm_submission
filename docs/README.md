# Project docs

Planning documents for the build. Start with the brief.

- `heat-project-brief.md` — the full project brief: idea, data inventory, label/feature/model design, LinuxONE constraints, pitch numbers, prior art
- `team-split.md` — who owns which workstream, sync points, shared traps
- `model-plan.md` — phase-by-phase plan for the model workstream (stream 5)
- `progress-report.md` — one-page status of everything built, verified and frozen so far
- `VERCEL.md` — how the public site deploys to Vercel and the rules every web/realtime change must follow (the root `CLAUDE.md` points every Claude session here)
- `GOOGLE_LOGIN.md` — Google credentials, remembered sessions, durable account storage, and coordinated deployment checks
- `ibm_integration.txt` — the IBM Z plan, highest points per hour first: s390x proof, Snap ML on CPU vs the Telum II accelerator, real-time replay, on-chip compression and encryption, Granite briefs, a "Why IBM Z" README section
- `SITE_GUIDE.md` — chat help, question browsing, typo suggestions and the retired FAQ redirect

## Data location (not in git)

Data files are too big for GitHub (complaints alone is 345 MB). Download from the team Drive folder (`Data_IBMZ`) and place them at `data/` in the repo root. The folder is gitignored.
