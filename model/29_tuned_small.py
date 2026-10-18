"""M17 - M13's recipe applied to the 8 features M16 chose for XGBoost.

M16 (model/28) found that untuned XGBoost on 8 of the 36 features matches its
own full version on the held-out spells and sits 0.1 below the tuned, bagged
M13 at k=100. That comparison is unfair to the small model until it gets M13's
exact treatment, which is what this script gives it:

  1. the same 12-trial spell HPO (same search space, same RNG seed, so the
     same 12 candidate configs), fit on 2018-2023 spells with early stopping
     on, and selected by, the 2024-25 validation spells only (p@100 + p@2500);
  2. the winner bagged over 5 seeds, each refit on 2018-2024;
  3. one evaluation on the 8 held-out 2025-26 spells.

M13's step 3 (blend weight with M12, chosen on val) resolved to w_bag = 1.0,
so the frozen M13 is the pure 5-seed bag; M17 skips the blend, which would
also bring the 36-feature M12 back in. M13's per-spell scores are recomputed
here from the final_spell_ensemble.json members on the same spells.

Run (instance container, after model/13 and model/24):
    python model/29_tuned_small.py
Writes: model/out/heat_model_m17_s*.json (bag members), m17_ensemble.json,
        m17_results.csv, m17_per_spell.csv
"""

import glob
import json
import numpy as np
import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M13REF = {100: .9012, 500: .654, 1000: .514, 2500: .3516}
M17_FEATS = ["c_last2", "c_prev7", "c_prev14", "c_prev30", "rate_freezing2",
             "days_since_c", "c_prev2", "bldgarea"]
COLS = [FEATS.index(f) for f in M17_FEATS]
RNG = np.random.default_rng(1)          # M13's seed: the same 12 candidate configs


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


data = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
tr = [d for d in data if 2018 <= d[4] <= 2023]
va = [d for d in data if d[4] == 2024]
te = [d for d in data if d[4] == 2025]
te_names = [d[0].split("spell_")[1][:10] for d in te]
print(f"spells: train {len(tr)} | val {len(va)} | test {len(te)}; "
      f"features {M17_FEATS}", flush=True)


def stack(ds, cols):
    return (np.vstack([d[1][d[3]][:, cols] for d in ds]),
            np.concatenate([d[2][d[3]] for d in ds]))


Xtr, ytr = stack(tr, COLS)
Xva, yva = stack(va, COLS)
Xall, yall = stack(tr + va, COLS)


def per_spell(scores_per_spell, ds):
    out = []
    for sc, d in zip(scores_per_spell, ds):
        y = d[2][d[3]]
        order = np.argsort(-sc, kind="stable")
        out.append({k: float(y[order[:k]].mean()) for k in KS})
    return out


def spell_p(scores_per_spell, ds):
    per = per_spell(scores_per_spell, ds)
    return {k: float(np.mean([r[k] for r in per])) for k in KS}


def predict_spells(model, ds, cols):
    return [model.predict_proba(d[1][d[3]][:, cols])[:, 1] for d in ds]


# ---------------- step 1: the same small HPO on the spell task (val only)
print("step 1: spell-HPO, 12 trials, selected on the validation winter")
best, trials = (-1, None), []
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
    vp = spell_p(predict_spells(m, va, COLS), va)
    score = vp[100] + vp[2500]
    trials.append(dict(trial=t, trees=m.best_iteration + 1, val_score=round(score, 4),
                       **{f"val_p{k}": round(vp[k], 4) for k in KS}, **cfg))
    print(f"  trial {t:02d} trees {m.best_iteration+1:4d} depth {cfg['max_depth']} "
          f"lr {cfg['learning_rate']} val p@100 {vp[100]:.3f} p@2500 {vp[2500]:.3f}",
          flush=True)
    if score > best[0]:
        best = (score, dict(cfg=cfg, n=m.best_iteration + 1, val=vp))
cfg, n_trees = best[1]["cfg"], best[1]["n"]
print(f"winner: trees {n_trees} {cfg} val p@100 {best[1]['val'][100]:.3f} "
      f"p@2500 {best[1]['val'][2500]:.3f}")

