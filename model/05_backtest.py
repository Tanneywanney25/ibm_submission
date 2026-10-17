"""Rolling backtest across ALL seasons, not just 2025-26.

For each test season S in 2020..2025: train only on seasons <= S-1, then score the
full building universe on S's 10 coldest days (precision@k vs the 14-day baseline).
One model per season, no test season ever touches its own training data.

Run from the repo root:  python model/05_backtest.py
Writes: model/out/backtest_by_season.csv
"""

import numpy as np
import pandas as pd
from common import DATA, FEATS, OUT, load_days, make_model, season

KS = (100, 500, 1000, 2500)
SEASONS = range(2020, 2026)        # 2020 is the first with two full prior seasons + 2018 training
DAYS_PER_SEASON = 10               # coldest days; keeps 6 seasons tractable

days = load_days()
panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")

viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])
viol["season"] = season(viol.inspectiondate)

bd["season"] = season(bd.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()

bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc = bdc.sort_values("day")
active = bdc.bbl.unique()

nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]

base = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                  "numfloors", "bldgarea", "cd"]].copy()
base["yearbuilt"] = base.yearbuilt.replace(0, np.nan)
base["altered"] = (base.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr):
    lvl = s.index.get_level_values(1)
    return base.bbl.map(s.xs(yr, level="season")).fillna(0) if yr in lvl else 0.0


def csum_asof(d):
    t = pd.DataFrame({"bbl": active, "day": d})
    r = pd.merge_asof(t.sort_values("day"), bdc[["bbl", "day", "csum"]],
                      on="day", by="bbl", direction="backward")
    return r.set_index("bbl")["csum"].fillna(0)


rows = []
for S in SEASONS:
    train = panel[(panel.season >= 2018) & (panel.season <= S - 1)]
    m, backend = make_model()
    m.fit(train[FEATS], train.failed48)

    X0 = base.copy()
    X0["c_last1"] = hist_col(sc, S - 1)
    X0["c_last2"] = X0.c_last1 + hist_col(sc, S - 2)
    X0["v_last1"] = hist_col(sv, S - 1)
    X0["v_last2"] = X0.v_last1 + hist_col(sv, S - 2)
    X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, S - 2) >= 5)).astype(int)

    td = days[days.heat_season & (days.TMIN < 32) & (season(days.day) == S)]
    td = td.sort_values("TMIN").head(DAYS_PER_SEASON)

    for _, drow in td.iterrows():
        d = drow.day
        pos = set(truth.loc[truth.day == d, "bbl"])
        X = X0.copy()
        c1 = csum_asof(d - pd.Timedelta(days=1))
        for w in (7, 14, 30):
            X[f"c_prev{w}"] = (c1 - csum_asof(d - pd.Timedelta(days=w + 1))) \
                .reindex(X.bbl).fillna(0).to_numpy()
        for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
                  "SNOW", "AWND", "wday_num"]:
            X[c] = drow[c]

        for method, s_ in (("model", pd.Series(m.predict_proba(X[FEATS])[:, 1], index=X.bbl)),
                           ("base_14d", pd.Series(X.c_prev14.to_numpy(), index=X.bbl))):
            order = s_.sample(frac=1, random_state=0).sort_values(ascending=False, kind="stable")
            for k in KS:
                top = set(order.index[:k])
                rows.append(dict(test_season=S, day=d.date(), k=k, method=method,
                                 n_failures=len(pos),
                                 precision=len(top & pos) / k,
                                 recall=len(top & pos) / max(len(pos), 1)))
    done = pd.DataFrame(rows)
    snap = done[done.test_season == S].groupby(["method", "k"]).precision.mean()
    print(f"season {S}-{str(S+1)[2:]} ({backend}, train<={S-1}): "
          f"p@100 model {snap.get(('model', 100), float('nan')):.3f} "
          f"vs base_14d {snap.get(('base_14d', 100), float('nan')):.3f}", flush=True)

res = pd.DataFrame(rows)
res.to_csv(OUT / "backtest_by_season.csv", index=False)
print("\nmean precision@k by test season:")
print(res.pivot_table(index=["test_season", "method"], columns="k",
                      values="precision").round(3).to_string())
