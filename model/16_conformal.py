"""T8 - conformal risk control: alert thresholds with a distribution-free guarantee.

One fixed model (trained on panel seasons 2018-2022, strictly before every
calibration day) is scored 05-style over the full history universe on every
TMIN<32 heat-season day of 2023-24 and 2024-25 (the calibration days), then on
the held-out 2025-26 cold days (the test winter, touched once).

Risk controlled: FNR = share of that day's failed48 buildings (within the
scored universe) whose score fell below the threshold. Loss is per calendar
day, bounded in [0,1]. Conformal risk control (Angelopoulos et al. 2022) picks,
per alpha, the LARGEST threshold lambda whose calibration risk satisfies
    (n/(n+1)) * Rhat(lambda) + 1/(n+1) <= alpha        (B = 1),
so the guarantee E[FNR] <= alpha holds by construction, no distributional
assumptions. Two alphas: 0.10 (the "broad" tier, misses <10% of failures) and
0.25 (the "strict" tier, fewer alerts).

The threshold is also expressed as a calibrated probability (isotonic fit on
the calibration days' full-universe pairs, M3's recipe): a monotone transform,
so thresholding p instead of the raw score alerts the identical set of
buildings and inherits the same guarantee.

Run from the repo root:  python model/16_conformal.py
Writes: model/out/conformal_thresholds.json, model/out/conformal_days.csv
"""

import json
from datetime import date

import numpy as np
import pandas as pd
from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, make_model, season,
                    second_tier)

TRAIN_MAX = 2022                    # model sees nothing after the 2022-23 season
CALIB_SEASONS = (2023, 2024)        # chronologically after training, before the test
TEST_SEASON = 2025                  # the untouched holdout winter
ALPHAS = {"broad": 0.10, "strict": 0.25}

# ------------------------------------------------------------------ inputs (05's prelude)
days = load_days()
panel = pd.read_csv(OUT / "panel.csv", parse_dates=["day"])
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
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()

bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc["lastd"] = bdc["day"]
bdc = bdc.sort_values("day")
vdc = (viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "day"})
       .sort_values("day"))
vdc["lastd"] = vdc["day"]
active = bdc.bbl.unique()
v_active = vdc.bbl.unique()
num, den = band_prep(bd, load_days())
bw["season"] = season(bw.day)
sbw = bw.groupby(["bbl", "season"])["n"].sum()
bwc = bw.sort_values(["bbl", "day"]).copy()
bwc["csum"] = bwc.groupby("bbl")["n"].cumsum()
bwc = bwc.sort_values("day")
bw_active = bwc.bbl.unique()
lord, boiler = second_tier()
sc_df = sc.rename("c").reset_index()
blkd = bd.assign(blk=bd.bbl // 10000).groupby(["blk", "day"])["n"].sum().reset_index()
blkc = blkd.sort_values(["blk", "day"]).copy()
blkc["csum"] = blkc.groupby("blk")["n"].cumsum()
blkc = blkc.sort_values("day")
blk_keys = blkc.blk.unique()
first55 = first_cold_day(load_days())

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


def asof_at(d, right, keys, cols, by="bbl"):
    t = pd.DataFrame({by: keys, "day": d})
    r = pd.merge_asof(t.sort_values("day"), right, on="day", by=by,
                      direction="backward")
    return r.set_index(by)[cols]


def csum_asof(d):
    return asof_at(d, bdc[["bbl", "day", "csum"]], active, ["csum"])["csum"].fillna(0)


def season_static(S):
    """05's X0: history features frozen as of the start of season S."""
    X0 = base.copy()
    X0["c_last1"] = hist_col(sc, S - 1)
    X0["c_last2"] = X0.c_last1 + hist_col(sc, S - 2)
    X0["v_last1"] = hist_col(sv, S - 1)
    X0["v_last2"] = X0.v_last1 + hist_col(sv, S - 2)
    X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, S - 2) >= 5)).astype(int)
    X0 = X0.merge(band_rates(num, den, S, X0.bbl), on="bbl", how="left")
    X0["bw_last1"] = hist_col(sbw, S - 1)
    return add_second_tier(X0, lord, boiler, sc_df, S)


