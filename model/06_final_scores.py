"""Final deployment model: train on ALL seasons (2018-19 through 2025-26), then
rank every building for the demo.

Two weather modes:
  python model/06_final_scores.py            # replay Feb 8, 2026 (peak cold-snap day)
  python model/06_final_scores.py 2026-01-24 # replay any date in data/days.csv

History features are as of today (last completed season = 2025-26; trailing
windows end at the most recent complaint data). Output feeds the frontend map.

Writes: model/out/heat_model_final.json (or .joblib),
        model/out/ranked_inspection_list.csv
"""

import sys
import numpy as np
import pandas as pd
from common import (DATA, FEATS, NEVER, OUT, band_prep, band_rates, load_days,
                    make_model, season)

REPLAY = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-02-08")

panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
m, backend = make_model()
m.fit(panel[FEATS], panel.failed48)                    # every season, incl. 2025-26
print(f"trained on all {len(panel):,} panel rows ({backend})")
if backend == "xgboost":
    m.save_model(OUT / "heat_model_final.json")
else:
    import joblib
    joblib.dump(m, OUT / "heat_model_final.joblib")

# ---- history as of now
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
bd["season"] = season(bd.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()

viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["season"] = season(pd.to_datetime(viol.inspectiondate))
sv = viol.groupby(["bbl", "season"]).size()

buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")
X = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
               "numfloors", "bldgarea", "cd", "latitude", "longitude"]].copy()
X["yearbuilt"] = X.yearbuilt.replace(0, np.nan)
X["altered"] = (X.yearalter1.fillna(0) > 0).astype(int)

LAST = 2025                                            # last completed season
X["c_last1"] = X.bbl.map(sc.xs(LAST, level="season")).fillna(0)
X["c_last2"] = X.c_last1 + X.bbl.map(sc.xs(LAST - 1, level="season")).fillna(0)
X["v_last1"] = X.bbl.map(sv.xs(LAST, level="season")).fillna(0)
X["v_last2"] = X.v_last1 + X.bbl.map(sv.xs(LAST - 1, level="season")).fillna(0)
X["chronic"] = ((X.c_last1 >= 5) &
                (X.bbl.map(sc.xs(LAST - 1, level="season")).fillna(0) >= 5)).astype(int)

today = bd.day.max()
for w in (7, 14, 30):
    recent = bd[bd.day > today - pd.Timedelta(days=w)].groupby("bbl")["n"].sum()
    X[f"c_prev{w}"] = X.bbl.map(recent).fillna(0)
print(f"trailing windows end {today.date()}")

# reaction rates by band (prior two completed seasons) + days-since + building-wide
X = X.merge(band_rates(*band_prep(bd, load_days()), LAST + 1, X.bbl), on="bbl", how="left")
bw = pd.read_csv(OUT / "building_day_counts_bw.csv", parse_dates=["day"])
bw["season"] = season(bw.day)
X["bw_last1"] = X.bbl.map(bw[bw.season == LAST].groupby("bbl")["n"].sum()).fillna(0)
X["bw_prev14"] = X.bbl.map(bw[bw.day > bw.day.max() - pd.Timedelta(days=14)]
                           .groupby("bbl")["n"].sum()).fillna(0)
X["days_since_c"] = ((today - X.bbl.map(bd.groupby("bbl").day.max())).dt.days
                     .fillna(NEVER))
vdate = pd.to_datetime(pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                                   usecols=["bbl", "inspectiondate"])
                       .dropna(subset=["bbl"])
                       .assign(bbl=lambda t: t.bbl.astype(float).astype("int64"))
                       .groupby("bbl").inspectiondate.max())
X["days_since_v"] = (today - X.bbl.map(vdate)).dt.days.fillna(NEVER)

# the inspectable universe: any history at all (team decision, matches 01/03/05)
X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]
print(f"universe with history: {len(X):,} buildings")

# ---- weather: the replayed day (swap for the live Open-Meteo forecast in the demo)
days = load_days()
drow = days.loc[days.day == REPLAY].iloc[0]
for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
    X[c] = drow[c]
print(f"weather replayed from {REPLAY.date()} (TMIN {drow.TMIN:.0f}F)")

X["score"] = m.predict_proba(X[FEATS])[:, 1]
X["tenants_at_risk"] = X.score * X.unitsres             # the second map view
out = X[["bbl", "score", "tenants_at_risk", "unitsres", "cd",
         "latitude", "longitude", "c_last1", "chronic"]].sort_values(
    "score", ascending=False).reset_index(drop=True)
out.index += 1
out.to_csv(OUT / "ranked_inspection_list.csv", index_label="rank")
print(out.head(10).round(3).to_string())
print(f"wrote {OUT/'ranked_inspection_list.csv'} ({len(out):,} buildings)")
