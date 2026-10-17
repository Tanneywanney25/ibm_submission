# Replay checkpoints and validation

Run one process only: `~/jupyter-env/bin/python realtime/app.py`.
The existing /queue, /stats, /replay/start response fields remain available.
Scores are temporary demo priorities, not calibrated probabilities.

POST /replay/start {"speedup":3600} starts fresh and resets the checkpoint.
POST /replay/pause pauses and saves state; poll /stats until status is paused.
POST /replay/start {"resume":true,"speedup":3600} resumes paused/restored state.
A completed checkpoint restores the completed queue; use a fresh start to replay again.
Startup restores state but does not automatically start a worker.

Checkpoints: data/realtime_checkpoint.json, every 100 events, pause, and completion.
The checkpoint includes position, counts, latency samples, active elapsed time, schema,
scoring mode, and input file hashes. Scores and clock are reconstructed on restore.
Downtime is excluded from elapsed time. A sudden process termination may lose up to
99 events since the last save; resume replays those events from the saved prefix,
without double-counting. Checkpoint I/O is excluded from per-event latency samples
but included in active elapsed time; paced events/sec is not maximum throughput.
Saving uses a flushed/fsynced temporary file, atomic rename and directory fsync.

Inputs changing (including buildings metadata) invalidate the saved state. A corrupt
or incompatible checkpoint blocks startup rather than silently resetting progress.
To intentionally start fresh, stop the server, rename the checkpoint, then restart.
Run this service as a single process; multiple WSGI workers would have independent
memory and race on the checkpoint file. No multi-process deployment is supported.

Queue k must be 1..1000; temporary scoring supports only sort=risk.
Start accepts only a JSON object with speedup (number 1..100000) and resume (boolean).
An empty body retains the original default start behavior. Concurrent starts: 409.
Request bodies over 16 KiB: 413. Pause/start state conflicts: 409.

Run tests: `~/jupyter-env/bin/python realtime/test_recovery.py`.
Tests use temporary synthetic input files and do not touch your replay data.
Model integration and rolling historical features are separate remaining work.
