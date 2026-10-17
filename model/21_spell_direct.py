"""M11: train directly on the evaluated task - spell-level failure.

M1 trains on 48h day labels; the headline metric is per-SPELL precision. The
graph dataset (model/13) already holds 54 full-universe spell snapshots
(features at the spell's eve, label = fails during the spell). Train a GBM on
those snapshots: seasons 2018-2023 to fit, 2024-25 spells to pick the round
count, refit on 2018-2024, score the same 8 held-out 2025-26 spells.
Adoption bar unchanged: beat the frozen 86.1 spell p@100 meaningfully and
consistently, or be cataloged as attempted. Frozen numbers never move.

Run (instance container, after model/13):  python model/21_spell_direct.py
Writes: model/out/heat_model_spell.json (M11), model/out/m11_results.csv
"""

import glob
import numpy as np
import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M1REF = {100: .861, 500: .646, 1000: .514, 2500: .348}
C14 = FEATS.index("c_prev14")


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


data = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
tr = [d for d in data if 2018 <= d[4] <= 2023]
va = [d for d in data if d[4] == 2024]
te = [d for d in data if d[4] == 2025]
print(f"spell snapshots: train {len(tr)} | val {len(va)} | test {len(te)}")


def stack(ds):
    X = np.vstack([d[1][d[3]] for d in ds])
    y = np.concatenate([d[2][d[3]] for d in ds])
    return X, y


Xtr, ytr = stack(tr)
Xva, yva = stack(va)
print(f"train rows {len(ytr):,} ({ytr.mean():.2%} pos)")

m = xgb.XGBClassifier(n_estimators=1500, max_depth=6, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8,
                      eval_metric="aucpr", tree_method="hist", n_jobs=-1,
                      early_stopping_rounds=50)
m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
best_n = m.best_iteration + 1
print(f"early stop: best_iteration {m.best_iteration} -> refit with {best_n} trees")

mf = xgb.XGBClassifier(n_estimators=best_n, max_depth=6, learning_rate=0.05,
                       subsample=0.8, colsample_bytree=0.8,
                       eval_metric="aucpr", tree_method="hist", n_jobs=-1)
Xall, yall = stack(tr + va)
mf.fit(Xall, yall)
mf.save_model(OUT / "heat_model_spell.json")


def eval_spells(model, ds):
    out = {k: [] for k in KS}
    base = {k: [] for k in KS}
    for d in ds:
        X, y, u = d[1][d[3]], d[2][d[3]], None
        p = model.predict_proba(X)[:, 1]
        order = np.argsort(-p, kind="stable")
        b_order = np.argsort(-X[:, C14], kind="stable")
        for k in KS:
            out[k].append(float(y[order[:k]].mean()))
            base[k].append(float(y[b_order[:k]].mean()))
    return ({k: float(np.mean(v)) for k, v in out.items()},
            {k: float(np.mean(v)) for k, v in base.items()})


res, b14 = eval_spells(mf, te)
rows = []
print("\nM11 spell-direct on the 8 held-out spells (vs frozen M1):")
for k in KS:
    print(f"  p@{k:<5} M11 {res[k]:.3f} | M1 {M1REF[k]:.3f} | delta {res[k]-M1REF[k]:+.3f} "
          f"| base_14d here {b14[k]:.3f}")
    rows.append(dict(k=k, m11=round(res[k], 4), m1_frozen=M1REF[k],
                     delta=round(res[k] - M1REF[k], 4), base_14d=round(b14[k], 4)))
pd.DataFrame(rows).to_csv(OUT / "m11_results.csv", index=False)
print("wrote m11_results.csv, heat_model_spell.json")
