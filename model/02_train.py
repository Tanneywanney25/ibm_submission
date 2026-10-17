"""Phase 4: train on seasons 2018-2024, hold out 2025-26 entirely.

Run from the repo root:  python model/02_train.py
Writes: model/out/heat_model.json (xgboost) or heat_model.joblib (sklearn fallback),
        model/out/feature_importance.csv
"""

import pandas as pd
from common import FEATS, OUT, make_model

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
train = panel[(panel.season >= 2018) & (panel.season <= 2024)]
test = panel[panel.season == 2025]
print(f"train {len(train):,} rows ({train.failed48.mean():.1%} pos) | "
      f"test {len(test):,} rows ({test.failed48.mean():.1%} pos)")

m, backend = make_model()
print("backend:", backend)
m.fit(train[FEATS], train.failed48)

# quick panel-level sanity (the real number is 03's full-universe precision@k)
from sklearn.metrics import average_precision_score, roc_auc_score
p = m.predict_proba(test[FEATS])[:, 1]
print(f"panel test AUC-PR {average_precision_score(test.failed48, p):.3f} | "
      f"AUC-ROC {roc_auc_score(test.failed48, p):.3f}")

if backend == "xgboost":
    m.save_model(OUT / "heat_model.json")          # portable; never pickle for s390x
    imp = pd.Series(m.feature_importances_, index=FEATS)
else:
    import joblib
    joblib.dump(m, OUT / "heat_model.joblib")      # same-machine use only
    from sklearn.inspection import permutation_importance
    sub = test.sample(50_000, random_state=0)
    r = permutation_importance(m, sub[FEATS], sub.failed48, n_repeats=3,
                               random_state=0, n_jobs=-1)
    imp = pd.Series(r.importances_mean, index=FEATS)

imp.sort_values(ascending=False).rename("importance").to_csv(OUT / "feature_importance.csv")
print(imp.sort_values(ascending=False).head(10))
