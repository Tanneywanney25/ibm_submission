"""Shared bits for the model scripts: feature list, season(), weather prep."""

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path("data")
OUT = Path("model/out")

FEATS = ["c_last1", "c_last2", "v_last1", "v_last2", "chronic",
         "c_prev7", "c_prev14", "c_prev30",
         "unitsres", "yearbuilt", "altered", "numfloors", "bldgarea", "cd",
         "TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
         "SNOW", "AWND", "wday_num"]


def season(d):
    # Oct-May season named by its starting year: Dec 2022 and Feb 2023 -> 2022
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)


def load_days():
    days = pd.read_csv(DATA / "days.csv", parse_dates=["day"]).sort_values("day")
    days["tmin_roll3"] = days.TMIN.rolling(3).min()
    days["tmin_drop"] = days.TMIN.diff()
    days["wday_num"] = days.day.dt.weekday
    return days


def make_model():
    """XGBoost when available (LinuxONE container has it); sklearn fallback."""
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                             subsample=0.8, colsample_bytree=0.8,
                             eval_metric="aucpr", tree_method="hist", n_jobs=-1), "xgboost"
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_iter=400, max_depth=6,
                                              learning_rate=0.08), "sklearn"