def score_day(m, X0, drow, S):
    """Full-universe scores for one cold day; returns (scores by bbl, failed set)."""
    d = drow.day
    pos = set(truth.loc[truth.day == d, "bbl"])
    X = X0.copy()
    a = asof_at(d - pd.Timedelta(days=1), bdc[["bbl", "day", "csum", "lastd"]],
                active, ["csum", "lastd"])
    c1 = a.csum.fillna(0)
    for w in (7, 14, 30):
        X[f"c_prev{w}"] = (c1 - csum_asof(d - pd.Timedelta(days=w + 1))) \
            .reindex(X.bbl).fillna(0).to_numpy()
    X["days_since_c"] = (d - a.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    av = asof_at(d - pd.Timedelta(days=1), vdc[["bbl", "day", "lastd"]],
                 v_active, ["lastd"])
    X["days_since_v"] = (d - av.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    bw1 = asof_at(d - pd.Timedelta(days=1), bwc[["bbl", "day", "csum"]],
                  bw_active, ["csum"])["csum"].fillna(0)
    bw15 = asof_at(d - pd.Timedelta(days=15), bwc[["bbl", "day", "csum"]],
                   bw_active, ["csum"])["csum"].fillna(0)
    X["bw_prev14"] = (bw1 - bw15).reindex(X.bbl).fillna(0).to_numpy()
    X["c_prev2"] = (c1 - csum_asof(d - pd.Timedelta(days=3))) \
        .reindex(X.bbl).fillna(0).to_numpy()
    nb = (asof_at(d - pd.Timedelta(days=1), blkc[["blk", "day", "csum"]],
                  blk_keys, ["csum"], by="blk")["csum"].fillna(0)
          - asof_at(d - pd.Timedelta(days=3), blkc[["blk", "day", "csum"]],
                    blk_keys, ["csum"], by="blk")["csum"].fillna(0))
    X["nb_block_2d"] = np.clip(nb.reindex(X.bbl // 10000).fillna(0).to_numpy()
                               - X.c_prev2.to_numpy(), 0, None)
    X["days_into_cold"] = days_into_cold([d], [S], first55)[0]
    X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]
    pos &= set(X.bbl)
    for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
              "SNOW", "AWND", "wday_num"]:
        X[c] = drow[c]
    return pd.Series(m.predict_proba(X[FEATS])[:, 1], index=X.bbl), pos


# ------------------------------------------------------------------ one fixed model
train = panel[(panel.season >= 2018) & (panel.season <= TRAIN_MAX)]
m, backend = make_model()
m.fit(train[FEATS], train.failed48)
print(f"model: {backend}, trained on {len(train):,} rows, seasons 2018-{TRAIN_MAX}")

# ------------------------------------------------------------------ score every day
per_day = []        # dicts: split, day, scores (np), fail_scores (np sorted), n_fail
pairs = []          # pooled (score, y) for the isotonic p-scale (calibration days only)
rng = np.random.default_rng(8)
for split, seasons in (("calib", CALIB_SEASONS), ("test", (TEST_SEASON,))):
    for S in seasons:
        X0 = season_static(S)
        td = days[days.heat_season & (days.TMIN < 32) & (season(days.day) == S)] \
            .sort_values("day")
        print(f"{split} season {S}-{str(S + 1)[2:]}: {len(td)} cold days", flush=True)
        for _, drow in td.iterrows():
            s_, pos = score_day(m, X0, drow, S)
            fs = np.sort(s_.reindex(list(pos)).to_numpy())
            per_day.append(dict(split=split, day=drow.day.date(), S=S,
                                scores=s_.to_numpy(), fail_scores=fs, n_fail=len(fs)))
            if split == "calib":
                idx = rng.choice(len(s_), size=min(2000, len(s_)), replace=False)
                pairs.append(pd.DataFrame({"score": s_.to_numpy()[idx],
                                           "y": np.isin(s_.index.to_numpy()[idx],
                                                        list(pos))}))

calib = [p for p in per_day if p["split"] == "calib" and p["n_fail"] > 0]
test = [p for p in per_day if p["split"] == "test" and p["n_fail"] > 0]
n = len(calib)
print(f"\ncalibration days with failures: {n} | test days with failures: {len(test)}")


def fnr_curve(day_list, lams):
    """mean over days of per-day FNR at each lambda (searchsorted on sorted scores)."""
    per = np.stack([np.searchsorted(p["fail_scores"], lams, side="left") / p["n_fail"]
                    for p in day_list])
    return per.mean(axis=0)


# candidate thresholds: the pooled calibration failure scores (where FNR can change)
lams = np.unique(np.concatenate([p["fail_scores"] for p in calib]))
rhat = fnr_curve(calib, lams)
bound = (n / (n + 1)) * rhat + 1.0 / (n + 1)        # B = 1: loss is in [0,1]

# the isotonic p-scale (M3's recipe, fit on calibration-day pairs only)
from sklearn.isotonic import IsotonicRegression
pp = pd.concat(pairs, ignore_index=True)
iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
iso.fit(pp.score, pp.y.astype(float))

tiers, day_rows = {}, []
for name, alpha in ALPHAS.items():
    ok = bound <= alpha
    if not ok.any():
        print(f"tier {name}: NO threshold satisfies alpha={alpha} (n={n} too small?)")
        continue
    lam = float(lams[ok][-1])                        # largest lambda still guaranteed
    r_cal = float(fnr_curve(calib, np.array([lam]))[0])
    r_test = float(fnr_curve(test, np.array([lam]))[0])
    vols = np.array([(p["scores"] >= lam).sum() for p in test])
    tiers[name] = dict(
        alpha=alpha, **{"lambda": lam},
        p_threshold=round(min(float(iso.predict([lam])[0]), 0.99), 4),
        n_calib_days=n, calib_fnr=round(r_cal, 4),
        conformal_bound=round(float((n / (n + 1)) * r_cal + 1 / (n + 1)), 4),
        realized_test_fnr=round(r_test, 4),
        guarantee_held=bool(r_test <= alpha),
        mean_alert_volume=round(float(vols.mean()), 1),
        median_alert_volume=int(np.median(vols)))
    print(f"tier {name} (alpha={alpha}): lambda={lam:.5f} "
          f"(~p={tiers[name]['p_threshold']:.2f}) | calib FNR {r_cal:.3f} "
          f"(bound {tiers[name]['conformal_bound']:.3f}) | "
          f"TEST FNR {r_test:.3f} {'<=' if r_test <= alpha else '> MISS'} {alpha} | "
          f"alerts/cold-day mean {vols.mean():.0f}, median {np.median(vols):.0f}")

for p in per_day:
    row = dict(split=p["split"], day=p["day"], n_fail=p["n_fail"],
               n_scored=len(p["scores"]))
    for name, t in tiers.items():
        lam = t["lambda"]
        row[f"fnr_{name}"] = (round(float((p["fail_scores"] < lam).mean()), 4)
                              if p["n_fail"] else np.nan)
        row[f"volume_{name}"] = int((p["scores"] >= lam).sum())
    day_rows.append(row)
pd.DataFrame(day_rows).to_csv(OUT / "conformal_days.csv", index=False)

out = dict(
    generated=str(date.today()),
    method="conformal risk control (Angelopoulos et al.), day-level FNR loss, B=1",
    model=f"{backend} trained on panel seasons 2018-{TRAIN_MAX} "
          "(strictly pre-dates every calibration day)",
    calib_seasons=list(CALIB_SEASONS), n_calib_days=n,
    test_season="2025-26", n_test_days=len(test),
    note="p_threshold is the threshold on the isotonic-calibrated probability "
         "scale (monotone, alerts the identical set); exact for this model, "
         "approximate when applied to the production twin's p_calibrated.",
    tiers=tiers)
(OUT / "conformal_thresholds.json").write_text(json.dumps(out, indent=2))
print(f"\nwrote {OUT / 'conformal_thresholds.json'} and {OUT / 'conformal_days.csv'}")
