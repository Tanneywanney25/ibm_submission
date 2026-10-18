"""M15 - next-winter watchlist v2 (T6e): M4's season-risk setup + trajectory features.

Same rows, label and model as 09_season_risk.py (M4): one row per building per
season, features as of Oct 1 (prior seasons only), label = any 48h complaint
cluster during that season. v2 adds slope features, every one built only from
seasons before S (so from data dated before Oct 1 of S):

  c_delta        complaints S-1 minus S-2 (season-over-season delta)
  c_delta_prev   complaints S-2 minus S-3 (was it already rising?)
  v_delta        heat violations S-1 minus S-2
  lord_c_other_last2, lord_trend   landlord's OTHER buildings, S-2 and S-1 minus S-2
  lord_c_per_bldg                  S-1 landlord-other complaints per other building
  (age of the last violation is M4's days_since_v already; kept, not re-added)

and an optional history block (selected or not on 2024-25 only):
  fail_last1, n_fail_prior  failed last season / count of prior failing seasons
  c_ever, v_ever            all prior complaints / violations

Protocol: selection (feature set, one depth try) on 2024-25 with training
2018-2023; forward-chaining check across 2020-2024; 2025-26 touched ONCE for
M4 vs v2 vs baselines; isotonic calibration fit on half of 2025-26, verified
bin by bin on the other half.

Reference caveat: the docs' "preseason 95.4% @1000" is 07_spell_eval's M1
ranking at the season's FIRST cold spell scored on rest-of-season failures, not
M4 at Oct 1. This script measures M4 itself at Oct 1 under the identical label,
so M15 is compared to M4 like for like; cite 95.4 only as the M1 reference.

Run on the LinuxONE guest from the repo root:
    sudo -n docker exec -w /home/ibm-user/ibm_submission notebook python model/27_watchlist_v2.py
Writes model/out/watchlist_v2_{selection,forward,holdout,reliability}.csv
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from common import (DATA, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    load_days, season, second_tier)

KS = (100, 500, 1000, 2500)
SFEATS = ["c_last1", "c_last2", "v_last1", "v_last2", "chronic", "bw_last1",
          "rate_frigid2", "rate_freezing2", "rate_cold2",
          "days_since_c", "days_since_v",
          "lord_nbldg", "lord_c_other_last1", "boiler_defects", "fuel_oil",
          "unitsres", "yearbuilt", "altered", "numfloors", "bldgarea", "cd"]
TRAJ = ["c_delta", "c_delta_prev", "v_delta",
        "lord_c_other_last2", "lord_trend", "lord_c_per_bldg"]
HIST = ["fail_last1", "n_fail_prior", "c_ever", "v_ever"]
VARIANTS = {"M4": SFEATS, "v2_traj": SFEATS + TRAJ, "v2_traj_hist": SFEATS + TRAJ + HIST}

# ---- identical data prep to 09_season_risk.py
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
bd["bbl"] = bd["bbl"].astype("int64")
bw["bbl"] = bw["bbl"].astype("int64")

bd["season"] = season(bd.day)
bw["season"] = season(bw.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()
sbw = bw.groupby(["bbl", "season"])["n"].sum()
num, den = band_prep(bd, days)
lord, boiler = second_tier()
sc_df = sc.rename("c").reset_index()
print(f"complaints {bd.day.min().date()} -> {bd.day.max().date()} | "
      f"violations {viol.inspectiondate.min().date()} -> {viol.inspectiondate.max().date()}")

nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]
truth["season"] = season(truth.day)
fs = truth[["bbl", "season"]].drop_duplicates()
fail_seasons = set(map(tuple, fs.to_numpy()))

base = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                  "numfloors", "bldgarea", "cd"]].copy()
base["yearbuilt"] = base.yearbuilt.replace(0, np.nan)
base["altered"] = (base.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr, bbls):
    return bbls.map(s.xs(yr, level="season")).fillna(0) \
        if yr in s.index.get_level_values(1) else 0.0


def lord_other(S_prev, bbls):
    """Season S_prev complaints across each building's landlord's OTHER buildings."""
    if lord is None:
        return pd.Series(0.0, index=bbls.index)
    m = lord.merge(sc_df.loc[sc_df.season == S_prev, ["bbl", "c"]],
                   on="bbl", how="left").fillna({"c": 0})
    m["o"] = m.groupby("landlord").c.transform("sum") - m.c
    return bbls.map(m.groupby("bbl").o.first()).fillna(0)


def season_frame(S):
    """09's M4 frame as of Oct 1 of season S, plus the trajectory/history columns."""
    X = base.copy()
    X["c_last1"] = hist_col(sc, S - 1, X.bbl)
    c2 = hist_col(sc, S - 2, X.bbl)
    c3 = hist_col(sc, S - 3, X.bbl)
    X["c_last2"] = X.c_last1 + c2
    X["v_last1"] = hist_col(sv, S - 1, X.bbl)
    X["v_last2"] = X.v_last1 + hist_col(sv, S - 2, X.bbl)
    X["chronic"] = ((X.c_last1 >= 5) & (c2 >= 5)).astype(int)
    X["bw_last1"] = hist_col(sbw, S - 1, X.bbl)
    X = X.merge(band_rates(num, den, S, X.bbl), on="bbl", how="left")
    X = add_second_tier(X, lord, boiler, sc_df, S)
    oct1 = pd.Timestamp(f"{S}-10-01")
    lc = bd[bd.day < oct1].groupby("bbl").day.max()
    lv = viol[viol.inspectiondate < oct1].groupby("bbl").inspectiondate.max()
    X["days_since_c"] = (oct1 - X.bbl.map(lc)).dt.days.fillna(NEVER)
    X["days_since_v"] = (oct1 - X.bbl.map(lv)).dt.days.fillna(NEVER)
    # trajectory (all from seasons < S)
    X["c_delta"] = X.c_last1 - c2
    X["c_delta_prev"] = c2 - c3
    X["v_delta"] = X.v_last1 - (X.v_last2 - X.v_last1)
    X["lord_c_other_last2"] = lord_other(S - 2, X.bbl)
    X["lord_trend"] = X.lord_c_other_last1 - X.lord_c_other_last2
    X["lord_c_per_bldg"] = X.lord_c_other_last1 / np.maximum(X.lord_nbldg - 1, 1)
    # history (prior seasons' outcomes are known by Oct 1)
    prior = fs[fs.season < S]
    X["fail_last1"] = X.bbl.isin(set(prior.loc[prior.season == S - 1, "bbl"])).astype(int)
    X["n_fail_prior"] = X.bbl.map(prior.groupby("bbl").size()).fillna(0)
    X["c_ever"] = X.bbl.map(bd[bd.day < oct1].groupby("bbl").n.sum()).fillna(0)
    X["v_ever"] = X.bbl.map(viol[viol.inspectiondate < oct1].groupby("bbl").size()).fillna(0)
    X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)].copy()
    X["y"] = [(b, S) in fail_seasons for b in X.bbl]
    X["season"] = S
    return X


