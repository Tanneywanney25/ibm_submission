# HeatAhead research assistant

This adds generative public-data research to `/monitor`. It does not change the
frozen building models, published evaluation numbers, map assets, registrations,
emails, or complaint collector. `/monitor?mode=current` preserves the published
complaint monitor; `/monitor?mode=replay` preserves historical model replay.
The assistant footer links to both.

## Execution and endpoints

- FreeLLMAPI gateway: `127.0.0.1:3001`, external model inference, private dashboard.
- `python -m assistant.service`: waitress `127.0.0.1:5002`. A single background
  worker runs bounded model/tool loops; up to three queued/running jobs.
- The existing LinuxONE web service exposes the same-origin proxy on 8080.
- Vercel renders the template and forwards short job requests only. It never
  imports pandas, numpy, XGBoost, or the `assistant` backend package.
- `POST /api/assistant/jobs {question}` -> 202 with opaque random job id.
- `GET /api/assistant/jobs/<id>` -> queued/running/completed/failed; expires in 1h.
- `GET /api/assistant/health` -> configuration flags; no secrets or provider calls.
- Browser polling every 1.8s. Jobs can run up to five model calls and eight local
  tools (maximum two web searches); each individual HTTP proxy call is short.
  A complex research question can take several minutes. Provider limits still apply.

Gateway build verified on Sid's s390x machine, Node 22.23.3, native SQLite and
Sharp. Dashboard static assets were built from gateway commit
3a9ee5d8c58666fb60648949b53e345b0150593d on x86; the dashboard's Lightning CSS
compiler cannot load a native s390x binary. The static files are portable.

## Data and answers

Approved data: `model/out/building_day_counts.csv`, `data/buildings.csv`, and the
read-only current collector SQLite. It does not crawl server directories or
read account/registration/SMTP/SSH files. General public questions use Tavily.
The gateway interprets requests and explains tool results. Tools calculate daily
trends, equal-length period comparisons, borough totals, top buildings, building
complaint history, and experimental count forecasts. They do not execute model-
generated SQL, Python, shell commands, or use generated URLs to fetch local files.
Charts are validated numeric tool results, rendered with native SVG and accessible
data tables; no new chart CDN or scientific dependency is required on Vercel.
Web-only answers need not have a quantitative chart. Arbitrary queries may be
unsupported, lack evidence, or exceed the bounded research/quota budget.

History is restricted to the building universe in `data/buildings.csv` for
consistency across historical/live counts, so these are NOT all-NYC counts.
Problem rows deduplicate by complaint id. Live overlapping calendar days REPLACE
historical counts; they are never added. Ambiguous BBLs, unknown buildings and
future records are excluded. Complete coverage is not inferred from absence of
complaints: forecast inputs conservatively exclude the latest received-date
source day and at least the most recent one/two local dates. A watermark is not
a guarantee of completeness. Source cutoff, latest received record, scope and
last successful poll are shown with each answer. Late source changes beyond the
collector overlap/reconciliation windows may still be missing.

No forecast is emitted if the history gap is over seven days or target horizon
plus gap exceeds fourteen days. Missing recent dates are not filled with zero.
The historical building-day extract is assumed to cover its intervening dates;
the collector's successful window coverage is checked before extending it.

## Count forecasting, distinct from building risk

The forecast predicts received heat-complaint counts for tomorrow onward, not
boiler failures, confirmed outages or already-known complaints. It has no weather
covariates yet, no October building-risk calibration, no current risk probabilities.

Candidates: last-week weekday count, four-week weekday mean, eight-week weekday
mean with recent volume trend. Candidate choice uses 45 earlier rolling origins;
the following 90 origins calibrate scaled absolute-error intervals. The final
30 origins report retrospective development MAE, baseline MAE and per-horizon
coverage. Outcome windows finish before the next partition starts. The development
backtest is not untouched independent validation or a frozen submission result.

