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

## Acceptance

- [ ] `/stats` shows `scoring_mode` ≠ temporary and real p50/p99
- [ ] Queue visibly re-sorts during the Feb 8 peak
- [ ] Page survives the service being down (no console errors, clear banner)
- [ ] 30-second screen capture recorded for the video

**Depends on:** model files (done), replay CSV extraction. **Feeds:** video, +3 demo bonus, Real-Time track.
