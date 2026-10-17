# CLAUDE.md: project rules for every Claude session in this repo

This is HeatAhead, team NYU Tingineers at the IBM Z Datathon (October 17-18, 2026): predict
which New York City buildings lose heat in a coming cold snap and rank them for inspection.
Everything heavy runs on the team's IBM z17 LinuxONE guest; the public site runs on Vercel.
Read `README.md` for the story and `docs/README.md` for the document map.

## Before you change anything, read the owning doc

| if the prompt touches | read first |
|---|---|
| `web/`, `api/`, `public/`, `realtime/`, `vercel.json`, `requirements.txt`, `.vercelignore`, the site at https://ibmsubmission.vercel.app | `docs/VERCEL.md` (the deployment contract; follow sections 3 and 6 to the letter) |
| `model/` | `model/README.md`, `docs/model-iterations.md` (the frozen numbers; new models get new names) |
| `task 2/` | `task 2/README.md` |
| the tasks on the board | `docs/tasks/README.md` and the task's own MD |
| slides, video, submission | `slides/presentation-script.md`, `docs/SUBMISSION.md` |

## Rules that never bend

- Building-level only. No apartment numbers anywhere: not in code, tables, tooltips,
  screenshots or prose. The raw HPD file has them; nothing derived from it ships them.
- Data stays out of git: `data/`, `model/out/`, zips, pickles and databases are ignored and
  must stay that way. The only data that ships is `public/data/` for the site (see VERCEL.md).
- Identifiers `bbl`, `bin`, `building_id` are int64 before every join. HPD tables join to each
  other on `building_id`; `bbl` only attaches PLUTO; `bin` only attaches boiler tables.
- Time discipline: training features use only data dated before the row's season; the
  2025-26 winter is the untouched holdout; `currentstatus` and `problem_status_date` are
  never features.
- The submission numbers are frozen (69.1 / 86.1 / 96.6 / 99 at k=100, 6 of 6 winters,
  481,356 buildings per second on Snap ML). Experiments get new model names and their own
  catalog entries; they never overwrite these.
- Probabilities shown to users are calibrated, capped at 99%, banded above 20%.
- Never pickle a model on one machine and load it on another (x86 vs s390x); JSON model
  files only. Never let pip upgrade numpy, pandas, scikit-learn or xgboost on the instance.
- Secrets (SMTP, tokens, keys, the Jupyter token) never enter the repo or a chat log.

## Git

- `git pull --rebase origin main` before every commit; push to `main`; no force pushes;
  one commit per working change with a message that says what changed and why.
- A push to `main` deploys the public site. Do not leave `main` in a state where the Vercel
  deploy fails; use a branch for risky UI work (Vercel gives it a preview URL).
- Commit messages and PR bodies end with the attribution line the session supplies.

## The LinuxONE guest

`linux1@148.100.77.112` (s390x, machine type 9175, 3 cores, 8 GB, account expires
2026-11-15, no backups). Non-interactive SSH shells do not activate the venv: call
`~/datathon-env/bin/python` explicitly. The Stream 2 pipeline lives in `~/heatahead/stream2/`,
a clone of this repo with the Stream 5 pipeline run in `~/heatahead/ibm_submission/`, and the
site's backend runs from a third clone, `~/heatahead/site/`, as systemd services
(`heatahead-web` on port 8080, `heatahead-realtime`, `heatahead-jupyter`; see
`docs/VERCEL.md` section 8).
Change the Jupyter token before opening any port. Push results to GitHub as soon as they exist.

## How to work

Do the work, verify it ran (tests, curl, a screenshot), and report what was verified and what
was not. When a prompt would change a shared contract (URL paths, feature list, frozen
numbers, deploy layout), say so and update the owning doc in the same commit.
