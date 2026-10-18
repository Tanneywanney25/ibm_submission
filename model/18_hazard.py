"""T10 / M10 - discrete-time hazard: WHEN a building first loses heat.

A classifier on building-day rows (each building at risk until its FIRST
failed48 day of the season) IS a discrete-time hazard model with a flexible
baseline. Rows carry the standard 31 features; alive days are strided and
weighted back up (Horvitz-Thompson), event days always kept at weight 1.

Chronology: hazard model trained on seasons 2018-19 .. 2023-24, hazard
isotonic-calibrated on 2024-25 (out-of-sample for the model), tested once on
the untouched 2025-26. Survival curves S(t) = prod(1 - h) use each building's
at-risk path only (hazards after a realized failure are never consumed), so
every number below is a function of information available on the eve of day t.

Weather is OBSERVED throughout - this is a backtest; the live product would
use the 7-day forecast then climatological TMIN, and must say so on any chart.

Run from the repo root:  python model/18_hazard.py
Writes: model/out/heat_model_hazard.json (M10),
        model/out/hazard_calibration.csv (raw-hazard/outcome pairs, 2024-25),
        model/out/hazard_eval.csv, model/out/expected_failure_week.csv
"""

import numpy as np
import pandas as pd
from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, make_model, season,
                    second_tier)

TRAIN_SEASONS = range(2018, 2024)   # 2018-19 .. 2023-24
CALIB_SEASON = 2024                 # isotonic hazard calibration, out-of-sample
TEST_SEASON = 2025                  # the untouched holdout
STRIDE = 7                          # keep every 7th alive day (weight 7)
NF_FRAC = 0.2                       # never-failer buildings sampled per season
HORIZONS = ("2025-12-01", "2026-01-01", "2026-02-01")
CHUNK = 15                          # days per full-universe scoring chunk
rng = np.random.default_rng(10)

# ------------------------------------------------------------------ inputs (05's prelude)
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
viol = viol[viol.inspectiondate >= "2010-01-01"]
viol["season"] = season(viol.inspectiondate)

bd["season"] = season(bd.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()

bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc["lastd"] = bdc["day"]
bdc = bdc.sort_values("day")
vdc = (viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "day"})
       .sort_values("day"))
vdc["lastd"] = vdc["day"]
num, den = band_prep(bd, load_days())
bw["season"] = season(bw.day)
sbw = bw.groupby(["bbl", "season"])["n"].sum()
bwc = bw.sort_values(["bbl", "day"]).copy()
bwc["csum"] = bwc.groupby("bbl")["n"].cumsum()
bwc = bwc.sort_values("day")
lord, boiler = second_tier()
sc_df = sc.rename("c").reset_index()
blkd = bd.assign(blk=bd.bbl // 10000).groupby(["blk", "day"])["n"].sum().reset_index()
blkc = blkd.sort_values(["blk", "day"]).copy()
blkc["csum"] = blkc.groupby("blk")["n"].cumsum()
blkc = blkc.sort_values("day")
first55 = first_cold_day(load_days())

base = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                  "numfloors", "bldgarea", "cd"]].copy()
base["yearbuilt"] = base.yearbuilt.replace(0, np.nan)
base["altered"] = (base.yearalter1.fillna(0) > 0).astype(int)

# truth: failed48 building-days (01's label), heat-season only; first per season
nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]
truth = truth.merge(days[["day", "heat_season"]], on="day", how="left")
truth = truth[truth.heat_season.fillna(False).astype(bool)]
truth["season"] = season(truth.day)
fday_all = truth.groupby(["season", "bbl"]).day.min()

first_c = bd.groupby("bbl").day.min()
first_v = vdc.groupby("bbl").day.min()
first_ev = pd.concat([first_c, first_v], axis=1).min(axis=1)

wcols = ["day", "TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
         "SNOW", "AWND", "wday_num"]


def universe(S):
    """Buildings with any complaint/violation strictly before Oct 1 of season S."""
    start = pd.Timestamp(f"{S}-10-01")
    u = first_ev[first_ev < start].index
    return np.sort(np.intersect1d(u.to_numpy(), buildings.bbl.to_numpy()))


def heat_days(S):
    d = days[days.heat_season & (season(days.day) == S)].sort_values("day")
    return d.day.to_numpy()


def hist_col(s, yr, bbls):
    lvl = s.index.get_level_values(1)
    return pd.Series(bbls).map(s.xs(yr, level="season")).fillna(0).to_numpy() \
        if yr in lvl else 0.0