def model(depth=6):
    return HistGradientBoostingClassifier(max_iter=400, max_depth=depth,
                                          learning_rate=0.08, random_state=0)


def prec_at_k(score, y):
    """precision@k with random tie-breaking (same convention as 07_spell_eval)."""
    s = pd.Series(np.asarray(score, float)).sample(frac=1, random_state=0)
    order = s.sort_values(ascending=False, kind="stable").index.to_numpy()
    yy = np.asarray(y)[order]
    return {k: yy[:k].mean() for k in KS}


def fit_score(feats, tr, te, depth=6):
    m = model(depth).fit(tr[feats], tr.y)
    return m.predict_proba(te[feats])[:, 1]


frames = {S: season_frame(S) for S in range(2018, 2026)}
for S, f in frames.items():
    print(f"  season {S}: {len(f):,} buildings, {f.y.mean():.1%} fail")

# ---- 1. selection on 2024-25 only (train 2018-2023)
tr = pd.concat([frames[S] for S in range(2018, 2024)], ignore_index=True)
val = frames[2024]
sel = []
for name, feats in VARIANTS.items():
    for depth in ((6, 8) if name != "M4" else (6,)):
        r = prec_at_k(fit_score(feats, tr, val, depth), val.y)
        sel.append(dict(variant=name, depth=depth, **{f"p@{k}": v for k, v in r.items()}))
        print(f"  val 2024  {name:<13} depth {depth}  " +
              "  ".join(f"@{k} {v:.3f}" for k, v in r.items()))
