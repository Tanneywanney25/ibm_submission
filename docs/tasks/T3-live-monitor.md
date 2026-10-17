# T3 — Live monitoring page (on Sid's realtime service)

**Goal:** the Real-Time track proof, visible: complaints stream in (Feb 7–9
replay), each affected building re-scores, the inspector queue re-sorts live,
with the latency ticker on screen.

## What exists

- `realtime/app.py` (Sid): replay loop + `GET /queue?k=`, `GET /stats`,
  `POST /replay/start {speedup}` — **stub scoring** (`scoring_mode:
  "temporary_demo_priority"`), clearly labeled
- `web/app.py` already proxies it same-origin: `/api/live/queue`,
  `/api/live/stats`, `/api/live/replay/start` (503 JSON when the service is down)
- `data/replay_feb7_9.csv` needs extracting once (one-liner in
  docs/stream6-realtime.md §Extracting)

## The two jobs

### 3a. Real model into the loop (owner: Sid)
Replace the stub `scores[bbl] = ...` with M2:
```python
from xgboost import XGBClassifier
m = XGBClassifier(); m.load_model("model/out/heat_model_final.json")  # never pickle
```
- Preload the static 31-feature matrix once (build it the way
  `model/06_final_scores.py` does); per event overwrite only the rolling fields
  (`c_prev2/7/14/30`, `days_since_c`, `bw_prev14`, `nb_block_2d`) for that
  building, re-predict that one row
- Keep `scoring_mode` honest: set it to `"model_v5_ensemble"` when real
- Measure p50/p99 per-event latency + events/sec over the full replay; those
  numbers go verbatim into `/stats`, the video and the slides

### 3b. The monitor page (owner: whoever has T1/T2 cycles)
`web/templates/monitor.html`:
- Poll `/api/live/stats` + `/api/live/queue?k=25` every 1.5 s
- Top strip: replay clock · events processed · events/sec · p99 ms
- Queue table: rank, BBL (link to building page), score, replay complaints,
  units; animate row moves if cheap, skip if not
- A "Start replay" button (speedup 600–3600) + graceful "service offline" state

## Handoff from stream 5 (DELIVERED — Oct 17, evening)

Everything 3a needs is staged, so the model swap is wiring, not feature work:

- **Bundle:** `/home/linux1/replay_assets.tar.gz` on the pipeline guest
  (`148.100.108.101`, 4 MB). Contents: `replay/static_features.csv` (62,716
  rows: `bbl` + the **31 features in exact model column order**, frozen as of
  **2026-02-06**, the eve of the replayed snap), `replay/features_schema.json`,
  `heat_model_final.json` (M2), `calibration.csv`.
- **Pull it onto the site guest** (from `~/heatahead/site`):
  `scp linux1@148.100.108.101:/home/linux1/replay_assets.tar.gz . && mkdir -p model/out && tar -xzf replay_assets.tar.gz -C model/out`
  (Or regenerate anywhere with `data/` + `model/out/`:
  `python model/10_export_replay_assets.py`.)
- **The schema file is the contract.** `features_schema.json` lists
  `feats_in_model_order` (predict with exactly that column order),
  `rolling_fields` (the seven fields the loop mutates per event:
  `c_prev2/7/14/30`, `days_since_c`, `bw_prev14`, `nb_block_2d`),
  `weather_fields` (overwrite once per replay-day from `days.csv`), and the
  update rules per replayed complaint. Static fields never change mid-replay.
- Load M2 with `XGBClassifier().load_model(...)` — never a pickle (s390x).
  Keep `scoring_mode` honest: set it to `model_v5_m2` when the swap lands.
- A bbl absent from the matrix is outside the history universe: keep the stub
  score or show it unranked — do not invent features for it.

## Acceptance

- [ ] `/stats` shows `scoring_mode` ≠ temporary and real p50/p99
- [ ] Queue visibly re-sorts during the Feb 8 peak
- [ ] Page survives the service being down (no console errors, clear banner)
- [ ] 30-second screen capture recorded for the video

**Depends on:** model files (done), replay CSV extraction. **Feeds:** video, +3 demo bonus, Real-Time track.
