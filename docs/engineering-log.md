# Engineering log — model stream + infrastructure, Oct 16–18, 2026

The chronological record of what was actually done, found, broken and fixed while
building HeatAhead's model stream and shared infrastructure. Companion to
`SUBMISSION.md` (the story) and `model-iterations.md` (the model arc). Useful for
reproducibility points, for the video's "how we worked" beat, and for anyone who
joins the repo cold.

## Phase 0 — data verification (Oct 16, pre-event planning only)

- Profiled all five source files: complaints 2.22M rows (Jul 2017 – Oct 14, 2026,
  zero bad dates), violations usable from 2012 (pre-2010 rows are data-entry noise
  back to 1968), PLUTO 172,485 lots, weather complete with no missing days.
- Confirmed the brief's traps live: BBLs parse as floats and silently break joins;
  `TAVG` 100% NaN; `yearbuilt` 1900 is a dump value; `currentstatus` is leakage.
- Join coverage measured: 92% of heat-complaint rows match a PLUTO lot; the
  unmatched are mostly 1–2-unit homes outside the 3+ universe (median 1 complaint).
- Identified the data gap: no hourly temperatures and no archived forecasts.
  Pulled both from Open-Meteo (hourly 2017→, Previous-Runs 24/48h forecasts
  2021→). Verified: hourly agrees with the NOAA station within 2–3°F; archived
  48h forecasts have 2.2°F MAE (2.6°F on freezing days) and flagged 118 of 123
  freezing days. Found the 24h forecast oddly *worse* than the 48h (3.0 vs 2.2°F).
- Cold-spell inventory: 54 spells of 2+ freezing days across 9 seasons; 41 in the
  training window, 8 in the 2025-26 holdout.
- Baseline reality-check (pre-model): "complaints in prior 14 days" already gets
  ~57–62% precision@100 — set as the bar before any model existed.

## Phase 1 — repo and environment (Oct 17)

- Repo: `ibm_submission` on GitHub; one folder per workstream; `data/` gitignored
  (345 MB complaints file exceeds GitHub's 100 MB limit); the two master tables
  (`days.csv`, `buildings.csv`) committed so a clone works without Drive.
- LinuxONE guest verified: **s390x, `nnpa` present, 3 cores, 7.8 GB** (event code
  granted more than the documented 4 GB). Docker was absent → installed, pulled
  IBM's JupyterLab s390x container (pandas 3.0.6 / sklearn 1.9.0 / XGBoost 3.4.1).
- Data to the instance as one tar.gz (420 MB → 78 MB, minutes instead of an hour).
- All pipeline runs on the instance are logged (`pipeline*.log`), launched by one
  idempotent `run_pipeline.sh`.

## Phase 2 — the pipeline (model/00–09)

Built per `docs/model-plan.md`, phases 0–6, then extended: second-tier prep (00),
panel (01), train (02), daily eval (03), Snap ML bench (04), 6-winter backtest
(05), final scores (06), spell eval + autopsy (07), season risk (09).
Design rules enforced in code: distinct `complaint_id` only; every feature dated
strictly before the ranking moment; an assert compares each 2025 row's history to
its recomputed 2024 count and crashes on mismatch; models cross machines only as
XGBoost JSON (never pickle — big-endian s390x).

## Phase 3 — results arc (held-out 2025-26, precision@100)

| round | change | exact 48h | notes |
|---|---|---|---|
| baseline | rank by 14-day complaints | 61.7% | the bar |
| 1 | plan-spec features | 65.7% | tied baseline on coldest days |
| 2 | band reaction rates, days-since, history cut | 67.8% | backtest 6/6 first time |
| 3 | whole-building outages; added 30-day horizon | 67.7% | 30d @100 = 96.3% |
| 4 | landlords, boilers, ensemble, calibration | 68.7% | honest probabilities |
| 5 | velocity, neighbor block, season clock | **69.1%** | days_into_cold → top-4 feature |

Then the horizon work: per-spell 86.1%, 30-day 96.6%, preseason-winter 99% @100 /
95.4% @1000. Autopsy: 1–7 truly-clean picks per top-100. 6-fold forward-chaining
CV: 6/6 winters, mean 0.673 vs 0.634. Season-level per-building risk (09) verified
bin-by-bin (89% predicted → 89.8% actual) and written for 2026-27.

## Bugs hit and fixed (so nobody re-hits them)

1. **`merge_asof: right keys must be sorted`** — cumsum table was sorted by
   (bbl, day); asof with `by=` needs global sort on the `on` key. Sort by day last.
2. **Snap ML can't import XGBoost 3.x JSON** ("no objective defined") → train
   Snap ML natively on the panel instead; throughput numbers still measured.
3. **Snap ML asserts on NaN** (`left_num == left_fill_idx` deep in its tree
   builder) → `np.nan_to_num(..., nan=-1)` before fit/predict.
4. **In-sample calibration looked perfect** (every bin exact) — because the
   isotonic was fit on the same pairs. Refit on disjoint halves; later, collect
   calibration pairs from the full universe in 03 (panel pairs have a sampled base
   rate ~70% vs real 1.2% and would inflate displayed probabilities).
5. **`band_prep` groupby crash** — merging a `days` frame into a `bd` that already
   had a `season` column created `season_x/_y`. Select only needed columns before
   merging.
6. **Panel-vs-R-pipeline drift** — 02 referenced a `weight` column only the old R
   panel had. Removed.
7. **Group-type error in R** (`median` int vs double by group) and data.table's
   full-table printing in notebooks (`invisible()`); `uniqueN` per group was 30×
   slower than unique-then-count.
8. **PowerShell vs everything**: multi-line python `-c` is unquotable (write a
   file), `&&` doesn't exist in 5.1, remote bash goes through a scp'd script with
   `sed -i 's/\r$//'` for CRLF. Curly quotes from a slipped autocorrect broke one
   f-string.
9. **Force-push protection**: when main had to be rewound (pre-window commit
   concern), local reset worked but the force push required a human-run
   `--force-with-lease` — by design.
10. **Concurrent teammates**: three push rejections resolved with
    `git pull --rebase`; one `.Rproj`/README collision resolved by keeping the
    teammate's version.

## Decisions made (and why)

- **BBL-level, not building-level**: 97.8% of complaint BBLs have one building;
  PLUTO (the attribute source) has no HPD building id.
- **History-only universe** (67,125 of 172,485): the 6,425 positives in
  no-history buildings are invisible to *every* ranker; cut from train and test
  alike (team call). Stated as a limitation; the Heat Sensors Program complements.
- **Trailing-window features allowed** (ending day-1): the plan banned same-season
  features, but without them the model loses to the recency baseline it must beat.
  Leak-free by construction.
- **Report 48h AND spell AND 30d AND season**: one list, four clocks; the strict
  number builds trust in the big ones.
- **Cap displayed probabilities at 99%**; rank by raw score within calibration
  plateaus; never display below building level.
- **Model freeze** after iteration 5 — every number reported is from a single
  final run, no post-hoc tuning.

## Still open / watchpoints

- Hack2skill deadline still unverified (two readings ~10.5h apart) — highest-risk
  open item in the project.
- Team number `[ONLXXX]` placeholder in README + project title.
- Jupyter in the container listens on 38888 with the default token; unreachable
  until iptables opens it — **change the token first** (stream 3).
- `09_season_risk` instance run: launched; local numbers already recorded.
- Instance survival: push often; `pipeline*.log` + `model/out/*` are the artifacts
  to save if the guest hangs.
