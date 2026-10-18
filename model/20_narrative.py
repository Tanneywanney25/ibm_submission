"""T20 / M14 - do complaint categories and per-unit rates add signal?

Substrate: model/13's full-universe spell snapshots (the 31 FEATS at each
spell's eve, label = fails during the spell). New building-level columns from
model/narrative.py are joined on in nodes.npz order:
  M14a = 31 + CAT_FEATS  (hot-water-only complaints, which 01 drops entirely;
         heat+hot-water share, anonymous share, duplicate share, distinct units)
  M14c = 31 + UNIT_FEATS (complaints per 100 units, breadth across units)
  M14ac = both;  control = the 31 alone, trained identically.
No prose exists in the extract, so the embedding variant has nothing to embed
(coverage table says so).

Recipe per variant x seed: M11's hand config, early-stopped on the 2024-25
spells (train 2018-2023), refit on 2018-2024 with that tree count, scored on
the 8 held-out 2025-26 spells. The winner is chosen on VALIDATION only (the
early-stopped models' val p@100 + p@2500, mean over seeds); every variant's
test numbers are reported. Then a forward-chaining backtest (test winter T,
train seasons <= T-1) for the control vs the val-chosen variant.

Run (instance container, after model/13):  python model/20_narrative.py
Writes: model/out/m14_results.csv, m14_per_spell.csv, m14_backtest.csv,
        narrative_coverage.csv, heat_model_m14.json (val-chosen variant, seed 0)
"""

import glob
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from common import DATA, FEATS, OUT
from narrative import (CAT_FEATS, UNIT_FEATS, load_complaints, narrative_features,
                       season_aggregates, unit_features)

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
SEEDS = (0, 1, 2)
M13REF = {100: .901, 500: .654, 1000: .514, 2500: .352}
IU, IC1, IC14 = FEATS.index("unitsres"), FEATS.index("c_last1"), FEATS.index("c_prev14")
CFG = dict(max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
           eval_metric="aucpr", tree_method="hist", n_jobs=-1)

# ---------------------------------------------------------------- inputs
bbls = np.load(G / "nodes.npz")["bbls"].astype("int64")
c = load_complaints(DATA / "hpd_heat_complaints.csv")
print(f"complaints: {c.complaint_id.nunique():,} distinct, buildings {c.bbl.nunique():,}")

# coverage: no prose fields exist; categorical fields cover every complaint
cov = []
for S, g in c.groupby("season"):
    if 2017 <= S <= 2025:
        cov.append(dict(season=int(S), complaints=g.complaint_id.nunique(),
                        buildings=g.bbl.nunique(),
                        bldg_with_heat=g[g.heat].bbl.nunique(),
                        bldg_with_nhw_only=g[g.nhw].bbl.nunique(),
                        share_with_unit=round(float(g.unit_key.notna().mean()), 3),
                        prose_fields=0))
cov = pd.DataFrame(cov)
cov.to_csv(OUT / "narrative_coverage.csv", index=False)
print(cov.to_string(index=False))

spells = []
agg_cache = {}
for p in sorted(glob.glob(str(G / "spell_*.npz"))):
    z = np.load(p)
    S = int(z["season"])
    start = pd.Timestamp(Path(p).stem.replace("spell_", ""))
    if S not in agg_cache:
        agg_cache = {S: season_aggregates(c, S)}
    cat = narrative_features(c, bbls, S, start, agg_cache[S]).to_numpy(np.float32)
    X = z["X"]
    uni = unit_features(X[:, IU], X[:, IC1], X[:, IC14], cat[:, CAT_FEATS.index("units_last1")])
    m = z["in_univ"]
    spells.append(dict(start=start, S=S, y=z["y"].astype(np.int8)[m],
                       base=X[m], cat=cat[m], uni=uni[m].astype(np.float32)))
print(f"{len(spells)} spell snapshots with M14 columns joined")

VARIANTS = {"control": ("base",), "M14a": ("base", "cat"),
            "M14c": ("base", "uni"), "M14ac": ("base", "cat", "uni")}


def mat(sp, parts):
    return np.hstack([sp[k] for k in parts])


def stack(ds, parts):
    return np.vstack([mat(d, parts) for d in ds]), np.concatenate([d["y"] for d in ds])


def spell_p(model, ds, parts):
    per = []
    for d in ds:
        p = model.predict_proba(mat(d, parts))[:, 1]
        order = np.argsort(-p, kind="stable")
        per.append({k: float(d["y"][order[:k]].mean()) for k in KS})
    return per


def mean_k(per):
    return {k: float(np.mean([r[k] for r in per])) for k in KS}


