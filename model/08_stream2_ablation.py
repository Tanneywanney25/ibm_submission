"""Ablation: do Stream 2's leak-free features lift precision@k over the current model?

Nothing here changes Stream 5's schema. 01_build_panel.py's panel.csv is read as-is;
candidate columns are merged onto it per (bbl, season), each variant is trained the
same way 02_train.py trains (XGBoost + HistGBC averaged when XGBoost exists), and
every variant is scored on the same 71 test cold days with 03_evaluate.py's protocol.

Variants (feature lists only differ):
  V0 current        FEATS as committed (boiler_defects / fuel_oil are all-time snapshots)
  V1a boiler-clean  V0 with the two boiler columns recomputed from records dated before
                    October 1 of the row's season (no future reports in any row)
  V1b boiler-rich   V1a + heavy-oil (No. 4 / No. 6) flag, days since last DOB inspection,
                    overdue flag, late-filing count, defects in the last three years
  V2 long-window    V0 + expanding-window reaction rates (ALL prior seasons, not two),
                    the widened <25 F rate, the sub-freezing rate, the cold multiplier,
                    the zero-mild and forecast-only flags, seasons active
  V3 both           V1b + V2's additions

All candidate columns are derived inside this pipeline at the bbl level, from the same
building-day counts and the raw boiler tables, so there is no building_id -> bbl
aggregation step; the mapping diagnostic at the end measures what that step would
have cost had the Stream 2 CSV been merged instead.

Run from the repo root:  python model/08_stream2_ablation.py [max_days]
Writes: model/out/ablation_stream2.csv, ablation_stream2_summary.csv,
        ablation_stream2_paired.csv, ablation_stream2_importance.csv
"""

import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, season, second_tier)

KS = (100, 500, 1000, 2500)
SEASONS = list(range(2018, 2026))
ST = DATA / "second_tier"
t_start = time.time()


def log(msg):
    print(f"[{time.time() - t_start:6.0f} s] {msg}", flush=True)


# ------------------------------------------------------------------ inputs (as 03)
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
log(f"panel {len(panel):,} rows, {panel.season.nunique()} seasons")

# ------------------------------------------------------------------ candidate 1: expanding-window reaction features
num, den = band_prep(bd, days)
d25 = days[days.heat_season].copy()
d25["season"] = season(d25.day)
bdd25 = bd[["bbl", "day"]].merge(d25.loc[d25.TMIN < 25, ["day", "season"]], on="day", how="inner")
num25 = bdd25.groupby(["bbl", "season"]).size().rename("n25")
den25 = d25[d25.TMIN < 25].groupby("season").size().rename("d25")


def long_window(S):
    """Reaction features from ALL seasons before S (2017-18 onward): leak-free by construction."""
    prior_mask = num.index.get_level_values("season") < S
    n = num[prior_mask].groupby(["bbl", "band"], observed=True).sum().unstack(fill_value=0)
    dd = den[den.index.get_level_values("season") < S].groupby("band", observed=True).sum()
    f = pd.DataFrame(index=n.index)
    for b in ("frigid", "freezing", "cold", "mild"):
        col = n[b] if b in n.columns else 0
        f[f"n_{b}"] = col
        f[f"rate_{b}_all"] = col / dd.get(b, 1)
    n25s = num25[num25.index.get_level_values("season") < S].groupby("bbl").sum()
    d25s = den25[den25.index < S].sum()
    f["rate_frigid25_all"] = n25s.reindex(f.index).fillna(0) / max(d25s, 1)
    dsub = dd.get("frigid", 0) + dd.get("freezing", 0)
    f["rate_subfreezing_all"] = (f.n_frigid + f.n_freezing) / max(dsub, 1)
    f["cold_mult"] = f.rate_subfreezing_all / (f.rate_cold_all + 0.5 / max(dd.get("cold", 1), 1))
    f["zero_mild_prior"] = (f.n_mild == 0).astype(int)
    f["forecast_only_prior"] = ((f.n_mild == 0) & ((f.n_frigid + f.n_freezing) >= 1)).astype(int)
    act = num[prior_mask].groupby(["bbl", "season"]).sum()
    f["seasons_active_prior"] = (act > 0).groupby("bbl").sum().reindex(f.index).fillna(0)
    return f.drop(columns=["n_frigid", "n_freezing", "n_cold", "n_mild"]).reset_index().assign(season=S)


