"""Spell-level evaluation + error autopsy on the 2025-26 test season.

Instead of a fresh list every cold DAY, issue one list per cold SPELL (run of 2+
days with mean temp < 32F), ranked on the eve of the spell. A building counts as
caught if it fails at any point during the spell (+1 day of grace). This removes
the which-48-hours timing lottery and is how inspectors would actually work a snap.

Also: the autopsy. For each spell's top-100, where did the "misses" go - failed
later in the spell, failed within 30 days, single complaint only, or clean?

Run from the repo root:  python model/07_spell_eval.py
Writes: model/out/spell_results.csv
"""

import sys

import numpy as np
import pandas as pd
from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, season, second_tier)

KS = (100, 500, 1000, 2500)

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

# ---- models (same loading as 03); --model PATH scores with that single model
# (classifier probabilities or ranker margins - either orders the list)
if "--model" in sys.argv:
    import xgboost as xgblib
    _b = xgblib.Booster()
    _b.load_model(sys.argv[sys.argv.index("--model") + 1])

    def predict(A):
        return _b.inplace_predict(np.ascontiguousarray(A, dtype=np.float32))
else:
    predict = None
models = []
if (OUT / "heat_model.json").exists():
    try:
        from xgboost import XGBClassifier
        m = XGBClassifier(); m.load_model(OUT / "heat_model.json"); models.append(m)
    except ImportError:
        pass
if (OUT / "heat_model.joblib").exists():
    import joblib
    models.append(joblib.load(OUT / "heat_model.joblib"))


if predict is None:
    def predict(A):
        return np.mean([mm.predict_proba(A)[:, 1] for mm in models], axis=0)


# ---- static features as of 2025-26 (same as 03)
bd["season"] = season(bd.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()
bw["season"] = season(bw.day)
sbw = bw.groupby(["bbl", "season"])["n"].sum()

X0 = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                "numfloors", "bldgarea", "cd"]].copy()
X0["yearbuilt"] = X0.yearbuilt.replace(0, np.nan)
X0["altered"] = (X0.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr):
    return X0.bbl.map(s.xs(yr, level="season")).fillna(0) \
        if yr in s.index.get_level_values(1) else 0.0


X0["c_last1"] = hist_col(sc, 2024)
X0["c_last2"] = X0.c_last1 + hist_col(sc, 2023)
X0["v_last1"] = hist_col(sv, 2024)
X0["v_last2"] = X0.v_last1 + hist_col(sv, 2023)
X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, 2023) >= 5)).astype(int)
X0["bw_last1"] = hist_col(sbw, 2024)
num, den = band_prep(bd, days)
X0 = X0.merge(band_rates(num, den, 2025, X0.bbl), on="bbl", how="left")
lord, boiler = second_tier()
X0 = add_second_tier(X0, lord, boiler, sc.rename("c").reset_index(), 2025)

bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc["lastd"] = bdc["day"]
bdc = bdc.sort_values("day")
vdc = (viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "day"})
       .sort_values("day"))
vdc["lastd"] = vdc["day"]
bwc = bw.sort_values(["bbl", "day"]).copy()
bwc["csum"] = bwc.groupby("bbl")["n"].cumsum()
bwc = bwc.sort_values("day")
active, v_active, bw_active = bdc.bbl.unique(), vdc.bbl.unique(), bwc.bbl.unique()


def asof_at(d, right, keys, cols, by="bbl"):
    t = pd.DataFrame({by: keys, "day": d})
    r = pd.merge_asof(t.sort_values("day"), right, on="day", by=by,
                      direction="backward")
    return r.set_index(by)[cols]


blkd = bd.assign(blk=bd.bbl // 10000).groupby(["blk", "day"])["n"].sum().reset_index()
blkc = blkd.sort_values(["blk", "day"]).copy()
blkc["csum"] = blkc.groupby("blk")["n"].cumsum()
blkc = blkc.sort_values("day")
blk_keys = blkc.blk.unique()
first55 = first_cold_day(days)


# ---- truth: cluster building-days
nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]

# ---- 2025-26 cold spells (2+ consecutive days with tmean < 32)
wx = days[days.heat_season].sort_values("day").copy()
wx["tmean"] = (wx.TMAX + wx.TMIN) / 2
wx["frz"] = wx.tmean < 32
wx["run"] = (wx.frz & ~wx.frz.shift(fill_value=False)).cumsum()
spells = (wx[wx.frz].groupby("run").agg(start=("day", "min"), end=("day", "max"),
                                        days=("day", "size"), min_tmin=("TMIN", "min")))
spells = spells[(spells.days >= 2) & (season(spells.start) == 2025)]
print(f"{len(spells)} test spells in 2025-26")

