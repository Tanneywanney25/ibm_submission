"""Verify the saved LinuxONE evidence and redraw its figure.

Requires NumPy and Matplotlib on the machine that renders the figure. This file
does not execute or time either model. All measurements come from timings.csv.
"""

from argparse import ArgumentParser
from pathlib import Path
import csv
import json
import math

import numpy as np

ENGINES = ("snapml_cpu", "ibm_zdnn")
LABELS = ("Snap ML CPU", "IBM zDNN accelerator")
COLORS = ("#2261A5", "#E16A32")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(folder):
    report = json.loads((folder / "results.json").read_text())
    with (folder / "timings.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == ["engine", "workload", "repetition", "rows", "elapsed_ms"],
                "Unexpected timing columns.")
        records = list(reader)
    require(report["status"] == "completed", "Benchmark did not complete.")
    require(report["architecture"] == "s390x", "Expected a measured s390x run.")
    require(set(report["timings"]) == set(ENGINES), "Expected the two recorded engines.")
    expected_total = 2 * (report["batch_repeats"] + report["single_row_repeats"])
    require(len(records) == expected_total, "Incorrect number of timing records.")
    require(all(r["engine"] in ENGINES and r["workload"] in ("batch", "single")
                for r in records), "Unknown engine or workload.")
    metadata = report["metadata"]
    count = metadata["rows_benchmarked"]
    require(metadata["rows_in_file"] - metadata["rows_excluded_missing_or_nonfinite"] == count,
            "Input row counts do not reconcile.")
    groups = {}
    for engine, tree_format in zip(ENGINES, ("compress_trees", "zdnn_tensors")):
        check = report["prediction_checks"][engine]
        require(check["selected_tree_format"] == tree_format, "Unexpected selected engine.")
        require(check["all_scores_finite"] and check["closely_matches_xgboost"],
                "Reported prediction check did not pass.")
        groups[engine] = {}
        for workload, repetitions in (("batch", report["batch_repeats"]),
                                       ("single", report["single_row_repeats"])):
            selected = [r for r in records if r["engine"] == engine and r["workload"] == workload]
            require(len(selected) == repetitions, f"Wrong {engine}/{workload} count.")
            require(sorted(int(r["repetition"]) for r in selected) == list(range(repetitions)),
                    f"Missing or duplicated {engine}/{workload} repetitions.")
            require(all(int(r["rows"]) == (count if workload == "batch" else 1) for r in selected),
                    f"Wrong {engine}/{workload} batch size.")
            values = np.array([float(r["elapsed_ms"]) for r in selected])
            require(bool(np.isfinite(values).all() and (values > 0).all()), "Invalid latency.")
            groups[engine][workload] = values
        batch_median = float(np.median(groups[engine]["batch"]))
        recalculated = {
            "median_batch_ms": batch_median,
            "scores_per_second_from_median_batch": count * 1000 / batch_median,
            "single_row_p50_ms": float(np.percentile(groups[engine]["single"], 50)),
            "single_row_p99_ms": float(np.percentile(groups[engine]["single"], 99)),
        }
        for key, value in recalculated.items():
            require(math.isclose(value, report["timings"][engine][key], rel_tol=1e-12, abs_tol=1e-12),
                    f"Saved {engine}/{key} differs from the raw timings.")
    return report, groups, len(records)


