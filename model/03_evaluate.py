"""Phase 5: full-universe precision@k on 2025-26 cold days - the number that wins or loses.

For every 2025-26 heat-season day with TMIN < 32, score ALL 172,485 buildings and
take the top k; measure precision (share that failed48 that day), recall (share of
the day's failures caught), and the same on the verified-violation tier.
Baselines use the identical protocol.

Run from the repo root:  python model/03_evaluate.py [max_days]
Writes: model/out/results_precision_at_k.csv, model/out/scores_<day>.csv (coldest day,
        for the frontend)
"""

import sys
import numpy as np
import pandas as pd
from common import DATA, FEATS, OUT, load_days, season

KS = (100, 500, 1000, 2500)

# ------------------------------------------------------------------ inputs
days = load_days()
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")

viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])

# model (whichever 02_train saved)
if (OUT / "heat_model.json").exists():
    from xgboost import XGBClassifier
    m = XGBClassifier()
    m.load_model(OUT / "heat_model.json")
else:
    import joblib
    m = joblib.load(OUT / "heat_model.joblib")

# ------------------------------------------------------------------ static pieces
# history features as of end of 2024-25 (identical to the panel's 2025 rows)
bd["season"] = season(bd.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
viol["season"] = season(viol.inspectiondate)
sv = viol.groupby(["bbl", "season"]).size()

X0 = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                "numfloors", "bldgarea", "cd"]].copy()
X0["yearbuilt"] = X0.yearbuilt.replace(0, np.nan)
X0["altered"] = (X0.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr):
    return X0.bbl.map(s.xs(yr, level="season")).fillna(0) if yr in s.index.get_level_values(1) else 0.0


X0["c_last1"] = hist_col(sc, 2024)
X0["c_last2"] = X0.c_last1 + hist_col(sc, 2023)
X0["v_last1"] = hist_col(sv, 2024)
X0["v_last2"] = X0.v_last1 + hist_col(sv, 2023)
X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, 2023) >= 5)).astype(int)

# per-building cumulative complaint counts, for trailing windows
bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc = bdc.sort_values("day")
active = bdc.bbl.unique()                        # only these ever have nonzero counts


def csum_asof(d):
    """csum per active bbl as of day d (0 for everyone else)."""
    t = pd.DataFrame({"bbl": active, "day": d})
    r = pd.merge_asof(t.sort_values("day"), bdc[["bbl", "day", "csum"]],
                      on="day", by="bbl", direction="backward")
    return r.set_index("bbl")["csum"].fillna(0)


# truth: failed48 per building-day
nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]

# ------------------------------------------------------------------ test days
test_days = days[(days.heat_season) & (days.TMIN < 32) &
                 (season(days.day) == 2025)].sort_values("TMIN")
if len(sys.argv) > 1:
    test_days = test_days.head(int(sys.argv[1]))   # coldest first
print(f"{len(test_days)} test cold days")

rows, coldest_scores = [], None
for _, drow in test_days.iterrows():
    d = drow.day
    pos = set(truth.loc[truth.day == d, "bbl"])
    ver = set(viol.loc[viol.inspectiondate.between(d, d + pd.Timedelta(days=7)), "bbl"])

    X = X0.copy()
    c1 = csum_asof(d - pd.Timedelta(days=1))
    for w in (7, 14, 30):
        X[f"c_prev{w}"] = (c1 - csum_asof(d - pd.Timedelta(days=w + 1))) \
            .reindex(X.bbl).fillna(0).to_numpy()
    for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
        X[c] = drow[c]

    rank = {
        "model": pd.Series(m.predict_proba(X[FEATS])[:, 1], index=X.bbl),
        "base_last_season": pd.Series(X.c_last1.to_numpy(), index=X.bbl),
        "base_14d": pd.Series(X.c_prev14.to_numpy(), index=X.bbl),
        "base_viol_last_season": pd.Series(X.v_last1.to_numpy(), index=X.bbl),
    }
    tops = {}
    for method, s in rank.items():
        order = s.sample(frac=1, random_state=0).sort_values(ascending=False, kind="stable")
        tops[method] = {k: set(order.index[:k]) for k in KS}
        for k in KS:
            top = tops[method][k]
            rows.append(dict(day=d.date(), TMIN=drow.TMIN, k=k, method=method,
                             n_failures=len(pos),
                             precision=len(top & pos) / k,
                             recall=len(top & pos) / max(len(pos), 1),
                             verified_precision=len(top & ver) / k))
    # new-to-list: the model's picks the 14-day baseline missed - where the model must win
    for k in KS:
        new = tops["model"][k] - tops["base_14d"][k]
        rows.append(dict(day=d.date(), TMIN=drow.TMIN, k=k, method="model_new_to_list",
                         n_failures=len(pos),
                         precision=len(new & pos) / max(len(new), 1),
                         recall=len(new & pos) / max(len(pos), 1),
                         verified_precision=len(new & ver) / max(len(new), 1),
                         n_new=len(new)))
    if coldest_scores is None:                      # test_days is coldest-first
        coldest_scores = X[["bbl"]].assign(score=rank["model"].to_numpy(), day=d.date())

res = pd.DataFrame(rows)
res.to_csv(OUT / "results_precision_at_k.csv", index=False)
coldest_scores.to_csv(OUT / "scores_coldest_day.csv", index=False)

print("\nmean over test days:")
print(res.groupby(["method", "k"])[["precision", "recall", "verified_precision"]]
      .mean().round(3).to_string())