rows, autopsy = [], []
for _, sp in spells.iterrows():
    s, e = sp.start, sp.end + pd.Timedelta(days=1)          # +1 day grace
    X = X0.copy()
    a = asof_at(s - pd.Timedelta(days=1), bdc[["bbl", "day", "csum", "lastd"]],
                active, ["csum", "lastd"])
    c1 = a.csum.fillna(0)
    for w in (7, 14, 30):
        cw = asof_at(s - pd.Timedelta(days=w + 1), bdc[["bbl", "day", "csum"]],
                     active, ["csum"])["csum"].fillna(0)
        X[f"c_prev{w}"] = (c1 - cw).reindex(X.bbl).fillna(0).to_numpy()
    X["days_since_c"] = (s - a.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    av = asof_at(s - pd.Timedelta(days=1), vdc[["bbl", "day", "lastd"]], v_active, ["lastd"])
    X["days_since_v"] = (s - av.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    b1 = asof_at(s - pd.Timedelta(days=1), bwc[["bbl", "day", "csum"]], bw_active, ["csum"])["csum"].fillna(0)
    b15 = asof_at(s - pd.Timedelta(days=15), bwc[["bbl", "day", "csum"]], bw_active, ["csum"])["csum"].fillna(0)
    X["bw_prev14"] = (b1 - b15).reindex(X.bbl).fillna(0).to_numpy()
    c3 = asof_at(s - pd.Timedelta(days=3), bdc[["bbl", "day", "csum"]],
                 active, ["csum"])["csum"].fillna(0)
    X["c_prev2"] = (c1 - c3).reindex(X.bbl).fillna(0).to_numpy()
    nb = (asof_at(s - pd.Timedelta(days=1), blkc[["blk", "day", "csum"]],
                  blk_keys, ["csum"], by="blk")["csum"].fillna(0)
          - asof_at(s - pd.Timedelta(days=3), blkc[["blk", "day", "csum"]],
                    blk_keys, ["csum"], by="blk")["csum"].fillna(0))
    X["nb_block_2d"] = np.clip(nb.reindex(X.bbl // 10000).fillna(0).to_numpy()
                               - X.c_prev2.to_numpy(), 0, None)
    X["days_into_cold"] = days_into_cold([s], [2025], first55)[0]
    X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]
    drow = days.loc[days.day == s].iloc[0]
    for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
        X[c] = drow[c]

    pos = set(truth.loc[truth.day.between(s, e), "bbl"]) & set(X.bbl)
    pos30 = set(truth.loc[truth.day.between(s, s + pd.Timedelta(days=29)), "bbl"]) & set(X.bbl)
    season_end = pd.Timestamp(f"{season(pd.Series([s]))[0] + 1}-05-31")
    pos_season = set(truth.loc[truth.day.between(s, season_end), "bbl"]) & set(X.bbl)
    any48 = set(bd.loc[bd.day.between(s, s + pd.Timedelta(days=1)), "bbl"]) & set(X.bbl)
    rank = {"model": pd.Series(predict(X[FEATS]), index=X.bbl),
            "base_14d": pd.Series(X.c_prev14.to_numpy(), index=X.bbl)}
    for method, sr in rank.items():
        order = sr.sample(frac=1, random_state=0).sort_values(ascending=False, kind="stable")
        for k in KS:
            top = set(order.index[:k])
            rows.append(dict(start=sp.start.date(), days=sp.days, k=k, method=method,
                             n_failures=len(pos),
                             precision_spell=len(top & pos) / k,
                             precision_30d=len(top & pos30) / k,
                             precision_rest_of_season=len(top & pos_season) / k,
                             recall_spell=len(top & pos) / max(len(pos), 1)))
    # autopsy of the model's top-100
    top = set(rank["model"].sort_values(ascending=False).index[:100])
    pos48 = set(truth.loc[truth.day.between(s, s + pd.Timedelta(days=1)), "bbl"])
    autopsy.append(dict(
        start=sp.start.date(),
        fail_48h=len(top & pos48),
        fail_in_spell=len(top & pos),
        fail_30d=len(top & pos30),
        single_complaint_48h=len((top - pos48) & any48),
        clean_30d=100 - len(top & pos30)))

SUF = ("_" + __import__("pathlib").Path(sys.argv[sys.argv.index("--model") + 1]).stem
       ) if "--model" in sys.argv else ""
res = pd.DataFrame(rows)
res.to_csv(OUT / f"spell_results{SUF}.csv", index=False)
print("\nspell-level precision (mean over spells):")
print(res.groupby(["method", "k"])[["precision_spell", "precision_30d",
                                    "precision_rest_of_season", "recall_spell"]]
      .mean().round(3).to_string())
print("\nfirst spell of the season only (the preseason watchlist view):")
print(res[res.start == res.start.min()].set_index(["method", "k"])
      [["precision_spell", "precision_30d", "precision_rest_of_season"]].round(3).to_string())
print("\nautopsy of the model's top-100 per spell:")
print(pd.DataFrame(autopsy).to_string(index=False))