Intervals target 80% marginal coverage; actual historical coverage is printed.
If it falls below 70% the quality is `experimental_low_coverage`. No live coverage
guarantee, causal inference or accuracy headline is made. Overlapping windows are
correlated; do not sum daily bounds to manufacture a joint three-day interval.
Freezing weather can change counts sharply; a weather-aware model requires its
own archived-forecast evaluation. See `count_forecast_validation.json` for the
dated development run, which did NOT have access to the live collector database.

## Configuration and quota controls

On Sid `.43`, `~/.config/heatahead/assistant.env` (0600):

```
TAVILY_API_KEY=<private>
LLM_BASE_URL=http://127.0.0.1:3001/v1
LLM_API_KEY=<FreeLLMAPI unified key, NOT the provider key>
LLM_MODEL=openai/gpt-oss-20b
ASSISTANT_PROXY_SECRET=<generated by installer; same secret on Vercel>
```

Provider keys remain in FreeLLMAPI's encrypted SQLite; its encryption key is in
`~/.config/heatahead/freellmapi.env`, separate from HeatAhead source. In Vercel
Production set ONLY `ASSISTANT_URL=http://148.100.78.43:8080/api/assistant` and
`ASSISTANT_PROXY_SECRET` to the matching secret. No LLM/Tavily key goes to Vercel
or the browser. The `.43` web service must load the same signing secret (installer
uses a separate systemd drop-in and preserves its existing service file).

Request/reply HMACs protect integrity, requests expire after 60s, backend nonces
reject replays. The existing HTTP 8080 transport does NOT provide confidentiality;
use HTTPS/private encrypted transport before supporting private questions/data.
Until then public building-level questions only. The model and search terms and
selected public data summaries go to external providers. Their retention/terms
apply. This is NOT on-chip LLM inference; `accelerator_used` is false.

Global durable admission budgets: 3 jobs/minute and 100/day; 12 model requests/
minute and 400/day; 6 search requests/minute, 100/day and 900/month. Local search
result cache lasts one hour. These are application limits, not promises of free
provider capacity or provider billing caps. Keep upstream accounts on free plans.
If quotas fail the page shows a clear failure; it never silently upgrades plans.

Job questions are stored temporarily in `data/assistant/jobs.sqlite3`, removed
when a job completes; job results expire after one hour (expired rows are removed
at the next admission). Failed/restarted job questions are cleared on restart.
Application logs do not print questions, model responses, API keys, or upstream
error bodies. Providers/gateway may have their own logs. Do not enable gateway
request-content logging for personal information.

## Install and review

Run `~/jupyter-env/bin/python install_assistant.py --root ~/ibm_submission` from
the unpacked package directory. It stages the current site's web/public files,
applies narrow hooks (no whole-app replacement), runs fixture/proxy tests, backs
up changed files in ignored `data/before-assistant-*`, and writes only source.
Model/history/registration files and existing collectors remain untouched.

Run `python -m assistant.check` inside the project for dated input/forecast checks.
`--providers` is an explicit opt-in that consumes one model request and one basic
search credit; it prints only status flags/counts, never credentials.

`install_assistant.py --root ~/ibm_submission --install-services` additionally
installs the private gateway and research systemd units and the web environment
drop-in, with previous unit backups. First stop the manually launched gateway
using Ctrl+C. It does not open any new firewall ports. Review generated units
under `data/assistant-service-units`.

To test before publishing: create a local-only SSH tunnel to 8080 and open
`/monitor`; verify real model responses, source citations, charts, data cutoff,
forecast coverage and graceful offline/quota handling. Then commit only the
listed source changes on a branch, merge after checks, configure Vercel's two
variables, and redeploy the existing project. Do not commit archives, data, keys,
SQLite, model outputs or generated systemd units. It is not deployed by this file.

Rollback: stop `heatahead-assistant`; restore only the backed-up source paths
from the installation's backup directory; remove the new web environment drop-in
if needed, daemon-reload and restart web. The published-complaint collector is
independent. The gateway unit can be stopped separately.
