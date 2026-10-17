"""T6b / M8: the enforcement ranker - predict VERIFIED failures.

Same panel, target verified (heat violation within 7 days, 9.6% of cluster
positives): "which buildings will produce a confirmed violation" - the queue an
enforcement office would run. Stream 2's confirmation analysis (1.87x lift) is
this model's validation story. New model, new name; frozen numbers untouched.

Run on the instance:  python model/12_verified_model.py
Then evaluate:        python model/03_evaluate.py --model model/out/heat_model_verified.json --label verified
Writes: model/out/heat_model_verified.json (M8)
"""

import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score

from common import FEATS, OUT

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
train = panel[(panel.season >= 2018) & (panel.season <= 2024)]
test = panel[panel.season == 2025]
print(f"train {len(train):,} rows ({train.verified.mean():.2%} verified-positive) | "
      f"test {len(test):,} ({test.verified.mean():.2%})")

m = xgb.XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                      subsample=0.8, colsample_bytree=0.8,
                      eval_metric="aucpr", tree_method="hist", n_jobs=-1)
m.fit(train[FEATS], train.verified)
p = m.predict_proba(test[FEATS])[:, 1]
print(f"panel test AUC-PR (verified target): {average_precision_score(test.verified, p):.4f}")
m.save_model(OUT / "heat_model_verified.json")
print("wrote model/out/heat_model_verified.json (M8)")
