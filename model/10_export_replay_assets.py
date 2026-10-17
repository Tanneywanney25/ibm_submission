"""T3a handoff: export the static feature matrix + schema the replay service
needs to score with M2 (heat_model_final.json).

One row per ranked building with ALL 31 model features, frozen as of --asof
(default 2026-02-06, the eve of the Feb 7-9 replay snap, so the replay is a
faithful reconstruction). Per replayed event, the service only overwrites the
ROLLING fields for that one building (and the day's WEATHER fields once per
replay-day), then calls model.predict_proba on the row in schema order.

Run from the repo root (instance container):
    python model/10_export_replay_assets.py            # asof 2026-02-06
    python model/10_export_replay_assets.py 2026-10-16 # live-mode variant

Writes model/out/replay/:
    static_features.csv   bbl + the 31 FEATS, in exact model column order
    features_schema.json  ordered FEATS + which are rolling / weather / static,
                          dtypes, asof, model + calibration file names
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, season, second_tier)

ASOF = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-02-06")
S = int(season(pd.Series([ASOF]))[0])          # the season ASOF sits in
cutoff = ASOF                                   # features use data <= ASOF (ranking eve)

ROLLING = ["c_prev2", "c_prev7", "c_prev14", "c_prev30",
           "days_since_c", "bw_prev14", "nb_block_2d"]
WEATHER = ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
           "SNOW", "AWND", "wday_num", "days_into_cold"]

days = load_days()
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
bw = pd.read_csv(OUT / "building_day_counts_bw.csv", parse_dates=["day"])
buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")
viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])
viol["season"] = season(viol.inspectiondate)

bd["season"] = season(bd.day)
bw["season"] = season(bw.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()
sbw = bw.groupby(["bbl", "season"])["n"].sum()

X = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
               "numfloors", "bldgarea", "cd"]].copy()
X["yearbuilt"] = X.yearbuilt.replace(0, np.nan)
X["altered"] = (X.yearalter1.fillna(0) > 0).astype(int)


def hist(s, yr):
    return X.bbl.map(s.xs(yr, level="season")).fillna(0) \
        if yr in s.index.get_level_values(1) else 0.0


X["c_last1"] = hist(sc, S - 1)
X["c_last2"] = X.c_last1 + hist(sc, S - 2)
X["v_last1"] = hist(sv, S - 1)
X["v_last2"] = X.v_last1 + hist(sv, S - 2)
X["chronic"] = ((X.c_last1 >= 5) & (hist(sc, S - 2) >= 5)).astype(int)
X["bw_last1"] = hist(sbw, S - 1)
num, den = band_prep(bd, days)
X = X.merge(band_rates(num, den, S, X.bbl), on="bbl", how="left")
lord, boiler = second_tier()
X = add_second_tier(X, lord, boiler, sc.rename("c").reset_index(), S)

# rolling fields as of the cutoff (the service mutates these per event)
pre = bd[bd.day <= cutoff]
for w, col in [(2, "c_prev2"), (7, "c_prev7"), (14, "c_prev14"), (30, "c_prev30")]:
    r = pre[pre.day > cutoff - pd.Timedelta(days=w)].groupby("bbl")["n"].sum()
    X[col] = X.bbl.map(r).fillna(0)
X["days_since_c"] = ((ASOF + pd.Timedelta(days=1)) - X.bbl.map(pre.groupby("bbl").day.max())) \
    .dt.days.fillna(NEVER)
X["days_since_v"] = ((ASOF + pd.Timedelta(days=1))
                     - X.bbl.map(viol[viol.inspectiondate <= cutoff]
                                 .groupby("bbl").inspectiondate.max())).dt.days.fillna(NEVER)
bwpre = bw[(bw.day <= cutoff) & (bw.day > cutoff - pd.Timedelta(days=14))]
X["bw_prev14"] = X.bbl.map(bwpre.groupby("bbl")["n"].sum()).fillna(0)
blk2 = (pre[pre.day > cutoff - pd.Timedelta(days=2)]
        .assign(blk=lambda t: t.bbl // 10000).groupby("blk")["n"].sum())
X["nb_block_2d"] = np.clip((X.bbl // 10000).map(blk2).fillna(0) - X.c_prev2, 0, None)

# weather of the ASOF day (the service overwrites these per replay-day)
drow = days.loc[days.day == ASOF].iloc[0]
for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
    X[c] = drow[c]
X["days_into_cold"] = days_into_cold([ASOF], [S], first_cold_day(days))[0]

# history universe only (matches training and every evaluation)
X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]

outdir = OUT / "replay"
outdir.mkdir(exist_ok=True)
cols = ["bbl"] + FEATS
X[cols].to_csv(outdir / "static_features.csv", index=False)

schema = dict(
    asof=str(ASOF.date()), season=S, rows=len(X),
    feats_in_model_order=FEATS,
    rolling_fields=ROLLING,
    weather_fields=WEATHER,
    static_fields=[f for f in FEATS if f not in ROLLING + WEATHER],
    never_sentinel=NEVER,
    model="model/out/heat_model_final.json (XGBoost JSON; load with XGBClassifier().load_model - NEVER pickle)",
    calibration="model/out/calibration.csv (fit isotonic on score,y to display honest probabilities)",
    notes=[
        "Predict with model.predict_proba(row[feats_in_model_order])[:,1].",
        "Per replayed complaint: increment that bbl's c_prev2/7/14/30, set days_since_c=0, "
        "bw_prev14 += 1 when ENTIRE BUILDING, nb_block_2d from the block counter; re-score that row only.",
        "Per replay-day rollover: overwrite the weather fields for ALL rows from days.csv.",
        "Universe = buildings with history (63,727); a bbl missing here is unranked by design.",
    ],
)
(outdir / "features_schema.json").write_text(json.dumps(schema, indent=2))
print(f"asof {ASOF.date()} season {S}: wrote {len(X):,} rows x {len(cols)} cols -> {outdir}")