LW_COLS = ["rate_frigid_all", "rate_freezing_all", "rate_cold_all", "rate_mild_all", "rate_frigid25_all",
           "rate_subfreezing_all", "cold_mult", "zero_mild_prior", "forecast_only_prior", "seasons_active_prior"]
lw = pd.concat([long_window(S) for S in SEASONS], ignore_index=True)
log(f"long-window reaction features: {len(lw):,} (bbl, season) rows")

# ------------------------------------------------------------------ candidate 2: per-season boiler features
reg = pd.read_csv(DATA / "hpd_registrations.csv", low_memory=False)
reg["bbl"] = (reg.boroid * 1_000_000_000 + reg.block * 10_000 + reg.lot).astype("int64")
bin2bbl = reg.dropna(subset=["bin"]).astype({"bin": "int64"}).drop_duplicates("bin").set_index("bin")["bbl"]
bi = pd.read_csv(ST / "boiler_inspections.csv", dtype=str, keep_default_na=False)
bi["bbl"] = pd.to_numeric(bi.bin_number, errors="coerce").astype("Int64").map(bin2bbl)
bi = bi.dropna(subset=["bbl"]).copy()
bi["bbl"] = bi.bbl.astype("int64")
bi["date"] = pd.to_datetime(bi.inspection_date, format="%m/%d/%Y %H:%M:%S", errors="coerce")
bi = bi.dropna(subset=["date"])
bi["defect"] = bi.defects_exist.str.upper().eq("YES")
bi["late"] = (pd.to_numeric(bi.lff_45_days, errors="coerce").fillna(0) > 0) | \
             (pd.to_numeric(bi.lff_180_days, errors="coerce").fillna(0) > 0)
bf = pd.read_csv(ST / "boiler_fuel.csv", dtype=str, keep_default_na=False)
bf["bbl"] = pd.to_numeric(bf.bin, errors="coerce").astype("Int64").map(bin2bbl)
bf = bf.dropna(subset=["bbl"]).copy()
bf["bbl"] = bf.bbl.astype("int64")
bf["date"] = pd.to_datetime(bf.issuedate, errors="coerce")
bf = bf.dropna(subset=["date"])
fuel = bf.primaryfuel.str.upper()
bf["oil"] = fuel.str.contains("FUEL|OIL")
bf["heavy"] = fuel.str.contains("NO4|NO6")


def boiler_season(S):
    cut = pd.Timestamp(S, 10, 1)
    b = bi[bi.date < cut]
    g = b.groupby("bbl")
    f = pd.DataFrame({"boiler_defects_pre": g.defect.sum(), "boiler_reports_pre": g.size(),
                      "boiler_late_pre": g.late.sum(), "last_insp": g.date.max()})
    f["boiler_defects_3y"] = b[b.date >= cut - pd.Timedelta(days=3 * 365)].groupby("bbl").defect.sum()
    f["boiler_days_since_insp"] = (cut - f.last_insp).dt.days
    f["boiler_overdue"] = (f.boiler_days_since_insp > 365).astype(int)
    f = f.drop(columns="last_insp")
    ff = bf[bf.date < cut].groupby("bbl").agg(fuel_oil_pre=("oil", "max"), fuel_heavy_pre=("heavy", "max"))
    f = f.join(ff, how="outer")
    for c in ("boiler_defects_pre", "boiler_reports_pre", "boiler_late_pre", "boiler_defects_3y", "boiler_overdue",
              "fuel_oil_pre", "fuel_heavy_pre"):
        f[c] = f[c].fillna(0).astype(int)
    f["boiler_days_since_insp"] = f.boiler_days_since_insp.fillna(NEVER)
    return f.reset_index().assign(season=S)