def season_static(S, bbls):
    """History features frozen as of the start of season S (05's X0)."""
    X0 = base[base.bbl.isin(bbls)].copy()
    X0["c_last1"] = hist_col(sc, S - 1, X0.bbl)
    X0["c_last2"] = X0.c_last1 + hist_col(sc, S - 2, X0.bbl)
    X0["v_last1"] = hist_col(sv, S - 1, X0.bbl)
    X0["v_last2"] = X0.v_last1 + hist_col(sv, S - 2, X0.bbl)
    X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, S - 2, X0.bbl) >= 5)).astype(int)
    X0 = X0.merge(band_rates(num, den, S, X0.bbl), on="bbl", how="left")
    X0["bw_last1"] = hist_col(sbw, S - 1, X0.bbl)
    X0 = add_second_tier(X0, lord, boiler, sc_df, S)
    for c in ("rate_frigid2", "rate_freezing2", "rate_cold2"):
        X0[c] = X0[c].fillna(0.0)
    return X0


def asof_before(keys, offset_days, right, cols, by="bbl"):
    """per-key state as of day + offset_days (01's machinery), row-aligned."""
    t = keys[[by, "day"]].copy()
    t["day"] = t.day + pd.Timedelta(days=offset_days)
    t["_i"] = np.arange(len(t))
    t = t.sort_values("day")
    r = pd.merge_asof(t, right, on="day", by=by, direction="backward")
    return r.sort_values("_i")[cols].reset_index(drop=True)