def draw(report, groups, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": "#283445", "text.color": "#172333",
        "xtick.color": "#445267", "ytick.color": "#445267",
        "svg.fonttype": "none", "savefig.facecolor": "white",
    })
    fig = plt.figure(figsize=(12.8, 7.2), facecolor="white")
    grid = fig.add_gridspec(1, 2, left=0.075, right=0.975, top=0.715,
                           bottom=0.25, wspace=0.30)
    batch_ax, single_ax = fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])
    ratio = (report["timings"]["ibm_zdnn"]["median_batch_ms"] /
             report["timings"]["snapml_cpu"]["median_batch_ms"])
    fig.text(0.075, 0.945, "HeatAhead on IBM Z", fontsize=21, weight="bold")
    fig.text(0.075, 0.887, f"CPU batch scoring was {ratio:.2f}× faster in this run.", fontsize=15)
    fig.text(0.075, 0.840,
             f"Same exported XGBoost model. s390x machine {report['machine_type']}. "
             f"{report['requested_threads_per_engine']} requested threads per engine.",
             fontsize=10.5, color="#556477")

    batch_ax.set_title("Batch scoring", loc="left", fontsize=13, weight="bold", pad=32)
    batch_ax.text(0, 1.035,
                  f"{report['metadata']['rows_benchmarked']:,} buildings per call, "
                  f"{report['batch_repeats']} calls per engine", transform=batch_ax.transAxes,
                  fontsize=9.5, color="#556477")
    medians = [report["timings"][engine]["median_batch_ms"] for engine in ENGINES]
    batch_ax.bar([0, 1], medians, width=0.53, color=COLORS, alpha=0.94, zorder=2)
    for index, engine in enumerate(ENGINES):
        values = groups[engine]["batch"]
        offsets = np.linspace(-0.13, 0.13, len(values))
        batch_ax.scatter(index + offsets, values, color="#172333", edgecolor="white",
                         linewidth=0.4, s=18, alpha=0.7, zorder=3)
        batch_ax.text(index, max(values) + 20, f"{medians[index]:.1f} ms",
                      ha="center", fontsize=12, weight="bold")
    batch_ax.set_xticks([0, 1], ["Snap ML CPU", "IBM zDNN"])
    batch_ax.set_ylabel("Elapsed milliseconds per batch")
    batch_ax.set_ylim(0, max(float(groups[e]["batch"].max()) for e in ENGINES) * 1.21)
    batch_ax.set_xlim(-0.6, 1.6)
    batch_ax.grid(axis="y", color="#E6EBF1", zorder=0)
    batch_ax.set_axisbelow(True)
    batch_ax.text(0, -0.225, "Bars show medians. Dots show all measured batch calls.",
                  transform=batch_ax.transAxes, fontsize=8.7, color="#556477")

    single_ax.set_title("Single-building latency", loc="left", fontsize=13, weight="bold", pad=32)
    single_ax.text(0, 1.035,
                   f"{report['single_row_repeats']:,} calls per engine, full empirical distribution",
                   transform=single_ax.transAxes, fontsize=9.5, color="#556477")
    for engine, label, color, linestyle in zip(ENGINES, LABELS, COLORS, ("-", "--")):
        values = np.sort(groups[engine]["single"] * 1000)
        cumulative = np.arange(1, len(values) + 1) / len(values) * 100
        p50, p99 = np.percentile(values, [50, 99])
        single_ax.step(values, cumulative, where="post", color=color, linestyle=linestyle,
                       linewidth=2.1,
                       label=f"{label}\np50 {p50:.1f} µs, p99 {p99:.1f} µs")
        single_ax.scatter([p50, p99], [50, 99], color=color, s=23,
                          edgecolor="white", linewidth=0.6, zorder=4)
    single_ax.set_xscale("log")
    single_ax.set_xlim(8, max(float(groups[e]["single"].max() * 1000) for e in ENGINES) * 1.15)
    single_ax.xaxis.set_major_locator(FixedLocator([10, 30, 100, 300, 1000]))
    single_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, position: f"{value:,.0f}"))
    single_ax.xaxis.set_minor_locator(NullLocator())
    single_ax.set_ylim(0, 105)
    single_ax.set_yticks([0, 25, 50, 75, 95, 100])
    single_ax.set_ylabel("Calls completed at or below this latency (%)")
    single_ax.set_xlabel("Microseconds per call (logarithmic scale)")
    single_ax.grid(axis="y", color="#E6EBF1")
    single_ax.legend(loc="lower right", frameon=False, fontsize=9, labelspacing=1.2)
    single_ax.text(0, -0.225, "All observations included, including slower outliers.",
                   transform=single_ax.transAxes, fontsize=8.7, color="#556477")

    maximum = max(report["prediction_checks"][e]["max_absolute_difference_vs_xgboost"] for e in ENGINES)
    fig.text(0.075, 0.115,
             f"Both paths closely matched XGBoost on all tested rows. Largest score difference: {maximum:.2e}.",
             fontsize=10)
    fig.text(0.075, 0.073,
             "Model inference only. Setup, feature updates, calibration, HTTP and replay processing are excluded.",
             fontsize=9, color="#556477")
    fig.text(0.075, 0.038,
             f"Measured 2026-10-18. {report['metadata']['rows_excluded_missing_or_nonfinite']:,} "
             "incomplete/nonfinite rows excluded. Sources: results.json and timings.csv.",
             fontsize=8.5, color="#556477")
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output / "benchmark.png", dpi=200)
    fig.savefig(output / "benchmark.svg")
    plt.close(fig)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    report, groups, count = verify(args.input_dir)
    print(f"Verified {count:,} timing records; every saved timing summary matches the raw CSV.")
    if not args.check_only:
        output = args.output_dir or args.input_dir
        draw(report, groups, output)
        print(f"Saved benchmark.png and benchmark.svg in {output}")


if __name__ == "__main__":
    main()