BO_COLS = ["boiler_defects_pre", "boiler_reports_pre", "boiler_late_pre", "boiler_defects_3y",
           "boiler_days_since_insp", "boiler_overdue", "fuel_oil_pre", "fuel_heavy_pre"]
bo = pd.concat([boiler_season(S) for S in SEASONS], ignore_index=True)
log(f"per-season boiler features: {len(bo):,} (bbl, season) rows; "
    f"bbls with a pre-2025-10-01 defect {int((bo[bo.season == 2025].boiler_defects_pre > 0).sum()):,} "
    f"vs all-time snapshot {int((pd.read_csv(ST / 'bbl_boiler.csv').boiler_defects > 0).sum()):,}")

# ------------------------------------------------------------------ merge candidates onto the panel
FILL = {c: 0.0 for c in LW_COLS + BO_COLS}
FILL["boiler_days_since_insp"] = NEVER
panel = panel.merge(lw, on=["bbl", "season"], how="left").merge(bo, on=["bbl", "season"], how="left")
panel = panel.fillna(FILL)

V1A = [c for c in FEATS if c not in ("boiler_defects", "fuel_oil")] + ["boiler_defects_pre", "fuel_oil_pre"]
VARIANTS = {
    "V0 current": FEATS,
    "V1a boiler-clean": V1A,
    "V1b boiler-rich": V1A + ["fuel_heavy_pre", "boiler_days_since_insp", "boiler_overdue", "boiler_late_pre", "boiler_defects_3y"],
    "V2 long-window": FEATS + LW_COLS,
    "V3 both": V1A + ["fuel_heavy_pre", "boiler_days_since_insp", "boiler_overdue", "boiler_late_pre", "boiler_defects_3y"] + LW_COLS,
}

# ------------------------------------------------------------------ train every variant like 02_train.py
train = panel[(panel.season >= 2018) & (panel.season <= 2024)]
try:
    from xgboost import XGBClassifier
    HAVE_XGB = True
except ImportError:
    HAVE_XGB = False
log(f"training {len(VARIANTS)} variants on {len(train):,} rows (xgboost={'yes' if HAVE_XGB else 'no, sklearn only'})")
models, imps = {}, []
for name, feats in VARIANTS.items():
    ms = []
    if HAVE_XGB:
        m = XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
                          eval_metric="aucpr", tree_method="hist", n_jobs=-1)
        m.fit(train[feats], train.failed48)
        ms.append(m)
        imps.append(pd.DataFrame({"variant": name, "feature": feats, "importance": m.feature_importances_}))
    h = HistGradientBoostingClassifier(max_iter=400, max_depth=6, learning_rate=0.08)
    h.fit(train[feats], train.failed48)
    ms.append(h)
    models[name] = ms
    log(f"  trained {name} ({len(feats)} features)")
if imps:
    pd.concat(imps).to_csv(OUT / "ablation_stream2_importance.csv", index=False)


def predict(name, X):
    feats = VARIANTS[name]
    return np.mean([mm.predict_proba(X[feats])[:, 1] for mm in models[name]], axis=0)


# ------------------------------------------------------------------ static test-season matrix (as 03) + candidates for S=2025
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()
X0 = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1", "numfloors", "bldgarea", "cd"]].copy()
X0["yearbuilt"] = X0.yearbuilt.replace(0, np.nan)
X0["altered"] = (X0.yearalter1.fillna(0) > 0).astype(int)


def hist_col(s, yr):
    return X0.bbl.map(s.xs(yr, level="season")).fillna(0) if yr in s.index.get_level_values(1) else 0.0


