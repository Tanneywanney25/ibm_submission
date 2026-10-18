"""T10 / M10b - horizon-level recalibration of M10's survival curves.

M10 (18_hazard.py) discriminates (C-index 0.871) but its S(t) is overconfident
in the top two deciles (8-42pp): ~240 compounded daily hazards amplify small
per-day overestimates, and the day-level isotonic never sees the product.
M10b adds a SECOND isotonic at the horizon level: cumulative predicted risk
1 - S(t) -> realized first-failure share, fit on the 2024-25 season's
full-universe at-risk curves (out-of-sample for the model, which trained on
2018-2023), then applied to 2025-26 and verified ONCE at the Dec 1 / Jan 1 /
Feb 1 horizons. The fit pools strided day indices; the three 2024-25 horizon
day-indices are held out of the fit and used as an in-season sanity check
before the holdout is touched.

Monotone in t by construction: g isotonic and R(t) nondecreasing along each
building's at-risk path, so the recalibrated curve is still a CDF; the
per-day first-failure mass is its increment, which also recomputes the
expected failure week. Ranking at a fixed t is preserved up to ties, so the
C-index is recomputed only to confirm it did not move.

Needs 18's outputs in model/out/: heat_model_hazard.json (the trained M10)
and hazard_calibration.csv (the day-level raw-hazard/outcome pairs). Does not
overwrite anything 18 wrote - all outputs carry the _recal suffix.

Run from the repo root:  python model/19_hazard_recal.py
Writes: model/out/hazard_recal_map.csv (the horizon isotonic's knots),
        model/out/hazard_eval_recal.csv, model/out/expected_failure_week_recal.csv
"""

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, season, second_tier)

CALIB_SEASON = 2024                 # horizon isotonic fit here, out-of-sample for M10
TEST_SEASON = 2025                  # the untouched holdout, looked at once
FIT_STRIDE = 7                      # day indices pooled into the horizon fit
HORIZONS_CAL = ("2024-12-01", "2025-01-01", "2025-02-01")
HORIZONS = ("2025-12-01", "2026-01-01", "2026-02-01")
CHUNK = 15                          # days per full-universe scoring chunk
rng = np.random.default_rng(10)

# ------------------------------------------------------------------ inputs
# (prelude copied verbatim from 18_hazard.py, which must stay reproducible as-is)
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
    t = keys[[by, "day"]].copy()
    t["day"] = t.day + pd.Timedelta(days=offset_days)
    t["_i"] = np.arange(len(t))
    t = t.sort_values("day")
    r = pd.merge_asof(t, right, on="day", by=by, direction="backward")
    return r.sort_values("_i")[cols].reset_index(drop=True)


def add_dynamic(X, S):
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


def season_hazard_matrix(S, predict):
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
    out = np.full(len(uni), len(D), dtype=np.int64)
    pos = np.searchsorted(uni, f.index.to_numpy())
    out[pos] = np.searchsorted(D, f.to_numpy())
    return out
# ------------------------------------------------------------------ end of 18's prelude


def cumrisk_atrisk(H, fid, iso_day):
    """Day-calibrated hazards -> frozen-past-failure cumulative risk R[nb, m]:
    R[b, t] = 1 - S(t) along b's at-risk path, constant after a realized failure."""
    nb, m = H.shape
    h = np.clip(iso_day.predict(H.ravel()).reshape(nb, m), 1e-7, 0.999)
    cumlog = np.cumsum(np.log1p(-h), axis=1)
    col = np.minimum(np.arange(m)[None, :], fid[:, None].clip(max=m - 1))
    return 1.0 - np.exp(np.take_along_axis(cumlog, col, axis=1))


def horizon_table(pred, real):
    dec = pd.qcut(pd.Series(pred).rank(method="first"), 10, labels=False)
    tab = pd.DataFrame({"pred": pred, "real": real, "dec": dec}) \
        .groupby("dec").agg(n=("real", "size"), mean_pred=("pred", "mean"),
                            realized=("real", "mean")).reset_index()
    tab["gap_pp"] = (tab.mean_pred - tab.realized) * 100
    return tab


# ------------------------------------------------------------------ M10 + day isotonic, reloaded
from xgboost import XGBClassifier
m10 = XGBClassifier()
m10.load_model(OUT / "heat_model_hazard.json")
print(f"loaded M10 from {OUT / 'heat_model_hazard.json'}")

pairs = pd.read_csv(OUT / "hazard_calibration.csv")
iso_day = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
iso_day.fit(pairs.h_raw, pairs.y)
print(f"day-level isotonic refit on {len(pairs):,} saved pairs "
      f"({int(pairs.y.sum()):,} events)")


def predict(A):
    return m10.predict_proba(A)[:, 1]


# ------------------------------------------------------------------ fit g on 2024-25 curves
print(f"\nscoring fit season {CALIB_SEASON} (full universe, every day):")
uni_c, D_c, H_c = season_hazard_matrix(CALIB_SEASON, predict)
fid_c = first_fail_idx(CALIB_SEASON, uni_c, D_c)
R_c = cumrisk_atrisk(H_c, fid_c, iso_day)
del H_c
nb_c, m_c = R_c.shape

