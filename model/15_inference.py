"""T7 - statistical inference: every headline gets a CI and a p-value.

Cluster bootstrap (resampling whole days / whole spells, the correlated units)
for 95% CIs; paired permutation tests model-vs-base_14d (sign-flip the per-unit
deltas); Wilson intervals on calibration bins. Pure post-processing of the
saved canonical evaluation files - no model is re-run, no frozen number moves.

Run from the repo root:  python model/15_inference.py
Reads : model/out/results_precision_at_k.csv, spell_results.csv,
        season_reliability.csv
Writes: model/out/stats_inference.csv
"""

import itertools
import numpy as np
import pandas as pd

from common import OUT

B = 2000
RNG = np.random.default_rng(42)
rows_out = []


def boot_ci(v, B=B):
    v = np.asarray(v, float)
    means = RNG.choice(v, size=(B, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def perm_p(delta, exact_max=12):
    """One-sided paired test: P(mean(+/-delta) >= observed | H0 sign-symmetric)."""
    d = np.asarray(delta, float)
    obs = d.mean()
    n = len(d)
    if n <= exact_max:                       # exact enumeration of all sign flips
        signs = np.array(list(itertools.product([1, -1], repeat=n)))
        means = (signs * d).mean(axis=1)
        return float((means >= obs - 1e-12).mean())
    flips = RNG.choice([1, -1], size=(100_000, n))
    means = (flips * d).mean(axis=1)
    return float((means >= obs - 1e-12).mean())


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(mid - half), float(mid + half)


def add(scope, metric, k, method, v, base=None):
    est = float(np.mean(v))
    lo, hi = boot_ci(v)
    p = perm_p(np.asarray(v) - np.asarray(base)) if base is not None else np.nan
    rows_out.append(dict(scope=scope, metric=metric, k=k, method=method,
                         estimate=round(est, 4), ci_lo=round(lo, 4),
                         ci_hi=round(hi, 4),
                         p_vs_base14=(round(p, 6) if p == p else ""),
                         n_units=len(v)))
    return est, lo, hi, p


# ------------------------------------------------- daily (71 cold days)
daily = pd.read_csv(OUT / "results_precision_at_k.csv")
for k in sorted(daily.k.unique()):
    base = daily[(daily.method == "base_14d") & (daily.k == k)].sort_values("day")
    for method in ("model", "model_new_to_list", "base_14d"):
        m = daily[(daily.method == method) & (daily.k == k)].sort_values("day")
        paired = base if method == "model" else None
        for metric in ("precision", "precision_30d"):
            e, lo, hi, p = add("daily", metric, k, method, m[metric].to_numpy(),
                               paired[metric].to_numpy() if paired is not None else None)
            if method == "model":
                stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                print(f"daily  {metric:14s} @{k:<5} {e:.3f} [{lo:.3f},{hi:.3f}] "
                      f"vs base p={p:.5f} {stars}")

# ------------------------------------------------- spell (8 spells; exact test)
spell = pd.read_csv(OUT / "spell_results.csv")
for k in sorted(spell.k.unique()):
    base = spell[(spell.method == "base_14d") & (spell.k == k)].sort_values("start")
    m = spell[(spell.method == "model") & (spell.k == k)].sort_values("start")
    for metric in ("precision_spell", "precision_30d", "precision_rest_of_season"):
        if metric not in m.columns:
            continue
        e, lo, hi, p = add("spell", metric, k, "model", m[metric].to_numpy(),
                           base[metric].to_numpy())
        add("spell", metric, k, "base_14d", base[metric].to_numpy())
        if metric == "precision_spell":
            print(f"spell  {metric:14s} @{k:<5} {e:.3f} [{lo:.3f},{hi:.3f}] "
                  f"exact p={p:.4f} (n=8: CI is wide by construction)")

# ------------------------------------------------- calibration bins (Wilson)
rel = pd.read_csv(OUT / "season_reliability.csv")
for _, r in rel.iterrows():
    kpos = r.actually_failed * r.buildings
    lo, hi = wilson(kpos, r.buildings)
    rows_out.append(dict(scope="season_calibration", metric="observed_rate",
                         k=r.get("bin", ""), method="M4",
                         estimate=round(float(r.actually_failed), 4),
                         ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                         p_vs_base14="", n_units=int(r.buildings)))
    inside = lo <= r.predicted <= hi
    print(f"calib  bin {str(r.get('bin','')):>14}: pred {r.predicted:.3f} "
          f"obs {r.actually_failed:.3f} [{lo:.3f},{hi:.3f}] "
          f"{'OK' if inside else 'OUTSIDE'}")

pd.DataFrame(rows_out).to_csv(OUT / "stats_inference.csv", index=False)
print(f"\nwrote model/out/stats_inference.csv ({len(rows_out)} rows, B={B})")
