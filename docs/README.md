# Project documentation

Use this index to find the submission, technical reports and setup instructions.
For the application code and folder map, return to the [main README](../README.md).

## Understand the project

- [Submission story](SUBMISSION.md) — problem, approach, results and IBM Z contribution.
- [Project brief](heat-project-brief.md) — data inventory, design, constraints and prior work.
- [Complete model report](models-complete-report.md) — a plain-language explanation of the models, methods and scores.
- [Progress report](progress-report.md) — a recorded build checkpoint.
- [Presentation scripts](../slides/README.md) — scripts for the presentation and explainer.

## Models and evidence

- [Model catalog](model-catalog.md) — model names, purposes and artifacts.
- [Final model comparison](model-final-comparison.md) — model results side by side.
- [Model iterations](model-iterations.md) — experiments and decisions during development.
- [Model plan](model-plan.md) — the original phase-by-phase build plan.
- [Pipeline instructions](../model/README.md) — how to run the model scripts.
- [LinuxONE setup](../model/linuxone_setup.md) — environment setup for IBM Z.
- [IBM Z benchmark evidence](benchmarks/2026-10-18-emerson/README.md) — CPU and zDNN results, raw timings, hardware metadata and reproduction steps.
- [IBM integration plan](ibm_integration.txt) — proposed integration work; use the benchmark evidence above for measured results.
- [Analysis handoff](../analysis/README.md) and [stream 2 report](../task%202/deliverables/02_stream2_report.md) — supporting analysis.

## Website and services

- [Deployment guide](VERCEL.md) — Vercel architecture, data paths and required checks.
- [Website specification](webapp-spec.md) — page behavior and display rules.
- [Site guide](SITE_GUIDE.md) — help chat, question matching and legacy FAQ links.
- [Google login](GOOGLE_LOGIN.md) — credentials, remembered sessions, account storage and deployment checks.
- [Assistant service](ASSISTANT.md) — assistant behavior and integration.
- [Newsletter, contact and privacy](NEWSLETTER_CONTACT_PRIVACY.md) — signup, contact and privacy features.
- [Real-time model integration](../realtime/README_MODEL.md) and [recovery checkpoints](../realtime/README_CHECKPOINTS.md) — replay service operation.

## Working on the project

- [Project rules](../CLAUDE.md) — read before making changes.
- [Task board](tasks/README.md) — individual build cards.
- [Team split](team-split.md) and [endgame roles](roles-endgame.md) — workstream ownership and handoffs.
- [Engineering log](engineering-log.md) — implementation notes.

## Data location (not in git)

Data files are too big for GitHub (complaints alone is 345 MB). Download from the team Drive folder (`Data_IBMZ`) and place them at `data/` in the repo root. The folder is gitignored.

The website's precomputed assets in [`public/data/`](../public/data/) are tracked
and ship with the Vercel deployment. See the [deployment guide](VERCEL.md) for the
difference between these public assets and the private training data.