hidx_c = {hz: int(np.searchsorted(D_c, np.datetime64(hz, "ns"))) for hz in HORIZONS_CAL}
fit_days = [d for d in range(0, m_c, FIT_STRIDE)
            if d + 1 not in hidx_c.values()]                 # hold the anchors out
x_fit = R_c[:, fit_days].ravel()
y_fit = (fid_c[:, None] <= np.asarray(fit_days)[None, :]).ravel().astype(float)
iso_hz = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
iso_hz.fit(x_fit, y_fit)
print(f"horizon isotonic fit on {len(x_fit):,} (building, day) pairs "
      f"from {len(fit_days)} strided days of {CALIB_SEASON}-{str(CALIB_SEASON + 1)[2:]}")
pd.DataFrame({"cum_risk_raw": iso_hz.X_thresholds_,
              "first_failure_share": iso_hz.y_thresholds_}) \
    .to_csv(OUT / "hazard_recal_map.csv", index=False)

print("\nin-season check on the held-out 2024-25 horizon days (after g):")
for hz, hidx in hidx_c.items():
    pred = iso_hz.predict(R_c[:, hidx - 1])
    real = (fid_c < hidx).astype(float)
    tab = horizon_table(pred, real)
    print(f"\n  by {hz} (realized overall {real.mean():.3f}, "
          f"max |gap| {tab.gap_pp.abs().max():.1f}pp):")
    print(tab.round(3).to_string(index=False))
del R_c

# ------------------------------------------------------------------ verify once on 2025-26
print(f"\nscoring test season {TEST_SEASON} (full universe, every day):")
uni, D, H = season_hazard_matrix(TEST_SEASON, predict)
fid = first_fail_idx(TEST_SEASON, uni, D)
R = cumrisk_atrisk(H, fid, iso_day)
del H
nb, m = R.shape
Rr = iso_hz.predict(R.ravel()).reshape(nb, m)                # the M10b curve

eval_rows = []
print("\nrecalibrated S(t) at horizons (predicted vs realized first-failure "
      "share, by decile of predicted):")
for hz in HORIZONS:
    hidx = int(np.searchsorted(D, np.datetime64(hz, "ns")))
    pred, real = Rr[:, hidx - 1], (fid < hidx).astype(float)
    tab = horizon_table(pred, real)
    print(f"\n  by {hz} (realized overall {real.mean():.3f}, "
          f"max |gap| {tab.gap_pp.abs().max():.1f}pp):")
    print(tab.round(3).to_string(index=False))
    for _, r in tab.iterrows():
        eval_rows.append(dict(kind="horizon_calibration", horizon=hz,
                              decile=int(r.dec), n=int(r.n),
                              mean_pred=round(r.mean_pred, 4),
                              realized=round(r.realized, 4),
                              gap_pp=round(r.gap_pp, 2)))

# C-index after g (monotone, so only isotonic ties can move it)
fail_i = np.where(fid < m)[0]
ii = rng.choice(fail_i, size=500_000)
jj = rng.integers(0, nb, size=500_000)
ok = fid[jj] > fid[ii]
ii, jj = ii[ok], jj[ok]
ri, rj = Rr[ii, fid[ii]], Rr[jj, fid[ii]]
c_index = float((ri > rj).mean() + 0.5 * (ri == rj).mean())
print(f"\nC-index on first-failure timing (recalibrated): {c_index:.3f} "
      f"({len(ii):,} comparable pairs)")
eval_rows.append(dict(kind="summary", metric="c_index", value=round(c_index, 4),
                      n=len(ii)))

# expected failure week from the recalibrated curve: per-day first-failure
# mass is the increment of the (frozen-past-failure, hence already masked) CDF
f_t = np.diff(Rr, axis=1, prepend=0.0)
p_fail = Rr[:, -1]
week = np.arange(m) // 7
exp_week = (f_t * week[None, :]).sum(axis=1) / np.clip(p_fail, 1e-9, None)
cum = np.cumsum(f_t, axis=1)
med_idx = np.argmax(cum >= 0.5, axis=1)
median_week = np.where(cum[:, -1] >= 0.5, med_idx // 7, -1)

pd.DataFrame({"bbl": uni, "p_fail_season": p_fail.round(4),
              "expected_failure_week": exp_week.round(2),
              "median_failure_week": median_week,
              "week0_start": str(pd.Timestamp(D[0]).date())}) \
    .to_csv(OUT / "expected_failure_week_recal.csv", index=False)

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
pd.DataFrame(eval_rows).to_csv(OUT / "hazard_eval_recal.csv", index=False)
print(f"\nwrote {OUT / 'hazard_eval_recal.csv'}, "
      f"{OUT / 'expected_failure_week_recal.csv'} and "
      f"{OUT / 'hazard_recal_map.csv'}")
print("NOTE: weather observed throughout (backtest); the live product must label "
      "climatology beyond the 7-day forecast.")
