"""Single-process complaint replay demo; scores remain temporary priorities."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request

MODE = "temporary_demo_priority"
VERSION = 1


def create_app(data_dir=None, checkpoint_every=100):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    data = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1] / "data"
    checkpoint = data / "realtime_checkpoint.json"
    event_path = data / "replay_feb7_9.csv"
    building_path = data / "buildings.csv"
    fingerprint = hashlib.sha256()
    for path in (event_path, building_path):
        fingerprint.update(path.name.encode())
        with path.open("rb") as src:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                fingerprint.update(block)
    fingerprint = fingerprint.hexdigest()

    def bbls(values):
        values = pd.to_numeric(values, errors="raise")
        if values.isna().any() or (values % 1 != 0).any():
            raise ValueError("BBLs must be non-missing integers")
        return values.astype("int64").astype(str)

    events = pd.read_csv(event_path, parse_dates=["received_date"])
    events["bbl"] = bbls(events["bbl"])
    if events.received_date.isna().any() or events.complaint_id.duplicated().any():
        raise ValueError("Replay needs valid timestamps and unique complaint IDs")
    events = events.sort_values(["received_date", "complaint_id"]).reset_index(drop=True)
    rows = list(events.itertuples(index=False))
    buildings = pd.read_csv(building_path, usecols=["bbl", "latitude", "longitude", "unitsres"])
    buildings["bbl"] = bbls(buildings["bbl"])
    buildings = buildings.drop_duplicates("bbl").set_index("bbl")
    metadata = buildings.astype(object).where(buildings.notna(), None).to_dict("index")
    lock = threading.RLock()
    stop = threading.Event()
    counts, scores, latencies = {}, {}, []
    state = dict(status="ready", processed=0, replay_clock=None, elapsed_seconds=0.0,
                 scoring_mode=MODE, total_events=len(rows), checkpoint_processed=0,
                 restored_from_checkpoint=False)

    def snapshot():
        return dict(version=VERSION, fingerprint=fingerprint, scoring_mode=MODE,
                    processed=state["processed"], counts=dict(counts),
                    latencies_ms=list(latencies), elapsed_seconds=state["elapsed_seconds"])

    def save():
        # Caller holds lock. Same-directory rename preserves the previous complete
        # checkpoint if writing is interrupted. No raw tenant fields are stored.
        payload = snapshot()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=data, prefix=".replay-", delete=False) as f:
                temporary = f.name
                json.dump(payload, f, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, checkpoint)
            temporary = None
            directory = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            state["checkpoint_processed"] = state["processed"]
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    if checkpoint.exists():
        try:
            saved = json.loads(checkpoint.read_text())
            n = saved["processed"]
            assert saved["version"] == VERSION and saved["fingerprint"] == fingerprint
            assert saved["scoring_mode"] == MODE
            assert type(n) is int and 0 <= n <= len(rows)
            expected = {}
            for ev in rows[:n]:
                expected[ev.bbl] = expected.get(ev.bbl, 0) + 1
            assert saved["counts"] == expected
            samples = saved["latencies_ms"]
            assert len(samples) == n
            assert all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in samples)
            elapsed = saved["elapsed_seconds"]
            assert type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0
            counts.update(expected)
            scores.update({b: c / (c + 5.0) for b, c in counts.items()})
            latencies.extend(samples)
            state.update(processed=n, checkpoint_processed=n, elapsed_seconds=elapsed,
                         replay_clock=rows[n-1].received_date.isoformat() if n else None,
                         status="completed" if n == len(rows) else "paused",
                         restored_from_checkpoint=True)
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            raise ValueError("Checkpoint invalid or inputs changed. Rename data/realtime_checkpoint.json before starting fresh.") from exc

    def replay(speedup, start_index):
        started = time.perf_counter()
        previous_elapsed = state["elapsed_seconds"]
        anchor = rows[start_index - 1].received_date if start_index else rows[0].received_date
        try:
            for ev in rows[start_index:]:
                target = (ev.received_date - anchor).total_seconds() / speedup
                if stop.wait(max(0, target - (time.perf_counter() - started))):
                    break
                t0 = time.perf_counter()
                with lock:
                    b = ev.bbl
                    counts[b] = counts.get(b, 0) + 1
                    scores[b] = counts[b] / (counts[b] + 5.0)
                    state["processed"] += 1
                    state["replay_clock"] = ev.received_date.isoformat()
                    latencies.append((time.perf_counter() - t0) * 1000)
                    state["elapsed_seconds"] = previous_elapsed + time.perf_counter() - started
                    if state["processed"] % checkpoint_every == 0:
                        save()
            with lock:
                state["elapsed_seconds"] = previous_elapsed + time.perf_counter() - started
                save()
                state["status"] = "completed" if state["processed"] == len(rows) else "paused"
        except Exception as exc:
            with lock:
                state.update(status="error", error=str(exc))

    def error(message, code=400):
        return jsonify(error=message), code

    @app.get("/queue")
    def queue():
        try:
            k = int(request.args.get("k", 50))
            if not 1 <= k <= 1000:
                raise ValueError()
        except ValueError:
            return error("k must be an integer between 1 and 1000")
        if request.args.get("sort", "risk") != "risk":
            return error("Only sort=risk is available with temporary scoring")
        with lock:
            ranked = sorted(scores, key=lambda b: (-scores[b], b))[:k]
            return jsonify(scoring_mode=MODE, buildings=[dict(bbl=b, score=scores[b],
                           replay_complaints=counts[b], **metadata.get(b, {})) for b in ranked])

    @app.get("/stats")
    def stats():
        with lock:
            result = dict(state)
            elapsed = result["elapsed_seconds"]
            result["replay_events_per_second"] = result["processed"] / elapsed if elapsed else 0
            for p in (50, 99):
                result[f"processing_latency_ms_p{p}"] = float(np.percentile(latencies, p)) if latencies else None
            result["latency_scope"] = "lock wait, counter update, temporary scoring; excludes checkpoint I/O and HTTP"
            return jsonify(result)

    @app.post("/replay/start")
    def start():
        if not request.get_data():
            body = {}
        else:
            if not request.is_json:
                return error("Use Content-Type: application/json")
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                return error("Body must be a valid JSON object")
        if set(body) - {"speedup", "resume"}:
            return error("Allowed fields: speedup, resume")
        resume = body.get("resume", False)
        if type(resume) is not bool:
            return error("resume must be a JSON boolean")
        speedup = body.get("speedup", 3600)
        if (type(speedup) not in (int, float) or not math.isfinite(speedup)
                or not 1 <= speedup <= 100000):
            return error("speedup must be a number between 1 and 100000")
        with lock:
            if state["status"] in ("running", "pausing"):
                return error("Replay already running", 409)
            if not rows:
                return error("Replay file is empty")
            if resume:
                if state["status"] != "paused":
                    return error("Resume requires a paused/restored replay", 409)
            else:
                counts.clear()
                scores.clear()
                latencies.clear()
                state.update(processed=0, replay_clock=None, elapsed_seconds=0.0,
                             restored_from_checkpoint=False)
            state.pop("error", None)
            try:
                save()  # Persist fresh reset before processing; never reuse old state.
            except OSError as exc:
                state.update(status="error", error=str(exc))
                return error("Unable to save checkpoint", 500)
            stop.clear()
            state["status"] = "running"
            threading.Thread(target=replay, args=(speedup, state["processed"]), daemon=True).start()
        return jsonify(status="started", speedup=speedup, resumed=resume), 202

    @app.post("/replay/pause")
    def pause():
        with lock:
            if state["status"] not in ("running", "pausing"):
                return error("Replay is not running", 409)
            stop.set()
            state["status"] = "pausing"
        return jsonify(status="pausing"), 202

    @app.errorhandler(413)
    def too_large(exc):
        return error("Request body exceeds 16 KiB", 413)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, threaded=True, use_reloader=False)
