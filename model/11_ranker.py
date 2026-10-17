"""T6a / M7 experiment: learning-to-rank instead of classification.

XGBRanker with rank:pairwise, grouped by calendar day, optimizes exactly our
metric (order within each day's list). Same features, same split, no tuning.
Adoption rule (docs/tasks/T6-models-next.md): adopt ONLY if it beats the frozen
spell p@100 (86.1%) by >=1pp on BOTH the spell and 30d horizons; the submission
numbers never change either way.

Run on the instance:  python model/11_ranker.py
Then evaluate:        python model/07_spell_eval.py --model model/out/heat_model_ranker.json
Writes: model/out/heat_model_ranker.json (M7; margins, not probabilities)
"""

import pandas as pd
import xgboost as xgb

from common import FEATS, OUT

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
train = panel[(panel.season >= 2018) & (panel.season <= 2024)].sort_values("day")
qid = train.day.rank(method="dense").astype(int)
print(f"train {len(train):,} rows across {qid.max()} day-groups")

m = xgb.XGBRanker(objective="rank:pairwise", n_estimators=400, max_depth=6,
                  learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
                  tree_method="hist", n_jobs=-1)
m.fit(train[FEATS], train.failed48.astype(int), qid=qid)
m.save_model(OUT / "heat_model_ranker.json")
print("wrote model/out/heat_model_ranker.json (M7 - scores are margins; "
      "ranking only, calibrate before any display)")
