# Endgame roles — five people, final stretch

Where everything stands after the overnight push, and who owns what until
submission. Old roles (team-split.md) are retired: streams 1, 2 and 5 are DONE.
Every remaining point in the rubric is demo, video, story or submission hygiene.

## What's in the repo right now (survey, latest pull)

- **Model (stream 5) — complete and frozen.** M1–M6 + baselines in
  `docs/model-catalog.md`; final ladder 69.1 / 86.1 / 96.6 / 99 @100; 6-of-6
  forward-chaining CV; calibrated per-building winter risk
  (`model/out/season_risk_2026.csv`). Full doc set shipped (SUBMISSION,
  iterations, catalog, engineering log, webapp spec, two scripts, README).
- **Stream 1 (analysis) — complete.** Weather bands, era/size/alteration
  heatmaps, cold-sensitivity tables in `analysis/analysis_outputs/`; final
  notebook committed.
- **Stream 2 — complete, plus a bonus.** Tanush's full report (label
  credibility 1.87×, inspector saturation, Bronx geography, Forecast-Only
  group) AND an ablation (`task 2/deliverables/ablation/`) independently
  re-running the model with feature variants on the guest — it confirms the
  frozen feature set: no variant beats V0. That's a third-party-style check of
  stream 5, slide-worthy.
- **Stream 6 (realtime) — started.** `realtime/app.py` replays Feb 7–9 with stub
  scores (merged via PR #1). Model swap + measurement still to do.
- **Not started / not visible in the repo:** the live map + tenant lookup
  frontend, the video, the deck, the Hack2skill submission itself.

## The five roles

### 1. Demo engineer — realtime + instance (suggested: Sid)
Owns the +3 live-demo bonus and the Real-Time track qualification.
- [ ] Swap `realtime/app.py` stub scoring for M2 (`heat_model_final.json`;
      load via XGBoost, never pickle) + preloaded static features
- [ ] Measure per-event p50/p99 and events/sec over the full replay; record
      beside `uname -m` + nnpa (the numbers go verbatim into the video)
- [ ] **Change the Jupyter token BEFORE opening any port** (default token is
      public); open Flask port via iptables, persist to `/etc/iptables/rules.v4`
- [ ] Keep the instance alive: snapshot state, push logs — guests have hung

### 2. Frontend — map + tenant lookup (suggested: Allen)
Owns presentation row's visual half. Spec is written: `docs/webapp-spec.md`.
- [ ] Folium/Leaflet map from `model/out/ranked_inspection_list.csv`
      (two sorts: p_calibrated, tenants_at_risk); poll `/queue` during replay
- [ ] Tenant lookup: address → GeoSearch → BBL → `season_risk_2026.csv`
      ("N% chance this winter") + complaint/violation history per season
- [ ] The trust expander: `season_reliability.csv` as "how accurate is this?"
- [ ] Building-level only; probabilities capped at 99%; bands above 20%

### 3. Video producer (suggested: stream-1 owner, now free)
Owns the 3-minute video — it MUST show the instance and the model.
- [ ] Shoot list from `slides/presentation-script.md` (timed beats): s390x +
      nnpa terminal, replay ticker, map re-sorting, tenant lookup, the ladder
- [ ] Record narration from the script (or explainer-script.md for one voice)
- [ ] Cut to <3:00 with a 10-second buffer; captions for the numbers
- [ ] B-roll fallback if the live demo slips: pre-rendered queue screenshots
      (the cut line in stream6-realtime.md)

### 4. Slides + submission owner (suggested: Tanush — his report is half the deck)
Owns storytelling (10 pts) + reproducibility (5) + repo bonus (2).
- [ ] **FIRST, TODAY: confirm the deadline on Hack2skill/Discord** (readings
      differ ~10.5h) and post it in the team chat pinned
- [ ] Deck in the order of `slides/presentation-script.md` §slide order; every
      number from `docs/SUBMISSION.md` §9's file index
- [ ] Team number `[ONLXXX]` into README + project title; roster per Sid's
      six-member answer
- [ ] Submit on Hack2skill with a 2-hour buffer; checklist at the bottom of
      presentation-script.md

### 5. Integrator + QA (suggested: Emerson)
The floating fixer role, now pointed at consistency and glue.
- [ ] Wire handoffs: model files → realtime (M2 + calibration curve),
      → frontend (ranked list, season risk, reliability)
- [ ] Number-consistency sweep: docs vs slides vs video captions all say
      69.1 / 86.1 / 96.6 / 99, 6-of-6, 481k/sec — one wrong digit on a slide
      beats ten in a CSV
- [ ] Dry-run the reproduce commands in README top-to-bottom on the instance
- [ ] Watch teammates' blockers; own the git tree (rebase conflicts, no force
      pushes, data stays out)

## Sync points

1. **Now:** deadline confirmed and pinned (role 4) — blocks scheduling everything
2. **Demo freeze:** map + replay working end to end on the public IP → video
   shooting starts (roles 1+2 → 3)
3. **T-4h before deadline:** content freeze — only video upload and submission
   fields after this
4. **T-2h:** submitted. Nothing lands on main after submission.

## Cut lines (in order, if slipping)

1. Tenant lookup → static screenshot of one building page in video/deck
2. Live map polling → pre-rendered before/after queue screenshots
3. Email alerts → spec slide only (it's fully written in webapp-spec.md)
4. Whole realtime stream → submit Wildcard; the batch model + map stand alone