sel = pd.DataFrame(sel)
sel.to_csv(OUT / "watchlist_v2_selection.csv", index=False)
cand = sel[sel.variant != "M4"].assign(score=lambda t: t["p@1000"] + 1e-3 * t[["p@100", "p@500", "p@2500"]].mean(axis=1))
best = cand.sort_values("score", ascending=False).iloc[0]
V2, DEPTH = VARIANTS[best.variant], int(best.depth)
print(f"selected on 2024-25: {best.variant}, depth {DEPTH}")

# ---- 2. forward chaining across earlier winters (train < S, test S; 2024 is also the selection winter)
fwd = []
for S in range(2020, 2025):
    tr = pd.concat([frames[s] for s in range(2018, S)], ignore_index=True)
    te = frames[S]
    for name, feats, d in (("M4", SFEATS, 6), ("M15", V2, DEPTH)):
        r = prec_at_k(fit_score(feats, tr, te, d), te.y)
        fwd.append(dict(test_season=S, model=name, n=len(te), fail_rate=te.y.mean(),
                        **{f"p@{k}": v for k, v in r.items()}))
fwd = pd.DataFrame(fwd)
fwd.to_csv(OUT / "watchlist_v2_forward.csv", index=False)
print("\nforward chaining (precision@k, fails at least once that winter):")
print(fwd.pivot(index="test_season", columns="model", values=["p@100", "p@1000", "p@2500"]).round(3).to_string())

# ---- 3. the one look at 2025-26
tr = pd.concat([frames[S] for S in range(2018, 2025)], ignore_index=True)
te = frames[2025]
p_m4 = fit_score(SFEATS, tr, te, 6)
p_v2 = fit_score(V2, tr, te, DEPTH)
ranks = {"M4": p_m4, "M15": p_v2,
         "B1 last-season complaints": te.c_last1, "B3 last-season violations": te.v_last1,
         "B4 failed last season": te.fail_last1 * 1e6 + te.c_last1}
hold = pd.DataFrame([dict(method=n, n=len(te), fail_rate=te.y.mean(),
                          **{f"p@{k}": v for k, v in prec_at_k(s, te.y).items()})
                     for n, s in ranks.items()])
hold.to_csv(OUT / "watchlist_v2_holdout.csv", index=False)
print("\nheld-out 2025-26 (touched once), precision@k for 'fails at least once this winter':")
print(hold.round(3).to_string(index=False))

# paired view: per-k bootstrap of (M15 - M4) over buildings is not meaningful for a top-k
# list, so report overlap instead: how many of the top-1000 are shared
o = len(set(te.bbl.to_numpy()[np.argsort(-p_m4)[:1000]]) & set(te.bbl.to_numpy()[np.argsort(-p_v2)[:1000]]))
print(f"top-1000 overlap M4 vs M15: {o}")

# ---- 4. calibration: isotonic on half of 2025-26, verified bin by bin on the other half
rng = np.random.default_rng(0)
half = rng.random(len(te)) < 0.5
yv = te.y.to_numpy()
bins = [0, .05, .1, .2, .35, .5, .65, .8, 1.0]
rel = []
for name, p in (("M4", p_m4), ("M15", p_v2)):
    iso = IsotonicRegression(out_of_bounds="clip").fit(p[half], yv[half])
    pc = np.minimum(iso.predict(p[~half]), 0.99)
    r = (pd.DataFrame({"p": pc, "y": yv[~half]})
         .assign(bin=lambda t: pd.cut(t.p, bins, include_lowest=True))
         .groupby("bin", observed=True).agg(buildings=("y", "size"), predicted=("p", "mean"),
                                            actually_failed=("y", "mean")).reset_index())
    r.insert(0, "model", name)
    r["gap_pp"] = 100 * (r.actually_failed - r.predicted)
    r["brier"] = np.mean((pc - yv[~half]) ** 2)
    rel.append(r)
rel = pd.concat(rel, ignore_index=True)
rel.to_csv(OUT / "watchlist_v2_reliability.csv", index=False)
print("\nreliability on the verification half of 2025-26:")
print(rel.round(3).to_string(index=False))
