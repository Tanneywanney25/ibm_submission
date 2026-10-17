import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request

app = Flask(__name__)
lock = threading.RLock()

def normalize_bbl(values):
    return pd.to_numeric(values, errors="raise").astype("int64").astype(str)

events = pd.read_csv(
    "data/replay_feb7_9.csv",
    parse_dates=["received_date"],
)
events["bbl"] = normalize_bbl(events["bbl"])
events = events.sort_values(["received_date", "complaint_id"])

buildings = pd.read_csv(
    "data/buildings.csv",
    usecols=["bbl", "latitude", "longitude", "unitsres"],
)
buildings["bbl"] = normalize_bbl(buildings["bbl"])
buildings = buildings.drop_duplicates("bbl").set_index("bbl")
metadata = buildings.astype(object).where(buildings.notna(), None).to_dict("index")

counts, scores, latencies = {}, {}, []
state = {
    "status": "ready",
    "processed": 0,
    "replay_clock": None,
    "elapsed_seconds": 0,
    "scoring_mode": "temporary_demo_priority",
    "total_events": len(events),
}

def replay(speedup):
    started = time.perf_counter()
    first = events["received_date"].iloc[0]
    try:
        for ev in events.itertuples(index=False):
            target = (ev.received_date - first).total_seconds() / speedup
            remaining = target - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)

            t0 = time.perf_counter()
            with lock:
                bbl = ev.bbl
                counts[bbl] = counts.get(bbl, 0) + 1
                # Demo priority only: cumulative complaints in this replay.
                # This is not a model probability or a historical rolling count.
                scores[bbl] = counts[bbl] / (counts[bbl] + 5.0)
                state["processed"] += 1
                state["replay_clock"] = ev.received_date.isoformat()
                latencies.append((time.perf_counter() - t0) * 1000)
                state["elapsed_seconds"] = time.perf_counter() - started
        with lock:
            state["status"] = "completed"
    except Exception as exc:
        with lock:
            state["status"] = "error"
            state["error"] = str(exc)

@app.get("/queue")
def queue():
    try:
        k = max(1, min(int(request.args.get("k", 50)), 1000))
    except ValueError:
        return jsonify(error="k must be an integer"), 400
    with lock:
        ranked = sorted(scores, key=lambda b: (-scores[b], b))[:k]
        rows = [
            dict(
                bbl=b,
                score=scores[b],
                replay_complaints=counts[b],
                **metadata.get(b, {}),
            )
            for b in ranked
        ]
        return jsonify(scoring_mode=state["scoring_mode"], buildings=rows)

@app.get("/stats")
def stats():
    with lock:
        result = dict(state)
        elapsed = result["elapsed_seconds"]
        result["replay_events_per_second"] = (
            result["processed"] / elapsed if elapsed else 0
        )
        result["processing_latency_ms_p50"] = (
            float(np.percentile(latencies, 50)) if latencies else None
        )
        result["processing_latency_ms_p99"] = (
            float(np.percentile(latencies, 99)) if latencies else None
        )
        return jsonify(result)

@app.post("/replay/start")
def start():
    body = request.get_json(silent=True) or {}
    try:
        speedup = float(body.get("speedup", 3600))
        if not np.isfinite(speedup) or not 1 <= speedup <= 100000:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify(error="speedup must be between 1 and 100000"), 400
    with lock:
        if state["status"] == "running":
            return jsonify(error="Replay already running"), 409
        if events.empty:
            return jsonify(error="Replay file is empty"), 400
        counts.clear()
        scores.clear()
        latencies.clear()
        state.update(
            status="running", processed=0,
            replay_clock=None, elapsed_seconds=0,
        )
        state.pop("error", None)
        threading.Thread(target=replay, args=(speedup,), daemon=True).start()
    return jsonify(status="started", speedup=speedup), 202

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True, use_reloader=False)
