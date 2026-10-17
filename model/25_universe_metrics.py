"""Whole-universe evaluation of the frozen M13 per-spell scorer (reporting only).

precision@100 says what an inspector with 100 visits gets; it says nothing about
the other ~63k buildings on the list. This script adds the standard rare-event
reporting (cumulative gain, PR-AUC with the base rate stated, recall@k, Brier)
on the same 8 held-out 2025-26 spells that model/24 evaluated — no retraining,
no new model, frozen numbers untouched.

Scores are the frozen M13 recipe: the mean of the 5 bag members
(model/out/heat_model_spell_s{0..4}.json; final_spell_ensemble.json chose the
pure bag, w_bag=1.0, so no M12 blend term).

Brier is reported three ways, because the bag outputs are not calibrated for
the spell task: (a) raw ensemble probabilities; (b) isotonic-calibrated, with
the isotonic fit on the pooled 2024-25 validation spells — note the bag members
were refit on train+val, so this calibration is slightly optimistic by
construction; (c) the climatology reference (predict the spell base rate for
every building). Read (b) against (c).

Run (instance container, after model/13 and model/24):
    python model/25_universe_metrics.py
Writes: model/out/universe_metrics_per_spell.csv,
        model/out/universe_metrics_summary.csv,
        model/out/universe_gain_curve.csv
(new files only; nothing existing is overwritten)
"""

import glob

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, precision_recall_curve

from common import OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
GAIN_PCTS = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0)   # % of the ranked list

members = []
for seed in range(5):
    m = xgb.XGBClassifier()
    m.load_model(OUT / f"heat_model_spell_s{seed}.json")
    members.append(m)
print(f"loaded {len(members)} M13 bag members")


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


data = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
va = [d for d in data if d[4] == 2024]
te = [d for d in data if d[4] == 2025]
print(f"{len(va)} validation spells (2024-25), {len(te)} test spells (2025-26)")


def score(d):
    X, y, iu = d[1], d[2], d[3]
    p = np.mean([m.predict_proba(X[iu])[:, 1] for m in members], axis=0)
    return p, y[iu]


# isotonic calibration for Brier, fit on the pooled validation spells only
pv, yv = zip(*[score(d) for d in va])
iso = IsotonicRegression(out_of_bounds="clip")
iso.fit(np.concatenate(pv), np.concatenate(yv))

rows, gain_rows, curves = [], [], []
for d in te:
    name = d[0].split("spell_")[-1].replace(".npz", "")
    p, y = score(d)
    n, n_pos = len(y), int(y.sum())
    base = n_pos / n
    order = np.argsort(-p, kind="stable")
    y_sorted = y[order]
    cum = np.cumsum(y_sorted)

    row = dict(spell=name, n_buildings=n, n_failures=n_pos,
               base_rate=round(base, 5),
               pr_auc=round(float(average_precision_score(y, p)), 4),
               brier_raw=round(float(np.mean((p - y) ** 2)), 5),
               brier_calibrated=round(float(np.mean((iso.predict(p) - y) ** 2)), 5),
               brier_climatology=round(float(base * (1 - base)), 5))
    for k in KS:
        row[f"recall_at_{k}"] = round(float(cum[k - 1] / max(n_pos, 1)), 4)
    rows.append(row)

    for pct in GAIN_PCTS:
        k = max(int(round(n * pct / 100)), 1)
        gain_rows.append(dict(spell=name, pct_of_list=pct, k=k,
                              failures_captured=int(cum[k - 1]),
                              pct_of_failures=round(100 * cum[k - 1] / max(n_pos, 1), 2)))

    pr_p, pr_r, _ = precision_recall_curve(y, p)
    curves.append((name, pr_p, pr_r))

per = pd.DataFrame(rows)
per.to_csv(OUT / "universe_metrics_per_spell.csv", index=False)
gain = pd.DataFrame(gain_rows)
gain.to_csv(OUT / "universe_gain_curve.csv", index=False)

mean_cols = [c for c in per.columns if c not in ("spell",)]
summary = per[mean_cols].mean().to_frame("mean_over_spells").round(5)
gain_mean = gain.groupby("pct_of_list")["pct_of_failures"].mean().round(2)
summary_rows = [dict(metric=k, value=round(float(v), 5))
                for k, v in summary.mean_over_spells.items()]
summary_rows += [dict(metric=f"gain_top_{pct}pct_captures_pct_failures", value=float(v))
                 for pct, v in gain_mean.items()]
pd.DataFrame(summary_rows).to_csv(OUT / "universe_metrics_summary.csv", index=False)

print("\nper spell:")
print(per.to_string(index=False))
print("\ncumulative gain (mean over the 8 spells): top X% of list captures Y% of failures")
print(gain_mean.to_string())
print("\nmean over spells:")
print(summary.to_string())
print("\nnote: brier_calibrated uses isotonic fit on the 2024-25 validation "
      "spells; bag members saw val labels in their refit, so it is slightly "
      "optimistic. Compare against brier_climatology.")
print("wrote universe_metrics_per_spell.csv, universe_gain_curve.csv, "
      "universe_metrics_summary.csv")