tr = [d for d in spells if 2018 <= d["S"] <= 2023]
va = [d for d in spells if d["S"] == 2024]
te = [d for d in spells if d["S"] == 2025]
print(f"train {len(tr)} | val {len(va)} | test {len(te)} spells")

# ---------------------------------------------------------------- variants x seeds
rows, per_spell, trees, models = [], [], {}, {}
for name, parts in VARIANTS.items():
    Xtr, ytr = stack(tr, parts)
    Xall, yall = stack(tr + va, parts)
    for seed in SEEDS:
        es = xgb.XGBClassifier(n_estimators=1500, early_stopping_rounds=50,
                               random_state=seed, **CFG)
        es.fit(Xtr, ytr, eval_set=[stack(va, parts)], verbose=False)
        n = es.best_iteration + 1
        vp = mean_k(spell_p(es, va, parts))
        mf = xgb.XGBClassifier(n_estimators=n, random_state=seed, **CFG)
        mf.fit(Xall, yall)
        tper = spell_p(mf, te, parts)
        tp = mean_k(tper)
        trees[(name, seed)] = n
        if seed == 0:
            models[name] = mf
        rows.append(dict(variant=name, seed=seed, n_feats=Xall.shape[1], trees=n,
                         **{f"val_p{k}": round(vp[k], 4) for k in KS},
                         **{f"test_p{k}": round(tp[k], 4) for k in KS}))
        for d, r in zip(te, tper):
            per_spell.append(dict(variant=name, seed=seed, spell=d["start"].date(),
                                  **{f"p{k}": r[k] for k in KS}))
        print(f"  {name:8s} seed {seed}: trees {n:4d} | val p@100 {vp[100]:.3f} "
              f"p@2500 {vp[2500]:.3f} | test p@100 {tp[100]:.3f} p@2500 {tp[2500]:.3f}",
              flush=True)

res = pd.DataFrame(rows)
res.to_csv(OUT / "m14_results.csv", index=False)
ps = pd.DataFrame(per_spell)
ps.to_csv(OUT / "m14_per_spell.csv", index=False)

summ = res.groupby("variant").mean(numeric_only=True)
summ["val_score"] = summ.val_p100 + summ.val_p2500
winner = summ.val_score.idxmax()
print("\nmean over seeds (selection uses VALIDATION columns only):")
print(summ[[f"val_p{k}" for k in KS] + [f"test_p{k}" for k in KS]].round(3).to_string())
print(f"\nval-chosen variant: {winner}")

# paired per-spell comparison of the winner vs the control (seed-averaged)
sp = ps.groupby(["variant", "spell"]).mean(numeric_only=True)
if winner != "control":
    d100 = (sp.loc[winner].p100 - sp.loc["control"].p100)
    wins, losses = int((d100 > 1e-9).sum()), int((d100 < -1e-9).sum())
    print(f"{winner} vs control @100 per spell: {wins} wins, {losses} losses, "
          f"{len(d100) - wins - losses} ties; mean delta {d100.mean():+.4f}")
    models[winner].save_model(OUT / "heat_model_m14.json")
else:
    print("validation chose the control: no M14 variant adds signal on val")

# ---------------------------------------------------------------- forward-chaining backtest
bt = []
challenger = winner if winner != "control" else summ.drop("control").val_score.idxmax()
for T in range(2020, 2026):
    trn = [d for d in spells if 2018 <= d["S"] <= T - 1]
    tst = [d for d in spells if d["S"] == T]
    if not tst:
        continue
    for name in ("control", challenger):
        parts = VARIANTS[name]
        n = int(np.mean([trees[(name, s)] for s in SEEDS]))
        Xa, ya = stack(trn, parts)
        r = []
        for seed in SEEDS[:2]:
            m = xgb.XGBClassifier(n_estimators=n, random_state=seed, **CFG)
            m.fit(Xa, ya)
            r.append(mean_k(spell_p(m, tst, parts)))
        bt.append(dict(test_season=T, variant=name, n_spells=len(tst),
                       **{f"p{k}": round(float(np.mean([x[k] for x in r])), 4) for k in KS}))
        print(f"  backtest {T}-{str(T + 1)[2:]} {name:8s}: p@100 {bt[-1]['p100']:.3f} "
              f"p@2500 {bt[-1]['p2500']:.3f}", flush=True)
bt = pd.DataFrame(bt)
bt.to_csv(OUT / "m14_backtest.csv", index=False)
piv = bt.pivot(index="test_season", columns="variant", values="p100")
print(f"\nbacktest @100: {challenger} beats control in "
      f"{int((piv[challenger] > piv.control).sum())} of {len(piv)} winters")
print("wrote m14_results.csv, m14_per_spell.csv, m14_backtest.csv, narrative_coverage.csv")