X0["c_last1"] = hist_col(sc, 2024)
X0["c_last2"] = X0.c_last1 + hist_col(sc, 2023)
X0["v_last1"] = hist_col(sv, 2024)
X0["v_last2"] = X0.v_last1 + hist_col(sv, 2023)
X0["chronic"] = ((X0.c_last1 >= 5) & (hist_col(sc, 2023) >= 5)).astype(int)
X0 = X0.merge(band_rates(num, den, 2025, X0.bbl), on="bbl", how="left")
bw["season"] = season(bw.day)
sbw = bw.groupby(["bbl", "season"])["n"].sum()
X0["bw_last1"] = hist_col(sbw, 2024)
lord, boiler = second_tier()
X0 = add_second_tier(X0, lord, boiler, sc.rename("c").reset_index(), 2025)
X0 = X0.merge(lw[lw.season == 2025].drop(columns="season"), on="bbl", how="left")
X0 = X0.merge(bo[bo.season == 2025].drop(columns="season"), on="bbl", how="left")
X0 = X0.fillna(FILL)

bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc["lastd"] = bdc["day"]
bdc = bdc.sort_values("day")
vdc = viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "day"}).sort_values("day")
vdc["lastd"] = vdc["day"]
active = bdc.bbl.unique()
v_active = vdc.bbl.unique()
bwc = bw.sort_values(["bbl", "day"]).copy()
bwc["csum"] = bwc.groupby("bbl")["n"].cumsum()
bwc = bwc.sort_values("day")
bw_active = bwc.bbl.unique()
blkd = bd.assign(blk=bd.bbl // 10000).groupby(["blk", "day"])["n"].sum().reset_index()
blkc = blkd.sort_values(["blk", "day"]).copy()
blkc["csum"] = blkc.groupby("blk")["n"].cumsum()
blkc = blkc.sort_values("day")
blk_keys = blkc.blk.unique()
first55 = first_cold_day(days)


def asof_at(d, right, keys, cols, by="bbl"):
    t = pd.DataFrame({by: keys, "day": d})
    r = pd.merge_asof(t.sort_values("day"), right, on="day", by=by, direction="backward")
    return r.set_index(by)[cols]


def csum_asof(d):
    return asof_at(d, bdc[["bbl", "day", "csum"]], active, ["csum"])["csum"].fillna(0)


nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer", suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]

test_days = days[(days.heat_season) & (days.TMIN < 32) & (season(days.day) == 2025)].sort_values("TMIN")
if len(sys.argv) > 1:
    test_days = test_days.head(int(sys.argv[1]))
log(f"{len(test_days)} test cold days")

rows = []
for _, drow in test_days.iterrows():
    d = drow.day
    pos = set(truth.loc[truth.day == d, "bbl"])
    pos30 = set(truth.loc[truth.day.between(d, d + pd.Timedelta(days=29)), "bbl"])
    ver = set(viol.loc[viol.inspectiondate.between(d, d + pd.Timedelta(days=7)), "bbl"])
    X = X0.copy()
    a = asof_at(d - pd.Timedelta(days=1), bdc[["bbl", "day", "csum", "lastd"]], active, ["csum", "lastd"])
    c1 = a.csum.fillna(0)
    for w in (7, 14, 30):
        X[f"c_prev{w}"] = (c1 - csum_asof(d - pd.Timedelta(days=w + 1))).reindex(X.bbl).fillna(0).to_numpy()
    X["days_since_c"] = (d - a.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    av = asof_at(d - pd.Timedelta(days=1), vdc[["bbl", "day", "lastd"]], v_active, ["lastd"])
    X["days_since_v"] = (d - av.lastd.reindex(X.bbl)).dt.days.fillna(NEVER).to_numpy()
    bw1 = asof_at(d - pd.Timedelta(days=1), bwc[["bbl", "day", "csum"]], bw_active, ["csum"])["csum"].fillna(0)
    bw15 = asof_at(d - pd.Timedelta(days=15), bwc[["bbl", "day", "csum"]], bw_active, ["csum"])["csum"].fillna(0)
    X["bw_prev14"] = (bw1 - bw15).reindex(X.bbl).fillna(0).to_numpy()
    X["c_prev2"] = (c1 - csum_asof(d - pd.Timedelta(days=3))).reindex(X.bbl).fillna(0).to_numpy()
    nb = (asof_at(d - pd.Timedelta(days=1), blkc[["blk", "day", "csum"]], blk_keys, ["csum"], by="blk")["csum"].fillna(0)
          - asof_at(d - pd.Timedelta(days=3), blkc[["blk", "day", "csum"]], blk_keys, ["csum"], by="blk")["csum"].fillna(0))
    X["nb_block_2d"] = np.clip(nb.reindex(X.bbl // 10000).fillna(0).to_numpy() - X.c_prev2.to_numpy(), 0, None)
    X["days_into_cold"] = days_into_cold([d], [2025], first55)[0]
    X = X[(X.days_since_c < NEVER) | (X.days_since_v < NEVER)]
    pos &= set(X.bbl); pos30 &= set(X.bbl); ver &= set(X.bbl)
    for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
        X[c] = drow[c]
    rank = {name: pd.Series(predict(name, X), index=X.bbl) for name in VARIANTS}
    rank["base_14d"] = pd.Series(X.c_prev14.to_numpy(), index=X.bbl)
    tops = {}
    for method, s in rank.items():
        order = s.sample(frac=1, random_state=0).sort_values(ascending=False, kind="stable")
        tops[method] = {k: set(order.index[:k]) for k in KS}
        for k in KS:
            top = tops[method][k]
            rows.append(dict(day=d.date(), TMIN=drow.TMIN, k=k, method=method, n_failures=len(pos),
                             precision=len(top & pos) / k, precision_30d=len(top & pos30) / k,
                             recall=len(top & pos) / max(len(pos), 1), verified_precision=len(top & ver) / k))
    for name in VARIANTS:
        for k in KS:
            new = tops[name][k] - tops["base_14d"][k]
            rows.append(dict(day=d.date(), TMIN=drow.TMIN, k=k, method=name + " new-to-list", n_failures=len(pos),
                             precision=len(new & pos) / max(len(new), 1), precision_30d=len(new & pos30) / max(len(new), 1),
                             recall=len(new & pos) / max(len(pos), 1), verified_precision=len(new & ver) / max(len(new), 1),
                             n_new=len(new)))
    log(f"  {d.date()} TMIN {drow.TMIN:>3} failures {len(pos):>5} | p@100 " +
        " ".join(f"{n.split()[0]}={len(tops[n][100] & pos)}" for n in VARIANTS) + f" base14={len(tops['base_14d'][100] & pos)}")

res = pd.DataFrame(rows)
res.to_csv(OUT / "ablation_stream2.csv", index=False)

# ------------------------------------------------------------------ summaries
main = res[~res.method.str.contains("new-to-list")]
summ = main.groupby(["method", "k"])[["precision", "precision_30d", "recall", "verified_precision"]].mean()
base = summ.xs("V0 current", level="method")
summ["delta_p_vs_V0"] = summ.precision - summ.index.get_level_values("k").map(base.precision).to_numpy()
summ["delta_p30_vs_V0"] = summ.precision_30d - summ.index.get_level_values("k").map(base.precision_30d).to_numpy()
subsets = {"all 71 cold days": main, "frigid days (TMIN < 20)": main[main.TMIN < 20],
           "Feb 7-9 2026": main[main.day.astype(str).isin(["2026-02-07", "2026-02-08", "2026-02-09"])]}
sub_rows = []
for lab, df in subsets.items():
    g = df[df.k == 100].groupby("method")[["precision", "precision_30d", "verified_precision"]].mean()
    g["subset"] = lab; g["days"] = df.day.nunique()
    sub_rows.append(g.reset_index())
subs = pd.concat(sub_rows, ignore_index=True)
# paired per-day differences at k=100 against V0: mean, standard error, days won / lost
p100 = main[main.k == 100].pivot(index="day", columns="method", values="precision")
p30 = main[main.k == 100].pivot(index="day", columns="method", values="precision_30d")
paired = []
for name in VARIANTS:
    if name == "V0 current":
        continue
    diff = p100[name] - p100["V0 current"]
    diff30 = p30[name] - p30["V0 current"]
    paired.append(dict(variant=name, mean_delta_p100=diff.mean(), se=diff.std(ddof=1) / np.sqrt(len(diff)),
                       t_stat=diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff))) if diff.std(ddof=1) > 0 else 0.0,
                       days_better=int((diff > 0).sum()), days_worse=int((diff < 0).sum()), days_tied=int((diff == 0).sum()),
                       mean_delta_p100_30d=diff30.mean(), se_30d=diff30.std(ddof=1) / np.sqrt(len(diff30))))
paired = pd.DataFrame(paired)
summ.reset_index().to_csv(OUT / "ablation_stream2_summary.csv", index=False)
subs.to_csv(OUT / "ablation_stream2_subsets.csv", index=False)
paired.to_csv(OUT / "ablation_stream2_paired.csv", index=False)

print("\nmean over test days (precision@k, 48 h and 30 d):")
print(summ.round(4).to_string())
print("\nprecision@100 by subset:")
print(subs.pivot(index="method", columns="subset", values="precision").round(4).to_string())
print("\nprecision@100 (30 d) by subset:")
print(subs.pivot(index="method", columns="subset", values="precision_30d").round(4).to_string())
print("\npaired per-day differences vs V0 at k=100:")
print(paired.round(4).to_string(index=False))
if imps:
    imp = pd.concat(imps)
    print("\nXGBoost importance of the candidate columns (V3 both):")
    v3 = imp[imp.variant == "V3 both"].sort_values("importance", ascending=False).reset_index(drop=True)
    v3["rank"] = v3.index + 1
    print(v3[v3.feature.isin(LW_COLS + BO_COLS + ["boiler_defects_pre", "fuel_oil_pre"])].round(4).to_string(index=False))

# ------------------------------------------------------------------ mapping diagnostic: what a building_id -> bbl merge would have cost
p = DATA.parent / "task 2" / "deliverables" / "forecast_only_buildings.csv"
if p.exists():
    s2 = pd.read_csv(p, usecols=["building_id", "bbl", "rate_subfreezing", "cdays_subfreezing"]).dropna(subset=["bbl"])
    s2["bbl"] = s2.bbl.astype("int64")
    agg_max = s2.groupby("bbl").rate_subfreezing.max()
    agg_mean = s2.groupby("bbl").rate_subfreezing.mean()
    nb_lot = s2.groupby("bbl").size()
    ref = lw[lw.season == 2025].set_index("bbl").rate_subfreezing_all
    j = pd.DataFrame({"bbl_level": ref, "bldg_max": agg_max, "bldg_mean": agg_mean, "n_bldg": nb_lot}).dropna()
    shared = j[j.n_bldg > 1]
    print(f"\nmapping diagnostic on {len(j):,} lots in both tables ({len(shared):,} with 2+ complaining building ids):")
    print(f"  corr(bbl-level expanding rate, max of building rates) = {j.bbl_level.corr(j.bldg_max):.4f}; "
          f"corr with mean of building rates = {j.bbl_level.corr(j.bldg_mean):.4f}")
    print(f"  on shared lots: bbl-level rate mean {shared.bbl_level.mean():.4f} | building max {shared.bldg_max.mean():.4f} "
          f"| building mean {shared.bldg_mean.mean():.4f} (max under-states the lot union by "
          f"{1 - shared.bldg_max.mean() / max(shared.bbl_level.mean(), 1e-9):.1%}, mean by "
          f"{1 - shared.bldg_mean.mean() / max(shared.bbl_level.mean(), 1e-9):.1%})")
log("done")
