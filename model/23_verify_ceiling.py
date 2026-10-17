"""Verify M11/M12 before trusting them: seed stability, per-spell consistency,
and honest multiplicity accounting.

1. Retrain M11 with three different seeds (early-stop re-run each time) and
   report the spread of test p@100 - was 89.9 a lucky draw?
2. Per-spell table: M11 and M12 vs M1 (canonical spell_results.csv), with the
   exact paired sign test over the 8 spells.
3. Nothing here touches canonical outputs.

Run (instance container):  python model/23_verify_ceiling.py
Writes: model/out/ceiling_verification.csv
"""

import glob
import itertools
import numpy as np
import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

G = OUT / "graph"


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


data = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
tr = [d for d in data if 2018 <= d[4] <= 2023]
va = [d for d in data if d[4] == 2024]
te = [d for d in data if d[4] == 2025]


def stack(ds):
    return (np.vstack([d[1][d[3]] for d in ds]),
            np.concatenate([d[2][d[3]] for d in ds]))


Xtr, ytr = stack(tr)
Xva, yva = stack(va)
Xall, yall = stack(tr + va)


def per_spell_p100(model, ds):
    out = []
    for d in ds:
        X, y = d[1][d[3]], d[2][d[3]]
        order = np.argsort(-model.predict_proba(X)[:, 1], kind="stable")
        out.append(float(y[order[:100]].mean()))
    return out


# ---------- 1. seed stability of M11
rows = []
print("M11 seed stability (early-stop re-run per seed):")
for seed in (0, 1, 2):
    m = xgb.XGBClassifier(n_estimators=1500, max_depth=6, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, random_state=seed,
                          eval_metric="aucpr", tree_method="hist", n_jobs=-1,
                          early_stopping_rounds=50)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    n = m.best_iteration + 1
    mf = xgb.XGBClassifier(n_estimators=n, max_depth=6, learning_rate=0.05,
                           subsample=0.8, colsample_bytree=0.8, random_state=seed,
                           eval_metric="aucpr", tree_method="hist", n_jobs=-1)
    mf.fit(Xall, yall)
    ps = per_spell_p100(mf, te)
    print(f"  seed {seed}: trees {n:3d}  test p@100 {np.mean(ps):.3f}  per-spell {np.round(ps,2)}")
    rows.append(dict(check="m11_seed", seed=seed, trees=n,
                     p100=round(float(np.mean(ps)), 4)))

# ---------- 2. per-spell consistency vs canonical M1
spellcsv = pd.read_csv(OUT / "spell_results.csv")
m1 = (spellcsv[(spellcsv.method == "model") & (spellcsv.k == 100)]
      .sort_values("start").precision_spell.to_numpy())

m11 = xgb.XGBClassifier()
m11.load_model(OUT / "heat_model_spell.json")
m12 = xgb.XGBClassifier()
m12.load_model(OUT / "heat_model_hpo.json")


def sign_test(deltas):
    """Exact one-sided paired sign-flip test over 8 spells."""
    d = np.asarray(deltas, float)
    signs = np.array(list(itertools.product([1, -1], repeat=len(d))))
    means = (signs * d).mean(axis=1)
    return float((means >= d.mean() - 1e-12).mean())


for name, model in (("M11", m11), ("M12", m12)):
    ps = np.array(per_spell_p100(model, te))
    delta = ps - m1
    wins = int((delta > 0).sum())
    p = sign_test(delta)
    print(f"\n{name} vs M1 per spell @100:")
    for d_, (pp, mm) in zip([x[0] for x in te], zip(ps, m1)):
        print(f"  {d_.split('spell_')[1][:10]}  {name} {pp:.2f}  M1 {mm:.2f}  "
              f"{'WIN' if pp > mm else 'tie' if pp == mm else 'loss'}")
    print(f"  -> mean delta {delta.mean():+.3f} | wins {wins}/8 | exact p {p:.4f}")
    rows.append(dict(check=f"{name.lower()}_vs_m1", seed="", trees="",
                     p100=round(float(ps.mean()), 4), wins=wins, exact_p=round(p, 4)))

pd.DataFrame(rows).to_csv(OUT / "ceiling_verification.csv", index=False)
print("\nwrote ceiling_verification.csv")
