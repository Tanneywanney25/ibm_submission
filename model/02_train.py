"""Phase 4: train on seasons 2018-2024, hold out 2025-26 entirely.

Trains an ensemble when XGBoost is available (XGBoost + sklearn HistGBC, averaged);
plain HistGBC otherwise. Also writes calibration pairs (held-out test scores vs
outcomes) so 06 can report true probabilities.

Run from the repo root:  python model/02_train.py
Writes: model/out/heat_model.json and/or heat_model.joblib,
        model/out/feature_importance.csv, model/out/calibration.csv
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from common import FEATS, OUT

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
train = panel[(panel.season >= 2018) & (panel.season <= 2024)]
test = panel[panel.season == 2025]
print(f"train {len(train):,} rows ({train.failed48.mean():.1%} pos) | "
      f"test {len(test):,} rows ({test.failed48.mean():.1%} pos)")

models = {}
try:
    from xgboost import XGBClassifier
    m = XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                      subsample=0.8, colsample_bytree=0.8,
                      eval_metric="aucpr", tree_method="hist", n_jobs=-1)
    m.fit(train[FEATS], train.failed48)
    m.save_model(OUT / "heat_model.json")          # portable; never pickle for s390x
    models["xgboost"] = m
except ImportError:
    pass

h = HistGradientBoostingClassifier(max_iter=400, max_depth=6, learning_rate=0.08)
h.fit(train[FEATS], train.failed48)
models["sklearn"] = h
import joblib
joblib.dump(h, OUT / "heat_model.joblib")          # same-machine use only

preds = {name: m.predict_proba(test[FEATS])[:, 1] for name, m in models.items()}
if len(preds) > 1:
    preds["ensemble"] = np.mean(list(preds.values()), axis=0)
for name, p in preds.items():
    print(f"{name:9s} panel test AUC-PR {average_precision_score(test.failed48, p):.4f} "
          f"| AUC-ROC {roc_auc_score(test.failed48, p):.4f}")

# calibration pairs from the held-out season (sampled rows re-weighted by `weight`)
best = preds.get("ensemble", list(preds.values())[0])
pd.DataFrame({"score": best, "y": test.failed48.to_numpy(),
              "weight": 1.0}).to_csv(OUT / "calibration.csv", index=False)

main = models.get("xgboost", models["sklearn"])
if hasattr(main, "feature_importances_"):
    imp = pd.Series(main.feature_importances_, index=FEATS)
else:
    from sklearn.inspection import permutation_importance
    sub = test.sample(min(50_000, len(test)), random_state=0)
    r = permutation_importance(main, sub[FEATS], sub.failed48, n_repeats=3,
                               random_state=0, n_jobs=-1)
    imp = pd.Series(r.importances_mean, index=FEATS)
imp.sort_values(ascending=False).rename("importance").to_csv(OUT / "feature_importance.csv")
print(imp.sort_values(ascending=False).head(12))
