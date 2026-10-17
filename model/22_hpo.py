"""Randomized hyperparameter search for the day-level model - the first one
this project has run (M1 shipped with its initial config untouched).

Honest protocol: each config trains on panel seasons 2018-2023 and is scored
by SPELL p@100 on the 2024-25 snapshots (validation winter) - the test winter
is touched exactly once, by the single winning config, at the very end.
Adoption bar: beat frozen spell 86.1 consistently, else catalog as attempted.

Run (instance container, after model/13):  python model/22_hpo.py [n_trials]
Writes: model/out/hpo_trials.csv, model/out/heat_model_hpo.json (winner)
"""

import glob
import sys
import numpy as np
import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M1REF = {100: .861, 500: .646, 1000: .514, 2500: .348}
N_TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
RNG = np.random.default_rng(0)

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
tr = panel[(panel.season >= 2018) & (panel.season <= 2023)]
trva = panel[(panel.season >= 2018) & (panel.season <= 2024)]
Xtr, ytr = tr[FEATS], tr.failed48
print(f"HPO: {N_TRIALS} trials | train {len(tr):,} rows | val = 2024-25 spells")


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


snaps = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
va = [d for d in snaps if d[4] == 2024]
te = [d for d in snaps if d[4] == 2025]


def spell_p(model, ds):
    out = {k: [] for k in KS}
    for d in ds:
        X, y = d[1][d[3]], d[2][d[3]]
        order = np.argsort(-model.predict_proba(X)[:, 1], kind="stable")
        for k in KS:
            out[k].append(float(y[order[:k]].mean()))
    return {k: float(np.mean(v)) for k, v in out.items()}


def sample():
    return dict(
        n_estimators=int(RNG.choice([300, 400, 600, 800])),
        max_depth=int(RNG.choice([4, 5, 6, 7, 8])),
        learning_rate=float(RNG.choice([0.03, 0.05, 0.08, 0.12])),
        min_child_weight=float(RNG.choice([1, 5, 20, 50])),
        subsample=float(RNG.uniform(0.6, 1.0)),
        colsample_bytree=float(RNG.uniform(0.5, 1.0)),
        reg_lambda=float(RNG.choice([0.5, 1, 3, 10])),
    )


trials = []
best = (-1, None, None)
for t in range(N_TRIALS):
    cfg = sample()
    m = xgb.XGBClassifier(eval_metric="aucpr", tree_method="hist", n_jobs=-1, **cfg)
    m.fit(Xtr, ytr)
    vp = spell_p(m, va)
    trials.append(dict(trial=t, **cfg, **{f"val_p{k}": round(vp[k], 4) for k in KS}))
    print(f"trial {t:02d} val p@100 {vp[100]:.3f} p@2500 {vp[2500]:.3f} {cfg}", flush=True)
    score = vp[100] + vp[2500]            # balance top and depth
    if score > best[0]:
        best = (score, cfg, vp)

pd.DataFrame(trials).to_csv(OUT / "hpo_trials.csv", index=False)
cfg = best[1]
print(f"\nwinner on validation: {cfg} (val p@100 {best[2][100]:.3f})")

final = xgb.XGBClassifier(eval_metric="aucpr", tree_method="hist", n_jobs=-1, **cfg)
final.fit(trva[FEATS], trva.failed48)      # refit through the validation winter
final.save_model(OUT / "heat_model_hpo.json")
tp = spell_p(final, te)                    # the ONE touch of the test winter
print("\nHPO winner on the 8 held-out spells (vs frozen M1):")
for k in KS:
    print(f"  p@{k:<5} HPO {tp[k]:.3f} | M1 {M1REF[k]:.3f} | delta {tp[k]-M1REF[k]:+.3f}")
