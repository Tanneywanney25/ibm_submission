# Model-backed LinuxONE replay

Run `~/jupyter-env/bin/python realtime/app.py` from the repository root (or any
working directory). Stop the previous port-5000 process first. Use a single
process, not multiple WSGI workers. The native Booster API avoids the installed
XGBoost 2.0.3 / scikit-learn classifier-wrapper incompatibility. If XGBoost is
not in the venv, only its Ubuntu dist-packages path is appended after venv paths.
No packages, model weights, or calibration data are modified at runtime.

Required files:
- data/replay_feb7_9.csv: bbl, received_date, complaint_id, minor_category
- data/buildings.csv: bbl, latitude, longitude, unitsres
- data/days.csv: day, TMIN, TMAX, tmin_lag1, SNOW, AWND
- model/out/heat_model_final.json, feature_schema.json, calibration.csv,
  building_features.csv, building_day_counts.csv, building_day_counts_bw.csv

The supplied handoff has 36 features and 62,716 feature rows. Schema/model feature
count and order must match. Snapshot date must be the day before replay starts.
No trained-model outputs need to be committed to Git.

## Scoring semantics

The initial queue covers all buildings in the feature matrix. Static features
come from the supplied snapshot. Rolling history is rebuilt only from daily
counts strictly before the replay start. Future history rows are ignored.

A rolling window uses the previous W calendar days plus complaints already
observed on the current replay day (the handoff's intraday-update policy).
Daily historical counts do not provide hour-level history; this is not an exact
sliding W*24-hour window. Old buckets expire at day rollover. Complaint recency,
weather and season-clock features advance with the replay date. Prior violation
recency ages from the snapshot; no new violation feed is simulated.

Every complaint updates its building and same-tax-block counts. All ranked
buildings in that block are re-scored because nb_block_2d changes for neighbors.
Events missing from the fixed ranked universe still update neighborhood counts,
but never acquire an invented model score. /stats reports unranked_events.

The daily weather is historical observed weather, not an archived forecast.
The final all-season deployment model was supplied for this simulation; this
replay is not a held-out predictive accuracy test. We apply the supplied isotonic
mapping, but its accuracy under intraday feature updates is not separately
validated. Do not claim validation guarantees or prospective prediction results.
This is a single XGBoost classifier (whose trees form an ensemble), not a newly
implemented multi-model ensemble. scoring_mode is xgboost_final_isotonic_cpu.
No accelerator use is claimed.

## API and recovery

Existing /queue, /stats, /replay/start and /replay/pause remain available.
Queue score is now the calibrated value for compatibility with the monitor;
raw_score is included separately. sort=risk orders by raw score (monotonic with
calibration); sort=tenants orders by calibrated score times residential units.

Start fresh:
`curl -s -X POST localhost:5000/replay/start -H 'Content-Type: application/json' -d '{"speedup":3600}'`

Pause:
`curl -s -X POST localhost:5000/replay/pause`

Resume after paused state or restart:
`curl -s -X POST localhost:5000/replay/start -H 'Content-Type: application/json' -d '{"resume":true,"speedup":3600}'`

A new file data/realtime_model_checkpoint.json keeps model runs separate from
old temporary-scorer checkpoints. It saves every 100 events, on pause and at
completion, using fsync and atomic replacement. On restart the saved event
prefix deterministically rebuilds the rolling state and scores; this avoids
large floating-point matrices in every checkpoint. Recovery does not include
future history or replay-prefix inference time in reported latency samples.
Input/model/calibration fingerprints prevent recovery against changed artifacts.
A sudden termination loses up to 99 events of progress, which are replayed from
the saved prefix without double-counting. Startup restores but does not auto-run.

For an intentional reset after changed inputs, stop the service and rename the
model checkpoint. Keep it if resuming. A fresh /replay/start resets a valid state.

## Validation and benchmark evidence

`~/jupyter-env/bin/python realtime/test_recovery.py`

Four tests cover window expiry, block neighbors, no future history, unknown
buildings, restart across a day boundary, API pause/restart/resume equivalence,
fresh reset, invalid input, and artifact fingerprint rejection. Tests train only
a tiny synthetic fixture; they never retrain the supplied deployment model.

The full 13,186-event handoff replay was also checked locally against independently
aggregated rolling/block counts. Mid-replay recovery reproduced the exact final
features, complaint counts and calibrated scores. Local tests are not LinuxONE
performance evidence.

On LinuxONE run:
`~/jupyter-env/bin/python realtime/benchmark_model.py`

This saves data/realtime_model_benchmark.json with host architecture, model hash,
CPU-only backend, three warmed batch inference+calibration timings, and the NNPA
flag if exposed. A flag does not establish accelerator use.

After a full replay save the actual instance metrics:
`curl -s localhost:5000/stats > data/realtime_model_stats.json`

processing_latency_ms_p50/p99 cover event processing including affected-block
scoring and day-rollover work, excluding checkpoint I/O and HTTP/frontend time.
replay_events_per_second includes pacing and checkpoints and excludes paused
periods. processing_events_per_second is observed service rate from processing
samples, not a separate saturated-load benchmark. batch_inference measures actual
full-universe DMatrix creation, inference and calibration; feature refresh work
is included in event latency but outside the batch-only timer.

## Frontend

The existing web/app.py proxies /api/live/stats and /api/live/queue to port 5000.
Use APP_MODE=lite for the monitor if the full website's additional violations or
landlord inputs are absent; model inference still occurs in the separate real
port-5000 service. Start the web app on 8080 and use an SSH tunnel to view /monitor.
Keep the live monitor's scoring label visible. The web page's CSV download is a
separate static ranked export, not the live replay queue.