def add_dynamic(X, S):
    """Trailing windows, days-since, neighbors, season clock, weather. All strictly
    before the row's day (windows end at day-1): the one rule, same as 01."""
    a = asof_before(X, -1, bdc[["bbl", "day", "csum", "lastd"]], ["csum", "lastd"])
    at_d1 = a.csum.fillna(0).to_numpy()
    X["days_since_c"] = ((X.day.to_numpy() - a.lastd.to_numpy())
                         / np.timedelta64(1, "D"))
    for w in (7, 14, 30):
        X[f"c_prev{w}"] = at_d1 - asof_before(
            X, -(w + 1), bdc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy()
    av = asof_before(X, -1, vdc[["bbl", "day", "lastd"]], ["lastd"])
    X["days_since_v"] = ((X.day.to_numpy() - av.lastd.to_numpy())
                         / np.timedelta64(1, "D"))
    X["bw_prev14"] = (
        asof_before(X, -1, bwc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy()
        - asof_before(X, -15, bwc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy())
    X["c_prev2"] = at_d1 - asof_before(
        X, -3, bdc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy()
    X["blk"] = X.bbl // 10000
    blk2 = (asof_before(X, -1, blkc[["blk", "day", "csum"]], ["csum"], by="blk")
            .csum.fillna(0).to_numpy()
            - asof_before(X, -3, blkc[["blk", "day", "csum"]], ["csum"], by="blk")
            .csum.fillna(0).to_numpy())
    X["nb_block_2d"] = np.clip(blk2 - X.c_prev2.to_numpy(), 0, None)
    X = X.drop(columns="blk")
    X["days_into_cold"] = days_into_cold(X.day, np.full(len(X), S), first55)
    for c in ("days_since_c", "days_since_v"):
        X[c] = X[c].fillna(NEVER)
    X = X.merge(days[wcols], on="day", how="left")
    return X


def season_rows(S):
    """Weighted hazard rows for season S: all failers' at-risk days (strided) +
    their event day; a NF_FRAC sample of never-failers' days (strided)."""
    uni = universe(S)
    D = heat_days(S)
    nb, m = len(uni), len(D)
    f = fday_all.xs(S, level="season") if S in fday_all.index.get_level_values(0) else pd.Series(dtype="datetime64[ns]")
    f = f[f.index.isin(uni)]
    fidx = pd.Series(np.searchsorted(D, f.to_numpy()), index=f.index)
    end = np.full(nb, m - 1, dtype=np.int32)                 # censored at May 31
    is_f = np.isin(uni, fidx.index.to_numpy())
    end[is_f] = fidx.reindex(uni[is_f]).to_numpy().astype(np.int32)

    nf_keep = rng.random(nb) < NF_FRAC                       # building-level sample
    t = np.tile(np.arange(m, dtype=np.int32), nb)
    b = np.repeat(np.arange(nb, dtype=np.int32), m)
    alive = t <= end[b]
    event = alive & is_f[b] & (t == end[b])
    strided = (t % STRIDE) == (uni[b] % STRIDE)
    keep = alive & (event | strided) & (is_f[b] | nf_keep[b])
    b, t, event = b[keep], t[keep], event[keep]

    w = np.where(event, 1.0, np.where(is_f[b], STRIDE, STRIDE / NF_FRAC))
    X = pd.DataFrame({"bbl": uni[b], "day": D[t], "y": event, "w": w})
    X = X.merge(season_static(S, uni), on="bbl", how="left")
    X = add_dynamic(X, S)
    # time discipline, asserted like 01
    assert (X.day.to_numpy() <= pd.Series(X.bbl.map(f)).fillna(pd.Timestamp.max)
            .to_numpy()).all(), "row after first failure!"
    chk = (X.bbl.map(sc.xs(S - 1, level="season")).fillna(0).to_numpy()
           if S - 1 in sc.index.get_level_values(1) else np.zeros(len(X)))
    assert (X.c_last1.to_numpy() == chk).all(), "history leak!"
    print(f"  season {S}-{str(S + 1)[2:]}: {nb:,} at risk, {is_f.sum():,} fail; "
          f"{len(X):,} rows ({event.sum():,} events)", flush=True)
    return X


def season_hazard_matrix(S, predict):
    """Raw hazard for EVERY universe building on EVERY heat-season day of S,
    scored in day chunks. Returns (uni, D, H[nb, m] float32)."""
    uni = universe(S)
    D = heat_days(S)
    nb, m = len(uni), len(D)
    X0 = season_static(S, uni).set_index("bbl").reindex(uni).reset_index()
    H = np.zeros((nb, m), dtype=np.float32)
    for lo in range(0, m, CHUNK):
        idx = np.arange(lo, min(lo + CHUNK, m))
        X = pd.DataFrame({"bbl": np.tile(uni, len(idx)),
                          "day": np.repeat(D[idx], nb)})
        X = X.merge(X0, on="bbl", how="left")
        X = add_dynamic(X, S)
        p = predict(X[FEATS]).astype(np.float32)
        H[:, idx] = p.reshape(len(idx), nb).T
        print(f"  scored days {lo}..{idx[-1]} of {m}", flush=True)
    return uni, D, H


def first_fail_idx(S, uni, D):
    f = fday_all.xs(S, level="season")
    f = f[f.index.isin(uni)]
    out = np.full(len(uni), len(D), dtype=np.int64)          # len(D) = never fails
    pos = np.searchsorted(uni, f.index.to_numpy())
    out[pos] = np.searchsorted(D, f.to_numpy())
    return out


# ------------------------------------------------------------------ train M10
print("building hazard rows (train seasons 2018-2023):")
rows = pd.concat([season_rows(S) for S in TRAIN_SEASONS], ignore_index=True)
print(f"total {len(rows):,} rows, {int(rows.y.sum()):,} events "
      f"(weighted base hazard {np.average(rows.y, weights=rows.w):.5f}/day)")
m10, backend = make_model()
m10.fit(rows[FEATS], rows.y, sample_weight=rows.w)
print(f"trained {backend} hazard model")
if backend == "xgboost":
    m10.save_model(OUT / "heat_model_hazard.json")
    print(f"saved {OUT / 'heat_model_hazard.json'}")
del rows


def predict(A):
    return m10.predict_proba(A)[:, 1]


# ------------------------------------------------------------------ calibrate on 2024-25
print(f"\nscoring calibration season {CALIB_SEASON} (full universe, every day):")
uni_c, D_c, H_c = season_hazard_matrix(CALIB_SEASON, predict)
fid_c = first_fail_idx(CALIB_SEASON, uni_c, D_c)
nb, m = H_c.shape
t = np.tile(np.arange(m), nb)
b = np.repeat(np.arange(nb), m)
at_risk = t <= np.minimum(fid_c[b], m - 1)
keep = at_risk & (((t % 2) == 0) | (t == fid_c[b]))          # every 2nd day + events
h_raw = H_c[b[keep], t[keep]]
y_c = (t[keep] == fid_c[b[keep]]).astype(float)
pd.DataFrame({"h_raw": h_raw, "y": y_c}).to_csv(
    OUT / "hazard_calibration.csv", index=False)
from sklearn.isotonic import IsotonicRegression
iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
iso.fit(h_raw, y_c)
print(f"isotonic fit on {len(h_raw):,} at-risk pairs "
      f"({int(y_c.sum()):,} events) from {CALIB_SEASON}-{str(CALIB_SEASON + 1)[2:]}")
del H_c, h_raw, y_c, t, b, at_risk, keep

# ------------------------------------------------------------------ test on 2025-26
print(f"\nscoring test season {TEST_SEASON} (full universe, every day):")
uni, D, H = season_hazard_matrix(TEST_SEASON, predict)
fid = first_fail_idx(TEST_SEASON, uni, D)
nb, m = H.shape
h = np.clip(iso.predict(H.ravel()).reshape(nb, m), 1e-7, 0.999)

# at-risk survival: hazards after a realized failure are never consumed
cumlog = np.cumsum(np.log1p(-h), axis=1)                     # log S(t), t inclusive
col = np.minimum(np.arange(m)[None, :], fid[:, None].clip(max=m - 1))
logS_atrisk = np.take_along_axis(cumlog, col, axis=1)        # frozen past failure

eval_rows = []
print("\nS(t) calibration at horizons (predicted vs realized first-failure share, "
      "by decile of predicted):")
for hz in HORIZONS:
    hidx = int(np.searchsorted(D, np.datetime64(hz, "ns")))  # days strictly before hz
    pred = 1.0 - np.exp(logS_atrisk[:, hidx - 1])
    real = (fid < hidx).astype(float)
    dec = pd.qcut(pd.Series(pred).rank(method="first"), 10, labels=False)
    tab = pd.DataFrame({"pred": pred, "real": real, "dec": dec}) \
        .groupby("dec").agg(n=("real", "size"), mean_pred=("pred", "mean"),
                            realized=("real", "mean")).reset_index()
    tab["gap_pp"] = (tab.mean_pred - tab.realized) * 100
    print(f"\n  by {hz} (realized overall {real.mean():.3f}, "
          f"max |gap| {tab.gap_pp.abs().max():.1f}pp):")
    print(tab.round(3).to_string(index=False))
    for _, r in tab.iterrows():
        eval_rows.append(dict(kind="horizon_calibration", horizon=hz,
                              decile=int(r.dec), n=int(r.n),
                              mean_pred=round(r.mean_pred, 4),
                              realized=round(r.realized, 4),
                              gap_pp=round(r.gap_pp, 2)))

# time-dependent C-index: pair (i fails at ti, j still at risk at ti); concordant
# when predicted cumulative risk AT ti ranks i above j. Both curves use only
# at-risk information through ti.
fail_i = np.where(fid < m)[0]
ii = rng.choice(fail_i, size=500_000)
jj = rng.integers(0, nb, size=500_000)
ok = fid[jj] > fid[ii]
ii, jj = ii[ok], jj[ok]
ri = 1 - np.exp(cumlog[ii, fid[ii]])
rj = 1 - np.exp(cumlog[jj, fid[ii]])
c_index = float((ri > rj).mean() + 0.5 * (ri == rj).mean())
print(f"\nC-index on first-failure timing: {c_index:.3f} "
      f"({len(ii):,} comparable pairs)")
eval_rows.append(dict(kind="summary", metric="c_index", value=round(c_index, 4),
                      n=len(ii)))

# expected failure week (conditional on failing), from the at-risk path
S_prev = np.exp(np.concatenate([np.zeros((nb, 1)), cumlog[:, :-1]], axis=1))
f_t = S_prev * h                                             # P(first failure on day t)
mask = np.arange(m)[None, :] <= np.minimum(fid, m - 1)[:, None]
f_t = f_t * mask
p_fail = f_t.sum(axis=1)
week = np.arange(m) // 7
exp_week = (f_t * week[None, :]).sum(axis=1) / np.clip(p_fail, 1e-9, None)
cum = np.cumsum(f_t, axis=1)
med_idx = np.argmax(cum >= 0.5, axis=1)
median_week = np.where(cum[:, -1] >= 0.5, med_idx // 7, -1)  # -1: never crosses 50%

pd.DataFrame({"bbl": uni, "p_fail_season": p_fail.round(4),
              "expected_failure_week": exp_week.round(2),
              "median_failure_week": median_week,
              "week0_start": str(pd.Timestamp(D[0]).date())}) \
    .to_csv(OUT / "expected_failure_week.csv", index=False)

# preseason top-1000 (by predicted season failure risk): predicted vs realized week
top = np.argsort(-p_fail)[:1000]
top_failed = top[fid[top] < m]
err = np.abs(exp_week[top_failed] - (fid[top_failed] // 7))
med_err = float(np.median(err))
print(f"top-1000 by predicted season risk: {len(top_failed)} failed; "
      f"median |expected - realized| failure week error: {med_err:.1f} weeks")
eval_rows.append(dict(kind="summary", metric="top1000_median_week_error_weeks",
                      value=round(med_err, 2), n=len(top_failed)))
eval_rows.append(dict(kind="summary", metric="top1000_n_failed",
                      value=len(top_failed), n=1000))
eval_rows.append(dict(kind="summary", metric="universe", value=nb, n=nb))
eval_rows.append(dict(kind="summary", metric="n_failed_2025_26",
                      value=int((fid < m).sum()), n=nb))
pd.DataFrame(eval_rows).to_csv(OUT / "hazard_eval.csv", index=False)
print(f"\nwrote {OUT / 'hazard_eval.csv'} and {OUT / 'expected_failure_week.csv'}")
print("NOTE: weather observed throughout (backtest); the live product must label "
      "climatology beyond the 7-day forecast.")
