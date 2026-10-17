"""Season-level risk: P(this building loses heat at least once this winter).

The number the tenant lookup shows. One row per building per season, features as
of Oct 1 (prior seasons only), label = any 48h complaint cluster during that
season. Train 2018-2024, verify calibration on held-out 2025-26 bin by bin, then
refit on everything and predict the CURRENT season (2026-27).

Run from the repo root:  python model/09_season_risk.py
Writes: model/out/season_risk_2026.csv, model/out/season_reliability.csv
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from common import (DATA, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    load_days, season, second_tier)

SFEATS = ["c_last1", "c_last2", "v_last1", "v_last2", "chronic", "bw_last1",
          "rate_frigid2", "rate_freezing2", "rate_cold2",
          "days_since_c", "days_since_v",
          "lord_nbldg", "lord_c_other_last1", "boiler_defects", "fuel_oil",
          "unitsres", "yearbuilt", "altered", "numfloors", "bldgarea", "cd"]

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
num, den = band_prep(bd, days)
lord, boiler = second_tier()
sc_df = sc.rename("c").reset_index()

# truth: building-seasons with at least one 48h cluster
nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]
truth["season"] = season(truth.day)
fail_seasons = set(map(tuple, truth[["bbl", "season"]].drop_duplicates().to_numpy()))

last_c = bd.groupby("bbl").day.max()      # overall latest; per-season cut below
base = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                  "numfloors", "bldgarea", "cd"]].copy()
base["yearbuilt"] = base.yearbuilt.replace(0, np.nan)
base["altered"] = (base.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr, bbls):
    return bbls.map(s.xs(yr, level="season")).fillna(0) \
        if yr in s.index.get_level_values(1) else 0.0


def season_frame(S):
    """Features as of Oct 1 of season S; label = fails during S."""
    X = base.copy()
    X["c_last1"] = hist_col(sc, S - 1, X.bbl)
    X["c_last2"] = X.c_last1 + hist_col(sc, S - 2, X.bbl)
    X["v_last1"] = hist_col(sv, S - 1, X.bbl)
    X["v_last2"] = X.v_last1 + hist_col(sv, S - 2, X.bbl)
    X["chronic"] = ((X.c_last1 >= 5) & (hist_col(sc, S - 2, X.bbl) >= 5)).astype(int)
    X["bw_last1"] = hist_col(sbw, S - 1, X.bbl)
    X = X.merge(band_rates(num, den, S, X.bbl), on="bbl", how="left")
    X = add_second_tier(X, lord, boiler, sc_df, S)
    oct1 = pd.Timestamp(f"{S}-10-01")
    lc = bd[bd.day < oct1].groupby("bbl").day.max()
    lv = viol[viol.inspectiondate < oct1].groupby("bbl").inspectiondate.max()
    X["days_since_c"] = (oct1 - X.bbl.map(lc)).dt.days.fillna(NEVER)
    X["days_since_v"] = (oct1 - X.bbl.map(lv)).dt.days.fillna(NEVER)
    X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]
    X["y"] = [(b, S) in fail_seasons for b in X.bbl]
    X["season"] = S
    return X

frames = {S: season_frame(S) for S in range(2018, 2027)}
train = pd.concat([frames[S] for S in range(2018, 2025)], ignore_index=True)
test = frames[2025]
print(f"train {len(train):,} building-seasons ({train.y.mean():.1%} fail) | "
      f"test {len(test):,} ({test.y.mean():.1%})")

m = HistGradientBoostingClassifier(max_iter=400, max_depth=6, learning_rate=0.08)
m.fit(train[SFEATS], train.y)
p_test = m.predict_proba(test[SFEATS])[:, 1]

# calibrate on half the held-out winter, report accuracy on the other half
rng = np.random.default_rng(0)
half = rng.random(len(test)) < 0.5
iso = IsotonicRegression(out_of_bounds="clip")
iso.fit(p_test[half], test.y.to_numpy()[half])
pc = iso.predict(p_test[~half])
yv = test.y.to_numpy()[~half]
bins = [0, .05, .1, .2, .35, .5, .65, .8, 1.0]
rel = (pd.DataFrame({"p": pc, "y": yv})
       .assign(bin=lambda t: pd.cut(t.p, bins, include_lowest=True))
       .groupby("bin", observed=True).agg(buildings=("y", "size"),
                                          predicted=("p", "mean"),
                                          actually_failed=("y", "mean")).round(3))
print("\nseason-risk reliability on held-out 2025-26:")
print(rel.to_string())
rel.to_csv(OUT / "season_reliability.csv")

# refit on everything through 2024-25 + calibration from 2025-26, predict 2026-27
m.fit(pd.concat([train, test])[SFEATS], pd.concat([train, test]).y)
cur = frames[2026].copy()
cur["raw_score"] = m.predict_proba(cur[SFEATS])[:, 1]
# calibrated, but never show certainty: cap at 0.99 (nothing is 100%)
cur["p_season"] = np.minimum(iso.predict(cur.raw_score), 0.99)
out = cur[["bbl", "p_season", "raw_score", "c_last1", "v_last1", "chronic",
           "unitsres", "cd"]].sort_values("raw_score", ascending=False)
out.insert(1, "rank", np.arange(1, len(out) + 1))
out.to_csv(OUT / "season_risk_2026.csv", index=False)
print(f"\nwrote season_risk_2026.csv: {len(out):,} buildings | "
      f"p_season>=0.8: {(out.p_season >= .8).sum():,} | >=0.5: {(out.p_season >= .5).sum():,} "
      f"| median {out.p_season.median():.3f}")
