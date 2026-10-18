"""Compare the same HeatAhead model on Snap ML CPU and IBM zDNN.

Run on LinuxONE, beside heat_model_final.json, feature_schema.json and
building_features.csv. No training, dependency installation or service changes.
"""

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
import csv
import hashlib
import json
import platform
import re

import numpy as np
import pandas as pd
from snapml import BoostingMachineClassifier
from xgboost import XGBClassifier

THREADS = 3
BATCH_REPEATS = 20
SINGLE_REPEATS = 1000
RTOL, ATOL = 1e-5, 1e-6


def prepare(folder):
    """Load shared inputs and make the separate Snap ML compatibility copy."""
    original_path = folder / "heat_model_final.json"
    schema_path = folder / "feature_schema.json"
    data_path = folder / "building_features.csv"
    schema = json.loads(schema_path.read_text())
    saved = json.loads(original_path.read_text())
    features = schema["feats_in_model_order"]
    if features != saved["learner"]["feature_names"]:
        raise ValueError("Feature order differs from the original model.")
    if saved["learner"]["objective"]["name"] != "binary:logistic":
        raise ValueError("This benchmark expects the binary HeatAhead model.")

    frame = pd.read_csv(data_path)[features]
    values = frame.to_numpy(dtype=np.float32)
    keep = np.isfinite(values).all(axis=1)
    sample = frame.loc[keep].copy()
    X = np.ascontiguousarray(values[keep])
    if not len(X):
        raise ValueError("No rows have complete, finite feature values.")

    # XGBoost 3.4 writes a one-value vector. Snap ML 1.17.2 needs a scalar.
    # Only the separate compatibility copy changes; trees stay identical.
    params = saved["learner"]["learner_model_param"]
    base = json.loads(params["base_score"])
    if isinstance(base, list):
        if len(base) != 1:
            raise ValueError("A multi-output base score needs a different importer.")
        params["base_score"] = str(base[0])
    compatible = folder / "heat_model_snapml_compat.json"
    compatible.write_text(json.dumps(saved, separators=(",", ":")))

    metadata = {
        "rows_in_file": len(frame),
        "rows_benchmarked": len(X),
        "rows_excluded_missing_or_nonfinite": int((~keep).sum()),
        "feature_count": len(features),
        "snapshot_asof": schema.get("asof"),
        "input_dtype": str(X.dtype),
        "input_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (original_path, schema_path, data_path, compatible)
        },
    }
    return sample, X, compatible, metadata


def parity(actual, expected):
    if actual.shape != expected.shape:
        raise ValueError("The engines returned different prediction shapes.")
    return {
        "all_scores_finite": bool(np.isfinite(actual).all()),
        "max_absolute_difference_vs_xgboost": float(np.max(np.abs(actual - expected))),
        "closely_matches_xgboost": bool(
            np.allclose(actual, expected, rtol=RTOL, atol=ATOL)
        ),
        "rtol": RTOL,
        "atol": ATOL,
    }


def measure(models, X, batch_repeats=BATCH_REPEATS, single_repeats=SINGLE_REPEATS):
    """Time completed calls; alternate engine order to reduce order effects."""
    names = list(models)
    records = []
    for model in models.values():
        for _ in range(3):
            model.predict_proba(X)
            model.predict_proba(X[:1])

    rng = np.random.default_rng(20261018)
    indices = rng.integers(0, len(X), size=single_repeats)
    for workload, repetitions in (("batch", batch_repeats), ("single", single_repeats)):
        for repetition in range(repetitions):
            if workload == "batch":
                A = X
            else:
                index = int(indices[repetition])
                A = X[index:index + 1]
            order = names if repetition % 2 == 0 else names[::-1]
            for name in order:
                start = perf_counter_ns()
                prediction = models[name].predict_proba(A)
                elapsed_ms = (perf_counter_ns() - start) / 1_000_000
                if prediction.shape != (len(A), 2):
                    raise ValueError(f"Unexpected prediction shape from {name}.")
                records.append({
                    "engine": name, "workload": workload,
                    "repetition": repetition, "rows": len(A),
                    "elapsed_ms": elapsed_ms,
                })

    summary = {}
    for name in names:
        batch = [r["elapsed_ms"] for r in records
                 if r["engine"] == name and r["workload"] == "batch"]
        single = [r["elapsed_ms"] for r in records
                  if r["engine"] == name and r["workload"] == "single"]
        median = float(np.median(batch))
        summary[name] = {
            "median_batch_ms": median,
            "scores_per_second_from_median_batch": len(X) * 1000 / median,
            "single_row_p50_ms": float(np.percentile(single, 50)),
            "single_row_p99_ms": float(np.percentile(single, 99)),
        }
    return summary, records


