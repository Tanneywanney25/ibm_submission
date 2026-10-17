# T15 — live data: poll NYC Open Data and the weather, continuously

## Goal

The site should run on *fresh* reality, not a frozen extract: poll NYC Open
Data for the newest 311 heat complaints, HPD violations and building updates,
and the weather/forecast feed, on a schedule — so risk scores, building pages
and alerts reflect this week, not download day.

## Sources (all free, no keys in the repo)

- 311 complaints: Socrata `erm2-nwe9`, filter heat/hot-water, incremental on
  `created_date` (app token via env file only if throttled).
- HPD violations: Socrata `wvxf-dwi5`, incremental on `inspectiondate`.
- PLUTO/building updates: quarterly — refresh on a slow cadence (monthly check).
- Weather: Open-Meteo forecast + observations (already used by `web/alerts.py`).

## What already exists

- `web/alerts.py` polls the forecast hourly via cron on the instance.
- `model/out/building_day_counts.csv` and the feature pipeline consume the
  static extracts in `data/` (gitignored).
- FULL mode serves from the instance; LITE serves `public/data/` snapshots.

## Contracts

- **Time discipline is untouched**: new data feeds *scoring* (today's features
  for today's ranking) — training, the frozen numbers and the 2025-26 holdout
  never change. No retraining in this task.
- Data stays out of git; incremental pulls land under `data/live/` on the
  instance only. The only shipped data remains `public/data/` (VERCEL.md).
- int64 `bbl`/`bin`/`building_id` before every join; building-level only —
  the 311 pull drops apartment fields at ingest.
- Never let pip upgrade pinned libraries on the instance.

## Steps

1. `etl/poll_nyc.py`: incremental Socrata pulls with a high-water-mark file,
   dedupe, append to `data/live/`; log counts per run.
2. Recompute the *scoring* feature rows for changed buildings; rescore with
   frozen M13/M4; write the site's tables the FULL app reads.
3. Cron on the instance (same env-file pattern as alerts): complaints hourly,
   violations daily, PLUTO monthly check.
4. A small freshness stamp in the site footer/API ("complaints as of …").
5. Regenerate `public/data/` snapshots for LITE on each daily run and push —
   only if the diff is sane (row-count guardrail).

## Acceptance

- [ ] Two consecutive cron runs ingest only new rows (idempotent, high-water).
- [ ] Building page shows a complaint filed after the original extract.
- [ ] Freshness stamp visible; scores change only via frozen-model rescoring.
- [ ] Leakage suite still green; no new data enters git except `public/data/`.
