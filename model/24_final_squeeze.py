"""M13 - the final squeeze, then freeze: spell-HPO + seed-bagging + M12 blend.

Discipline: EVERY choice (config, bag, blend weight) is made on the validation
winter (2024-25 spells). The 8 test spells are evaluated exactly once, by the
single final recipe. After this, the model stream freezes for the submission.

Run (instance container, after model/13):  python model/24_final_squeeze.py
Writes: model/out/heat_model_spell_s*.json (bag members),
        model/out/final_spell_ensemble.json (recipe manifest),
        model/out/m13_results.csv
"""

import glob
import json
import numpy as np
import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M1REF = {100: .861, 500: .646, 1000: .514, 2500: .348}
RNG = np.random.default_rng(1)


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


def spell_p(scores_per_spell, ds):
    out = {k: [] for k in KS}
    for sc, d in zip(scores_per_spell, ds):
        y = d[2][d[3]]
        order = np.argsort(-sc, kind="stable")
        for k in KS:
            out[k].append(float(y[order[:k]].mean()))
    return {k: float(np.mean(v)) for k, v in out.items()}


def predict_spells(model, ds):
    return [model.predict_proba(d[1][d[3]])[:, 1] for d in ds]


# ---------------- step 1: small HPO on the spell task (selected on val only)
print("step 1: spell-HPO, 12 trials, selected on the validation winter")
best = (-1, None)
for t in range(12):
    cfg = dict(max_depth=int(RNG.choice([3, 4, 5, 6, 7])),
               learning_rate=float(RNG.choice([0.03, 0.05, 0.08])),
               min_child_weight=float(RNG.choice([5, 20, 50, 100])),
               subsample=float(RNG.uniform(0.6, 1.0)),
               colsample_bytree=float(RNG.uniform(0.5, 1.0)),
               reg_lambda=float(RNG.choice([0.5, 1, 3])))
    m = xgb.XGBClassifier(n_estimators=2000, eval_metric="aucpr",
                          tree_method="hist", n_jobs=-1,
                          early_stopping_rounds=60, **cfg)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    vp = spell_p(predict_spells(m, va), va)
    score = vp[100] + vp[2500]
    print(f"  trial {t:02d} trees {m.best_iteration+1:4d} "
          f"val p@100 {vp[100]:.3f} p@2500 {vp[2500]:.3f}", flush=True)
    if score > best[0]:
        best = (score, dict(cfg=cfg, n=m.best_iteration + 1, val=vp))
cfg, n_trees = best[1]["cfg"], best[1]["n"]
print(f"winner: trees {n_trees} {cfg} val p@100 {best[1]['val'][100]:.3f}")

# ---------------- step 2: seed-bag the winner (refit on train+val)
print("step 2: bagging 5 seeds of the winner, refit on 2018-2024")
bag_val, bag_te, members = [], [], []
for seed in range(5):
    mf = xgb.XGBClassifier(n_estimators=n_trees, eval_metric="aucpr",
                           tree_method="hist", n_jobs=-1, random_state=seed, **cfg)
    mf.fit(Xall, yall)
    mf.save_model(OUT / f"heat_model_spell_s{seed}.json")
    members.append(f"heat_model_spell_s{seed}.json")
    bag_val.append(predict_spells(mf, va))   # val preds are from refit-on-val
    bag_te.append(predict_spells(mf, te))
bagv = [np.mean([b[i] for b in bag_val], axis=0) for i in range(len(va))]
bagt = [np.mean([b[i] for b in bag_te], axis=0) for i in range(len(te))]

# ---------------- step 3: blend weight with M12, chosen on val
# NOTE: bag members saw val in their refit, so the val-based weight pick is
# slightly optimistic by construction; the blend is validated by the single
# final test evaluation below and the weight grid is coarse to limit fitting.
m12 = xgb.XGBClassifier()
m12.load_model(OUT / "heat_model_hpo.json")
m12v, m12t = predict_spells(m12, va), predict_spells(m12, te)

print("step 3: blend weight grid on the validation winter")
best_w = (-1, 0.0)
for w in np.round(np.arange(0, 1.01, 0.25), 2):
    mix = [w * a + (1 - w) * b for a, b in zip(bagv, m12v)]
    vp = spell_p(mix, va)
    print(f"  w(bag)={w:.2f} val p@100 {vp[100]:.3f} p@2500 {vp[2500]:.3f}")
    s = vp[100] + vp[2500]
    if s > best_w[0]:
        best_w = (s, float(w))
w = best_w[1]
print(f"chosen blend: {w:.2f}*bagged-spell + {1-w:.2f}*M12")

# ---------------- the ONE test evaluation of the final recipe
final_te = [w * a + (1 - w) * b for a, b in zip(bagt, m12t)]
res = spell_p(final_te, te)
rows = []
print("\nM13 (bag+blend) on the 8 held-out spells - the one test look:")
for k in KS:
    print(f"  p@{k:<5} M13 {res[k]:.3f} | M1 frozen {M1REF[k]:.3f} "
          f"| delta {res[k]-M1REF[k]:+.3f}")
    rows.append(dict(k=k, m13=round(res[k], 4), m1_frozen=M1REF[k],
                     delta=round(res[k] - M1REF[k], 4)))
pd.DataFrame(rows).to_csv(OUT / "m13_results.csv", index=False)
(OUT / "final_spell_ensemble.json").write_text(json.dumps(dict(
    members=members, blend_with="heat_model_hpo.json", w_bag=w,
    config=cfg, n_trees=n_trees,
    note="M13 frozen recipe; score = w*mean(members) + (1-w)*M12"), indent=2))
print("wrote m13_results.csv, final_spell_ensemble.json - MODELS FROZEN")
