"""M16 - recursive feature elimination across three model families.

Substrate: model/13's full-universe spell snapshots (the 31 FEATS at each
spell's eve, label = fails during the spell), the M11/M13 substrate.
Splits: train 2018-2023 spells, validation 2024-25 spells, test the 8 held-out
2025-26 spells (touched once per family, in `final`).

Per family (xgb = M11's config with early stopping on val; hgb = sklearn
HistGradientBoosting; logreg = signed-log + standardized logistic regression):
start from all 31, fit (2 seeds for the tree models), measure validation
permutation importance = drop in mean per-spell average precision when the
column is shuffled WITHIN each spell, remove the least important column,
repeat down to 1. Within-spell shuffling is the right null for a ranking
task: a column constant inside a spell (the weather) scores exactly 0.

Selection rule, fixed before any test look: the val score is
p@100 + p@2500 (M13's rule), mean over seeds; the chosen subset is the
SMALLEST one scoring within 0.005 of that family's best val score.
`final` refits the chosen subset and the full 31 on train+val with 3 seeds
and evaluates each once on the test spells.

Run (instance container, after model/13), one family per process:
    python model/28_feature_rfe.py xgb | hgb | logreg     -> m16_rfe_<family>.csv
    python model/28_feature_rfe.py final                  -> m16_results.csv,
                                                            m16_per_spell.csv
"""

import glob
import json
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from common import FEATS, OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
TOL = 0.005
M13REF = {100: .901, 500: .654, 1000: .514, 2500: .352}
RNG = np.random.default_rng(15)

spells = []
for p in sorted(glob.glob(str(G / "spell_*.npz"))):
    z = np.load(p)
    m = z["in_univ"]
    spells.append(dict(name=p.split("spell_")[1][:10], S=int(z["season"]),
                       X=z["X"][m], y=z["y"].astype(np.int8)[m]))
tr = [d for d in spells if 2018 <= d["S"] <= 2023]
va = [d for d in spells if d["S"] == 2024]
te = [d for d in spells if d["S"] == 2025]


def stack(ds, cols):
    return np.vstack([d["X"][:, cols] for d in ds]), np.concatenate([d["y"] for d in ds])


def slog(X):
    return np.sign(X) * np.log1p(np.abs(X))


def fit(family, cols, seed, ds_fit, n_trees=None):
    """Returns (score_fn, n_trees). Early stopping (xgb) looks at val only."""
    X, y = stack(ds_fit, cols)
    if family == "xgb":
        import xgboost as xgb
        cfg = dict(max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                   eval_metric="aucpr", tree_method="hist", n_jobs=-1, random_state=seed)
        if n_trees is None:
            m = xgb.XGBClassifier(n_estimators=1500, early_stopping_rounds=50, **cfg)
            m.fit(X, y, eval_set=[stack(va, cols)], verbose=False)
            n_trees = m.best_iteration + 1
        else:
            m = xgb.XGBClassifier(n_estimators=n_trees, **cfg)
            m.fit(X, y)
        return (lambda A: m.predict_proba(A)[:, 1]), n_trees
    if family == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        m = HistGradientBoostingClassifier(max_iter=n_trees or 500, learning_rate=0.05,
                                           max_depth=6, min_samples_leaf=50,
                                           early_stopping=n_trees is None,
                                           validation_fraction=0.1, random_state=seed)
        m.fit(X, y)
        return (lambda A: m.predict_proba(A)[:, 1]), int(m.n_iter_)
    if family == "logreg":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import FunctionTransformer, StandardScaler
        m = make_pipeline(FunctionTransformer(slog), SimpleImputer(strategy="median"),
                          StandardScaler(), LogisticRegression(max_iter=500, C=1.0))
        m.fit(X, y)
        return (lambda A: m.decision_function(A)), 0
    raise SystemExit(f"unknown family {family}")


def evaluate(score, ds, cols):
    per = []
    for d in ds:
        s = score(d["X"][:, cols])
        order = np.argsort(-s, kind="stable")
        r = {k: float(d["y"][order[:k]].mean()) for k in KS}
        r["ap"] = float(average_precision_score(d["y"], s))
        per.append(r)
    return per


def mean_of(per):
    return {k: float(np.mean([r[k] for r in per])) for k in per[0]}


