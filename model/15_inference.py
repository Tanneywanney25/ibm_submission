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
    """One-sided paired test: P(mean(+/-delta) >= observed | H0 sign-symmetric).
    Monte Carlo p uses add-one smoothing - a finite test can never return 0."""
    d = np.asarray(delta, float)
    obs = d.mean()
    n = len(d)
    if n <= exact_max:                       # exact enumeration of all sign flips
        signs = np.array(list(itertools.product([1, -1], repeat=n)))
        means = (signs * d).mean(axis=1)
        return float((means >= obs - 1e-12).mean())
    M = 100_000
    flips = RNG.choice([1, -1], size=(M, n))
    means = (flips * d).mean(axis=1)
    return float((1 + (means >= obs - 1e-12).sum()) / (M + 1))


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


def block_ci(v, blocks, B=B):
    """Sensitivity: bootstrap BLOCKS of consecutive cold days (days inside one
    snap are correlated), not individual days."""
    v = np.asarray(v, float)
    ub = np.unique(blocks)
    groups = [v[blocks == b] for b in ub]
    means = np.empty(B)
    for i in range(B):
        pick = RNG.integers(0, len(groups), size=len(groups))
        means[i] = np.concatenate([groups[j] for j in pick]).mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# ------------------------------------------------- daily (71 cold days)
daily = pd.read_csv(OUT / "results_precision_at_k.csv")
# block id: consecutive calendar cold days share a block (within-snap correlation)
daydates = pd.to_datetime(sorted(daily.day.unique()))
block_of = {}
bid = 0
for i, d in enumerate(daydates):
    if i and (d - daydates[i - 1]).days > 1:
        bid += 1
    block_of[str(d.date())] = bid
print(f"71 days -> {bid + 1} consecutive-day blocks for the sensitivity CI")
for k in sorted(daily.k.unique()):
    base = daily[(daily.method == "base_14d") & (daily.k == k)].sort_values("day")
    for method in ("model", "model_new_to_list", "base_14d"):
        m = daily[(daily.method == method) & (daily.k == k)].sort_values("day")
        paired = base if method == "model" else None
        for metric in ("precision", "precision_30d"):
            e, lo, hi, p = add("daily", metric, k, method, m[metric].to_numpy(),
                               paired[metric].to_numpy() if paired is not None else None)
            if method == "model":
                blocks = m.day.astype(str).map(block_of).to_numpy()
                blo, bhi = block_ci(m[metric].to_numpy(), blocks)
                stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                print(f"daily  {metric:14s} @{k:<5} {e:.3f} day-CI [{lo:.3f},{hi:.3f}] "
                      f"block-CI [{blo:.3f},{bhi:.3f}] p={p:.2e} {stars}")
                rows_out.append(dict(scope="daily_blockboot", metric=metric, k=k,
                                     method="model", estimate=round(e, 4),
                                     ci_lo=round(blo, 4), ci_hi=round(bhi, 4),
                                     p_vs_base14="", n_units=bid + 1))

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