# ---------------- step 2: seed-bag the winner (refit on train+val)
print("step 2: bagging 5 seeds of the winner, refit on 2018-2024")
m17_seed, members = [], []
for seed in range(5):
    mf = xgb.XGBClassifier(n_estimators=n_trees, eval_metric="aucpr",
                           tree_method="hist", n_jobs=-1, random_state=seed, **cfg)
    mf.fit(Xall, yall)
    mf.save_model(OUT / f"heat_model_m17_s{seed}.json")
    members.append(f"heat_model_m17_s{seed}.json")
    m17_seed.append(predict_spells(mf, te, COLS))
m17_bag = [np.mean([s[i] for s in m17_seed], axis=0) for i in range(len(te))]

# ---------------- M13 on the same spells, from its frozen members
man = json.loads((OUT / "final_spell_ensemble.json").read_text())
assert man["w_bag"] == 1.0, "M13 blend weight is not 1.0; the pure-bag comparison breaks"
ALL = list(range(len(FEATS)))
m13_seed = []
for f in man["members"]:
    mm = xgb.XGBClassifier()
    mm.load_model(OUT / f)
    m13_seed.append(predict_spells(mm, te, ALL))
m13_bag = [np.mean([s[i] for s in m13_seed], axis=0) for i in range(len(te))]

# ---------------- the ONE test evaluation
rows = []
for model, bag, seeds in (("m17", m17_bag, m17_seed), ("m13", m13_bag, m13_seed)):
    for label, sc in [("bag", bag)] + [(f"s{i}", s) for i, s in enumerate(seeds)]:
        for name, r in zip(te_names, per_spell(sc, te)):
            rows.append(dict(model=model, member=label, spell=name,
                             **{f"p{k}": round(r[k], 4) for k in KS}))
ps = pd.DataFrame(rows)
ps.to_csv(OUT / "m17_per_spell.csv", index=False)

bag = ps[ps.member == "bag"].drop(columns="member").pivot(index="spell", columns="model")
seedmeans = ps[ps.member != "bag"].groupby(["model", "member"])[[f"p{k}" for k in KS]].mean()
res = []
print("\nM17 (8 features, tuned, 5-seed bag) vs M13 on the 8 held-out spells:")
for k in KS:
    a, b = bag[(f"p{k}", "m17")], bag[(f"p{k}", "m13")]
    d = (a - b).round(4)
    w, ti, lo = int((d > 0).sum()), int((d == 0).sum()), int((d < 0).sum())
    s17, s13 = seedmeans.loc["m17", f"p{k}"], seedmeans.loc["m13", f"p{k}"]
    res.append(dict(k=k, m17=round(a.mean(), 4), m13=round(b.mean(), 4),
                    m13_frozen=M13REF[k], delta=round(a.mean() - b.mean(), 4),
                    spell_wins=w, spell_ties=ti, spell_losses=lo,
                    m17_seed_min=round(s17.min(), 4), m17_seed_max=round(s17.max(), 4),
                    m13_seed_min=round(s13.min(), 4), m13_seed_max=round(s13.max(), 4)))
    print(f"  p@{k:<5} M17 {a.mean():.4f} | M13 {b.mean():.4f} (frozen {M13REF[k]:.4f}) "
          f"| delta {a.mean()-b.mean():+.4f} | spells W/T/L {w}/{ti}/{lo} "
          f"| seeds M17 {s17.min():.3f}-{s17.max():.3f} M13 {s13.min():.3f}-{s13.max():.3f}")
out = pd.DataFrame(res)
out.to_csv(OUT / "m17_results.csv", index=False)
print("\nper spell (bag):")
print(bag.round(3).to_string())
(OUT / "m17_ensemble.json").write_text(json.dumps(dict(
    members=members, features=M17_FEATS, config=cfg, n_trees=n_trees,
    val=best[1]["val"], trials=trials,
    note="M17 = M13 recipe on M16's 8 XGBoost features; score = mean(members)"),
    indent=2))
print("wrote heat_model_m17_s*.json, m17_ensemble.json, m17_results.csv, m17_per_spell.csv")