def main():
    if platform.machine() != "s390x":
        raise SystemExit("Run this file in your LinuxONE Jupyter Terminal (s390x).")
    folder = Path(__file__).resolve().parent
    sample, X, compatible, metadata = prepare(folder)
    print(f"Buildings benchmarked: {len(X):,}", flush=True)
    print(f"Rows excluded for missing/nonfinite inputs: "
          f"{metadata['rows_excluded_missing_or_nonfinite']:,}", flush=True)

    reference = XGBClassifier(n_jobs=THREADS)
    reference.load_model(folder / "heat_model_final.json")
    reference.set_params(n_jobs=THREADS)
    expected = reference.predict_proba(sample)[:, 1]
    models, checks = {}, {}
    for name, tree_format in (("snapml_cpu", "compress_trees"),
                              ("ibm_zdnn", "zdnn_tensors")):
        print(f"Loading {name}...", flush=True)
        model = BoostingMachineClassifier(n_jobs=THREADS)
        model.import_model(str(compatible), input_type="xgb_json",
                           tree_format=tree_format, X=X[:10000])
        selected = model.booster_.optimized_tree_format_
        if selected != tree_format:
            raise RuntimeError(f"Requested {tree_format}, got {selected}.")
        checks[name] = parity(model.predict_proba(X)[:, 1], expected)
        checks[name]["selected_tree_format"] = selected
        print(f"{name}: full-input score match = "
              f"{checks[name]['closely_matches_xgboost']}; max difference = "
              f"{checks[name]['max_absolute_difference_vs_xgboost']:.9g}", flush=True)
        models[name] = model

    cpuinfo = Path("/proc/cpuinfo").read_text()
    machine = re.search(r"\bmachine\s*=\s*(\d+)", cpuinfo)
    report = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "architecture": platform.machine(),
        "machine_type": machine.group(1) if machine else None,
        "nnpa_flag_present": bool(re.search(r"\bnnpa\b", cpuinfo)),
        "versions": {name: version(name) for name in
                     ("snapml", "xgboost", "numpy", "pandas", "scikit-learn")},
        "requested_threads_per_engine": THREADS,
        "batch_repeats": BATCH_REPEATS,
        "single_row_repeats": SINGLE_REPEATS,
        "warmup_calls_per_engine_per_workload": 3,
        "metadata": metadata,
        "prediction_checks": checks,
        "scope": (
            "Historical complete-case inputs; uncalibrated model inference only. "
            "Excludes file/model loading, optimization, feature updates, calibration, "
            "HTTP and queue handling. This is not an accuracy evaluation or replay "
            "latency benchmark and does not replace frozen submission results."
        ),
    }
    output = folder / "benchmark_results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output.mkdir(parents=True, exist_ok=False)
    if not all(check["closely_matches_xgboost"] for check in checks.values()):
        report["status"] = "prediction_mismatch_no_timing_run"
        (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
        raise RuntimeError(f"Score comparison failed. Details saved in {output}")

    print("Timing both engines; please wait for the final table...", flush=True)
    summary, records = measure(models, X)
    report["status"] = "completed"
    report["timings"] = summary
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    with (output / "timings.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    print("\nEngine          Batch median ms    Scores/sec    Single p50 ms    Single p99 ms")
    for name, result in summary.items():
        print(f"{name:<15} {result['median_batch_ms']:>14.3f} "
              f"{result['scores_per_second_from_median_batch']:>13,.0f} "
              f"{result['single_row_p50_ms']:>16.3f} "
              f"{result['single_row_p99_ms']:>16.3f}")
    print(f"\nSaved results.json and timings.csv in:\n{output}")
    print("Timing covers model inference only; it excludes web/replay processing.")


if __name__ == "__main__":
    main()
