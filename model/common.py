"""Shared bits for the model scripts: feature list, season(), weather prep."""

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path("data")
OUT = Path("model/out")

FEATS = ["c_last1", "c_last2", "v_last1", "v_last2", "chronic",
         "c_prev7", "c_prev14", "c_prev30",
         "rate_frigid2", "rate_freezing2", "rate_cold2",      # reaction rates by band
         "days_since_c", "days_since_v",
         "bw_last1", "bw_prev14",                             # ENTIRE BUILDING complaints
         "unitsres", "yearbuilt", "altered", "numfloors", "bldgarea", "cd",
         "TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
         "SNOW", "AWND", "wday_num"]

NEVER = 9999                       # "no prior event" for the days-since features


def season(d):
    # Oct-May season named by its starting year: Dec 2022 and Feb 2023 -> 2022
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)


def load_days():
    days = pd.read_csv(DATA / "days.csv", parse_dates=["day"]).sort_values("day")
    days["tmin_roll3"] = days.TMIN.rolling(3).min()
    days["tmin_drop"] = days.TMIN.diff()
    days["wday_num"] = days.day.dt.weekday
    return days


def band_prep(bd, days):
    """Pre-aggregate complaint-days and season-days per TMIN band (stream 1's bands).

    Returns (num, den): num = complaint-days per (bbl, season, band),
    den = heat-season days per (season, band)."""
    d = days[days.heat_season].copy()
    d["season"] = season(d.day)
    d["band"] = pd.cut(d.TMIN, [-np.inf, 20, 32, 45, np.inf],
                       right=False, labels=["frigid", "freezing", "cold", "mild"])
    bdd = bd[["bbl", "day"]].merge(d[["day", "season", "band"]], on="day", how="inner")
    num = bdd.groupby(["bbl", "season", "band"], observed=True).size().rename("n")
    den = d.groupby(["season", "band"], observed=True).size().rename("days")
    return num, den


def band_rates(num, den, S, bbls):
    """Reaction rates over the two seasons before S: share of each band's days on
    which the building complained. rate_frigid2 / rate_freezing2 / rate_cold2."""
    prior = [S - 1, S - 2]
    n = (num[num.index.get_level_values("season").isin(prior)]
         .groupby(["bbl", "band"], observed=True).sum().unstack(fill_value=0))
    dd = den[den.index.get_level_values("season").isin(prior)] \
        .groupby("band", observed=True).sum()
    out = pd.DataFrame(index=bbls)
    for band in ("frigid", "freezing", "cold"):
        days_b = dd.get(band, 0)
        col = n[band] if band in n.columns else pd.Series(0, index=n.index)
        out[f"rate_{band}2"] = (col / days_b if days_b else 0.0)
    return out.fillna(0.0).reset_index(names="bbl")


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