def perm_importance(score, cols):
    """Drop in mean val AP when each column is shuffled within each spell."""
    base = mean_of(evaluate(score, va, cols))["ap"]
    imp = {}
    for j, c in enumerate(cols):
        aps = []
        for d in va:
            A = d["X"][:, cols].copy()
            A[:, j] = A[RNG.permutation(len(A)), j]
            aps.append(average_precision_score(d["y"], score(A)))
        imp[c] = base - float(np.mean(aps))
    return imp


def rfe(family):
    seeds = (0,) if family == "logreg" else (0, 1)
    cols = list(range(len(FEATS)))
    rows = []
    while cols:
        fits = [fit(family, cols, s, tr) for s in seeds]
        vm = [mean_of(evaluate(f, va, cols)) for f, _ in fits]
        v = {k: float(np.mean([x[k] for x in vm])) for k in vm[0]}
        imps = [perm_importance(f, cols) for f, _ in fits]
        imp = {c: float(np.mean([i[c] for i in imps])) for c in cols}
        drop = min(cols, key=lambda c: imp[c])
        rows.append(dict(family=family, n_feats=len(cols),
                         feats=json.dumps([FEATS[c] for c in cols]),
                         trees=json.dumps([n for _, n in fits]),
                         val_score=round(v[100] + v[2500], 4),
                         **{f"val_p{k}": round(v[k], 4) for k in KS},
                         val_ap=round(v["ap"], 4), dropped_next=FEATS[drop],
                         drop_importance=round(imp[drop], 5)))
        print(f"{family} {len(cols):2d} feats: val p@100 {v[100]:.3f} p@2500 {v[2500]:.3f} "
              f"ap {v['ap']:.3f} | drop {FEATS[drop]} (imp {imp[drop]:+.5f})", flush=True)
        pd.DataFrame(rows).to_csv(OUT / f"m16_rfe_{family}.csv", index=False)
        cols.remove(drop)


def final():
    rows, per_spell = [], []
    for fam_csv in sorted(glob.glob(str(OUT / "m16_rfe_*.csv"))):
        r = pd.read_csv(fam_csv)
        family = r.family.iloc[0]
        best = r.val_score.max()
        chosen = r[r.val_score >= best - TOL].sort_values("n_feats").iloc[0]
        full = r[r.n_feats == len(FEATS)].iloc[0]
        print(f"\n{family}: best val {best:.4f}; chosen {int(chosen.n_feats)} feats "
              f"(val {chosen.val_score:.4f}) vs full {len(FEATS)} (val {full.val_score:.4f})")
        for label, row in (("full36", full), ("rfe", chosen)):
            cols = [FEATS.index(f) for f in json.loads(row.feats)]
            nt = int(np.mean(json.loads(row.trees))) if family == "xgb" else None
            seeds = (0,) if family == "logreg" else (0, 1, 2)
            pers = []
            for s in seeds:
                score, _ = fit(family, cols, s, tr + va, n_trees=nt)
                per = evaluate(score, te, cols)
                pers.append(per)
                for d, x in zip(te, per):
                    per_spell.append(dict(family=family, subset=label, seed=s,
                                          spell=d["name"],
                                          **{(f"p{k}" if k != "ap" else k): v
                                             for k, v in x.items()}))
            t = mean_of([mean_of(p) for p in pers])
            rows.append(dict(family=family, subset=label, n_feats=len(cols),
                             val_score=row.val_score,
                             **{f"test_p{k}": round(t[k], 4) for k in KS},
                             test_ap=round(t["ap"], 4), feats=row.feats))
            print(f"  {label:6s} {len(cols):2d} feats: test " +
                  " / ".join(f"{t[k]:.3f}" for k in KS) + f" | ap {t['ap']:.3f}", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "m16_results.csv", index=False)
    pd.DataFrame(per_spell).to_csv(OUT / "m16_per_spell.csv", index=False)
    print("\nM13 frozen reference @100/500/1000/2500: " +
          " / ".join(f"{M13REF[k]:.3f}" for k in KS))
    print(res.drop(columns="feats").to_string(index=False))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "xgb"
    print(f"spells: train {len(tr)} | val {len(va)} | test {len(te)}; mode {mode}", flush=True)
    final() if mode == "final" else rfe(mode)
