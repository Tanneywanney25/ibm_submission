"""STEP 4 / Deliverable 3: the Forecast-Only building group.

Training window only (heat seasons 2018-19 .. 2024-25): per building, complaint-days
and 48 h failure clusters by TMIN band (Frigid <20 F, widened <25 F, Freezing 20-31,
Cold 32-44, Mild >=45). Groups:
  Chronic:                >=1 complaint-day in Mild weather (TMIN >= 45 F)
  Forecast-Only (strict): 0 Mild and 0 Cold complaint-days, >=1 in Freezing or Frigid
  Forecast-Only (broad):  0 Mild complaint-days, >=1 in Freezing or Frigid (ranked by cold-sensitivity)
  Cold-only:              0 Mild, 0 sub-freezing, >=1 Cold (32-44 F) complaint-day
Then the held-out 2025-26 winter and the Feb 7-9, 2026 cold snap are scored out of
sample, baselines ranked by last season's total complaints are compared at
k = 100 / 500 / 1000 / 2500, and Sid's archived 48 h ECMWF forecasts are used to
check that the snap was forecast-triggered.

Outputs (out/): forecast_only_buildings.csv, forecast_only_group_summary.csv,
                forecast_only_precision_at_k.csv, forecast_only_examples.csv,
                forecast_vs_observed_2025_26.csv, fig_forecast_only_regimes.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from s2_common import (WORK, OUT, TRAIN_SEASONS, TEST_SEASON, SNAP_DAYS, FEATURE_CUTOFF, BAND_ORDER,
                       season, tmin_band, load_days, save_numbers, Timer)

PAL = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "violet": "#6250d6",
       "red": "#e34948", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "surface": "#fcfcfb"}
GROUP_ORDER = ["chronic", "forecast_only_strict", "forecast_only_broad_extra", "cold_only", "no_training_complaints"]
GROUP_LABEL = {"chronic": "Chronic (complains in mild weather)", "forecast_only_strict": "Forecast-Only, strict",
               "forecast_only_broad_extra": "Forecast-Only, broad (cold-day complaints too)",
               "cold_only": "Cold-only (32-44 F only)", "no_training_complaints": "No training complaints"}
GROUP_COLOR = {"chronic": PAL["orange"], "forecast_only_strict": PAL["blue"], "forecast_only_broad_extra": "#86b6ef",
               "cold_only": PAL["aqua"], "no_training_complaints": PAL["muted"]}
KS = [100, 500, 1000, 2500]
N = {}


def rank_by(df, cols):
    """1 = highest on cols (descending, lexicographic), ties broken by building_id so every rank is unique."""
    order = df.sort_values(cols + ["building_id"], ascending=[False] * len(cols) + [True], kind="mergesort").index
    return pd.Series(np.arange(1, len(df) + 1), index=order).reindex(df.index)

with Timer("load"):
    hc = pd.read_csv(WORK / "heat_complaints.csv", parse_dates=["first_ts", "day"])
    cl = pd.read_csv(WORK / "clusters.csv", parse_dates=["start_ts", "end_ts", "start_date", "vdate"])
    u = pd.read_csv(WORK / "buildings_universe.csv")
    v = pd.read_csv(WORK / "violations_clean.csv", parse_dates=["inspectiondate"])
    days = load_days()
    fc = pd.read_csv(WORK / "forecast_daily.csv", parse_dates=["prediction_day", "target_day"])
    days["frigid25"] = days.TMIN < 25

# ---------------------------------------------------------------- training-window features by band
with Timer("training-window band features"):
    dtrain = days[days.heat_season & days.season.isin(TRAIN_SEASONS) & ~days.holiday_gap]
    band_days = dtrain.band.value_counts().reindex(BAND_ORDER).fillna(0).astype(int)
    band_days25 = int(dtrain.frigid25.sum())
    N["train_days_by_band"] = band_days.to_dict()
    N["train_days_frigid25"] = band_days25
    N["train_days_total"] = len(dtrain)
    bd = (hc[hc.season.isin(TRAIN_SEASONS) & hc.heat_season].groupby(["building_id", "day"]).complaint_id.size()
          .rename("n").reset_index())
    bd = bd.merge(days[["day", "TMIN", "band", "frigid25"]], on="day", how="inner")
    bd = bd[bd.day.isin(dtrain.day)]
    cdays = bd.pivot_table(index="building_id", columns="band", values="day", aggfunc="count", fill_value=0, observed=False)
    cdays.columns = [f"cdays_{c.lower()}" for c in cdays.columns]
    ccnt = bd.pivot_table(index="building_id", columns="band", values="n", aggfunc="sum", fill_value=0, observed=False)
    ccnt.columns = [f"complaints_{c.lower()}" for c in ccnt.columns]
    f = cdays.join(ccnt)
    f["cdays_frigid25"] = bd[bd.frigid25].groupby("building_id").size()
    f["cdays_frigid25"] = f.cdays_frigid25.fillna(0).astype(int)
    f["cdays_subfreezing"] = f.cdays_frigid + f.cdays_freezing
    f["cdays_total"] = f[["cdays_frigid", "cdays_freezing", "cdays_cold", "cdays_mild"]].sum(axis=1)
    for b in BAND_ORDER:
        f[f"rate_{b.lower()}"] = f[f"cdays_{b.lower()}"] / band_days[b]
    f["rate_frigid25"] = f.cdays_frigid25 / band_days25
    f["rate_subfreezing"] = f.cdays_subfreezing / (band_days["Frigid"] + band_days["Freezing"])
    f["rate_cold_mild"] = (f.cdays_cold + f.cdays_mild) / (band_days["Cold"] + band_days["Mild"])
    eps_cold = 0.5 / band_days["Cold"]
    eps_cm = 0.5 / (band_days["Cold"] + band_days["Mild"])
    f["cold_multiplier_vs_cold"] = f.rate_subfreezing / (f.rate_cold + eps_cold)
    f["cold_multiplier_vs_cold_mild"] = f.rate_subfreezing / (f.rate_cold_mild + eps_cm)
    # 48 h failure clusters (2+) by band of the start day, training window
    ct = cl[cl.season.isin(TRAIN_SEASONS) & cl.heat_season & cl.label_2plus & cl.start_date.isin(dtrain.day)]
    fb = ct.pivot_table(index="building_id", columns="band", values="cluster_id", aggfunc="count", fill_value=0, observed=False)
    fb.columns = [f"fail48_{c.lower()}" for c in fb.columns]
    f = f.join(fb).fillna({c: 0 for c in fb.columns})
    f["fail48_train_total"] = f[[c for c in f.columns if c.startswith("fail48_")]].sum(axis=1)
    f["fail48_rate_subfreezing"] = (f.fail48_frigid + f.fail48_freezing) / (band_days["Frigid"] + band_days["Freezing"])
    f["fail48_verified7_train"] = ct[ct.confirmed7].groupby("building_id").size()
    # Stream 5 style season counts, strictly training window
    sc = hc[hc.season.isin(TRAIN_SEASONS)].groupby(["building_id", "season"]).complaint_id.size().unstack(fill_value=0)
    f["c_train_total"] = sc.sum(axis=1)
    f["c_last1"] = sc.get(2024, 0)
    f["c_last2"] = sc.get(2024, 0) + sc.get(2023, 0)
    f["seasons_active_train"] = (sc > 0).sum(axis=1)
    f["chronic_stream5"] = ((sc.get(2024, 0) >= 5) & (sc.get(2023, 0) >= 5)).astype(int)
    last = hc[hc.season.isin(TRAIN_SEASONS)].groupby("building_id").day.max()
    f["days_since_last_complaint_at_cutoff"] = (FEATURE_CUTOFF - last).dt.days
    first = hc[hc.season.isin(TRAIN_SEASONS)].groupby("building_id").day.min()
    f["first_training_complaint"] = first
    f["last_training_complaint"] = last
    hv = v[(v.vtype == "heat") & v.season.isin(TRAIN_SEASONS)]
    f["v_heat_train_total"] = hv.groupby("building_id").size()
    f["v_heat_last1"] = hv[hv.season == 2024].groupby("building_id").size()
    f = f.fillna({"c_train_total": 0, "c_last1": 0, "c_last2": 0, "seasons_active_train": 0, "chronic_stream5": 0,
                  "v_heat_train_total": 0, "v_heat_last1": 0, "fail48_verified7_train": 0})

# ---------------------------------------------------------------- groups
with Timer("groups"):
    F = u[["building_id", "bbl", "bin", "borough", "cd", "council", "unitsres", "yearbuilt", "yearalter1", "numfloors",
           "bldgarea", "bldgclass", "size_bucket", "era", "altered", "res3plus", "multi_building_lot", "latitude", "longitude"]].merge(
        f.reset_index(), on="building_id", how="left")
    numcols = [c for c in f.columns if c not in ("first_training_complaint", "last_training_complaint")]
    F[numcols] = F[numcols].fillna(0)
    sub = F.cdays_subfreezing >= 1
    F["group"] = np.select(
        [F.cdays_mild >= 1,
         (F.cdays_mild == 0) & (F.cdays_cold == 0) & sub,
         (F.cdays_mild == 0) & (F.cdays_cold >= 1) & sub,
         (F.cdays_mild == 0) & (F.cdays_cold >= 1) & ~sub],
        ["chronic", "forecast_only_strict", "forecast_only_broad_extra", "cold_only"], "no_training_complaints")
    F["forecast_only_strict"] = F.group.eq("forecast_only_strict")
    F["forecast_only_broad"] = F.group.isin(["forecast_only_strict", "forecast_only_broad_extra"])
    F["chronic"] = F.group.eq("chronic")
    # widened frigid variant: strict group that reacted on a <25 F day
    F["forecast_only_strict_frigid25"] = F.forecast_only_strict & (F.cdays_frigid25 >= 1)
    F["forecast_only_broad_rank"] = np.nan
    fb_idx = F.index[F.forecast_only_broad]
    F.loc[fb_idx, "forecast_only_broad_rank"] = rank_by(F.loc[fb_idx], ["rate_subfreezing", "cold_multiplier_vs_cold"]).to_numpy()
    F["subfreezing_tier"] = pd.cut(F.cdays_subfreezing, [-1, 0, 1, 3, 9, 10 ** 6], labels=["0", "1", "2-3", "4-9", "10+"])
    # the strongest chronic buildings for contrast: mild complaint-days in the top decile among chronic
    N["groups_buildings"] = F.group.value_counts().to_dict()
    N["groups_units"] = F.groupby("group").unitsres.sum().to_dict()
    N["forecast_only_strict_buildings"] = int(F.forecast_only_strict.sum())
    N["forecast_only_strict_units"] = float(F.loc[F.forecast_only_strict, "unitsres"].sum())
    N["forecast_only_strict_frigid25_buildings"] = int(F.forecast_only_strict_frigid25.sum())
    N["forecast_only_broad_buildings"] = int(F.forecast_only_broad.sum())
    N["forecast_only_broad_units"] = float(F.loc[F.forecast_only_broad, "unitsres"].sum())
    N["chronic_buildings"] = int(F.chronic.sum())
    N["chronic_units"] = float(F.loc[F.chronic, "unitsres"].sum())
    N["forecast_only_strict_in_res3plus"] = int((F.forecast_only_strict & F.res3plus).sum())
    N["forecast_only_strict_share_1_2_units"] = float((F.loc[F.forecast_only_strict, "unitsres"] <= 2).mean())
    N["forecast_only_strict_median_c_last1"] = float(F.loc[F.forecast_only_strict, "c_last1"].median())
    N["forecast_only_strict_share_c_last1_zero"] = float((F.loc[F.forecast_only_strict, "c_last1"] == 0).mean())
    N["chronic_median_c_last1"] = float(F.loc[F.chronic, "c_last1"].median())
    prof = F[F.group.isin(["chronic", "forecast_only_strict", "forecast_only_broad_extra"])].groupby("group").agg(
        buildings=("building_id", "size"), units=("unitsres", "sum"), median_units=("unitsres", "median"),
        median_yearbuilt=("yearbuilt", lambda s: s[s > 0].median()), share_prewar=("era", lambda s: (s == "1901-1939 pre-war").mean()),
        share_altered=("altered", "mean"), share_bronx=("borough", lambda s: (s == "Bronx").mean()),
        share_res3plus=("res3plus", "mean"), mean_c_last1=("c_last1", "mean"), mean_cdays_subfreezing=("cdays_subfreezing", "mean"),
        mean_rate_subfreezing=("rate_subfreezing", "mean"), mean_rate_mild=("rate_mild", "mean"))
    N["profile"] = prof.reset_index().to_dict(orient="records")
print(f"  chronic {N['chronic_buildings']:,} buildings | forecast-only strict {N['forecast_only_strict_buildings']:,} "
      f"({N['forecast_only_strict_units']:,.0f} units) | broad {N['forecast_only_broad_buildings']:,} ({N['forecast_only_broad_units']:,.0f} units)")

# ---------------------------------------------------------------- held-out 2025-26 outcomes
with Timer("2025-26 holdout outcomes"):
    dtest = days[days.heat_season & (days.season == TEST_SEASON)]
    tb = (hc[(hc.season == TEST_SEASON) & hc.heat_season].groupby(["building_id", "day"]).complaint_id.size()
          .rename("n").reset_index().merge(days[["day", "band", "TMIN"]], on="day"))
    tcd = tb.pivot_table(index="building_id", columns="band", values="day", aggfunc="count", fill_value=0, observed=False)
    tcd.columns = [f"test_cdays_{c.lower()}" for c in tcd.columns]
    T = tcd.copy()
    T["test_complaints"] = hc[hc.season == TEST_SEASON].groupby("building_id").size()
    T["test_cdays_total"] = tcd.sum(axis=1)
    ctest = cl[(cl.season == TEST_SEASON) & cl.heat_season & cl.label_2plus]
    T["test_fail48"] = ctest.groupby("building_id").size()
    T["test_fail48_subfreezing"] = ctest[ctest.band.isin(["Frigid", "Freezing"])].groupby("building_id").size()
    T["test_fail48_verified7"] = ctest[ctest.confirmed7].groupby("building_id").size()
    T["test_heat_violations"] = v[(v.vtype == "heat") & (v.season == TEST_SEASON)].groupby("building_id").size()
    snapc = hc[hc.day.isin(SNAP_DAYS)]
    T["snap_complaints"] = snapc.groupby("building_id").size()
    csnap = cl[cl.start_date.isin(SNAP_DAYS) & cl.label_2plus]
    T["snap_fail48"] = csnap.groupby("building_id").size()
    T["snap_fail48_n"] = csnap.groupby("building_id").n.max()
    T["snap_verified7"] = csnap[csnap.confirmed7].groupby("building_id").size()
    T["snap_violation_date"] = csnap[csnap.confirmed7].groupby("building_id").vdate.min()
    T["snap_violation_lag_days"] = csnap[csnap.confirmed7].groupby("building_id").lag_days.min()
    # trailing-14-day complaints before the snap (Jan 24 .. Feb 6, 2026): the strong recency baseline
    T["c_prev14_before_snap"] = hc[(hc.day >= "2026-01-24") & (hc.day <= "2026-02-06")].groupby("building_id").size()
    T = T.reset_index()
    F = F.merge(T, on="building_id", how="left")
    tcols = [c for c in T.columns if c not in ("building_id", "snap_violation_date")]
    F[tcols] = F[tcols].fillna(0)
    F["snap_failed"] = F.snap_fail48 >= 1
    F["snap_any_complaint"] = F.snap_complaints >= 1
    F["test_failed"] = F.test_fail48 >= 1
    F["test_complained"] = F.test_complaints >= 1
    F["test_verified"] = F.test_fail48_verified7 >= 1

    g = F.groupby("group")
    gs = pd.DataFrame({
        "buildings": g.size(), "units": g.unitsres.sum(),
        "share_complained_2025_26": g.test_complained.mean(), "share_failed48_2025_26": g.test_failed.mean(),
        "share_verified_2025_26": g.test_verified.mean(), "share_heat_violation_2025_26": g.test_heat_violations.apply(lambda s: (s >= 1).mean()),
        "share_failed48_feb7_9": g.snap_failed.mean(), "share_any_complaint_feb7_9": g.snap_any_complaint.mean(),
        "fail48_events_2025_26": g.test_fail48.sum(), "fail48_events_feb7_9": g.snap_fail48.sum(),
        "units_in_buildings_failed_feb7_9": g.apply(lambda d: d.loc[d.snap_failed, "unitsres"].sum()),
    })
    test_band_days = dtest.band.value_counts().reindex(BAND_ORDER).fillna(0)
    for b in BAND_ORDER:
        col = f"test_cdays_{b.lower()}"
        gs[f"test_cdays_per_1000_bldg_per_day_{b.lower()}"] = 1000 * g[col].sum() / (g.size() * test_band_days[b]) if test_band_days[b] else np.nan
    gs = gs.reindex(GROUP_ORDER).reset_index()
    gs.to_csv(OUT / "forecast_only_group_summary.csv", index=False)
    N["group_summary"] = gs.to_dict(orient="records")
    N["test_days_by_band"] = test_band_days.to_dict()
    fo = F[F.forecast_only_strict]
    N["forecast_only_strict_failed_snap"] = int(fo.snap_failed.sum())
    N["forecast_only_strict_any_complaint_snap"] = int(fo.snap_any_complaint.sum())
    N["forecast_only_strict_units_failed_snap"] = float(fo.loc[fo.snap_failed, "unitsres"].sum())
    N["forecast_only_strict_verified_snap"] = int((fo.snap_verified7 >= 1).sum())
    N["forecast_only_broad_failed_snap"] = int(F.loc[F.forecast_only_broad, "snap_failed"].sum())
    N["chronic_failed_snap"] = int(F.loc[F.chronic, "snap_failed"].sum())
    N["all_failed_snap"] = int(F.snap_failed.sum())
    N["all_units_failed_snap"] = float(F.loc[F.snap_failed, "unitsres"].sum())
    N["snap_failed_buildings_with_no_training_complaints"] = int(F.loc[F.group == "no_training_complaints", "snap_failed"].sum())
    N["forecast_only_strict_test_mild_rate_per_1000"] = float(gs.loc[gs.group == "forecast_only_strict", "test_cdays_per_1000_bldg_per_day_mild"].iloc[0])
    N["forecast_only_strict_test_frigid_rate_per_1000"] = float(gs.loc[gs.group == "forecast_only_strict", "test_cdays_per_1000_bldg_per_day_frigid"].iloc[0])
    N["chronic_test_mild_rate_per_1000"] = float(gs.loc[gs.group == "chronic", "test_cdays_per_1000_bldg_per_day_mild"].iloc[0])
    N["chronic_test_frigid_rate_per_1000"] = float(gs.loc[gs.group == "chronic", "test_cdays_per_1000_bldg_per_day_frigid"].iloc[0])
print(gs[["group", "buildings", "units", "share_failed48_2025_26", "share_failed48_feb7_9", "fail48_events_feb7_9"]].to_string(index=False))

# ---------------------------------------------------------------- baselines at k on Feb 7-9, 2026
with Timer("baseline ranks at k"):
    R = F[F.in_pluto if "in_pluto" in F.columns else F.bbl.notna()].copy() if False else F.copy()
    R["_cold_x_units"] = R.rate_subfreezing * R.unitsres.clip(lower=1)
    rankings = {
        "last season total complaints (2024-25)": rank_by(R, ["c_last1", "c_train_total"]),
        "training-window total complaints (2018-25)": rank_by(R, ["c_train_total", "c_last1"]),
        "last season heat violations (2024-25)": rank_by(R, ["v_heat_last1", "c_last1"]),
        "trailing 14-day complaints before Feb 7": rank_by(R, ["c_prev14_before_snap", "c_last1"]),
        "cold-sensitivity: sub-freezing reaction rate (2018-25)": rank_by(R, ["rate_subfreezing", "cold_multiplier_vs_cold", "c_train_total"]),
        "cold-sensitivity x units (tenants at risk)": rank_by(R, ["_cold_x_units", "c_train_total"]),
    }
    rows = []
    total_fail = int(R.snap_failed.sum())
    for name, order in rankings.items():
        R[f"rank__{name}"] = order
        for k in KS:
            top = R[order <= k]
            rows.append({"ranking": name, "k": k, "failed_feb7_9_caught": int(top.snap_failed.sum()),
                         "precision": float(top.snap_failed.mean()), "recall": float(top.snap_failed.sum() / total_fail),
                         "forecast_only_strict_in_top_k": int(top.forecast_only_strict.sum()),
                         "forecast_only_broad_in_top_k": int(top.forecast_only_broad.sum()),
                         "chronic_in_top_k": int(top.chronic.sum()),
                         "verified_feb7_9_caught": int((top.snap_verified7 >= 1).sum()),
                         "units_in_failed_caught": float(top.loc[top.snap_failed, "unitsres"].sum())})
    pk = pd.DataFrame(rows)
    pk.to_csv(OUT / "forecast_only_precision_at_k.csv", index=False)
    N["precision_at_k"] = pk.to_dict(orient="records")
    N["snap_total_failed"] = total_fail
    # where does the static baseline put the forecast-only buildings that failed in the snap?
    fo_fail = R[R.forecast_only_strict & R.snap_failed]
    base = "rank__last season total complaints (2024-25)"
    N["fo_strict_failed_snap_baseline_rank_median"] = float(fo_fail[base].median())
    N["fo_strict_failed_snap_baseline_rank_min"] = float(fo_fail[base].min())
    for k in KS:
        N[f"fo_strict_failed_snap_in_baseline_top_{k}"] = int((fo_fail[base] <= k).sum())
    cs = "rank__cold-sensitivity: sub-freezing reaction rate (2018-25)"
    for k in KS:
        N[f"fo_strict_failed_snap_in_coldsens_top_{k}"] = int((fo_fail[cs] <= k).sum())
    N["fo_strict_failed_snap_coldsens_rank_median"] = float(fo_fail[cs].median())
    # new-to-list: failures the cold-sensitivity list catches at k that the last-season list misses
    for k in KS:
        a = set(R.loc[R[cs] <= k, "building_id"]); b = set(R.loc[R[base] <= k, "building_id"])
        new = R[R.building_id.isin(a - b)]
        N[f"coldsens_new_to_list_k{k}_buildings"] = len(new)
        N[f"coldsens_new_to_list_k{k}_failed"] = int(new.snap_failed.sum())
print(pk.pivot(index="k", columns="ranking", values="precision").round(3).to_string())

# ---------------------------------------------------------------- cold-sensitivity intensity tiers (zero-mild buildings)
with Timer("intensity tiers"):
    tiers = []
    for lab, mask in [("forecast_only_broad", F.forecast_only_broad), ("forecast_only_strict", F.forecast_only_strict), ("chronic", F.chronic)]:
        g = F[mask].groupby("subfreezing_tier", observed=True)
        t = pd.DataFrame({"buildings": g.size(), "units": g.unitsres.sum(), "share_failed48_2025_26": g.test_failed.mean(),
                          "share_verified_2025_26": g.test_verified.mean(), "share_failed48_feb7_9": g.snap_failed.mean(),
                          "failed48_feb7_9": g.snap_failed.sum(), "share_complained_2025_26": g.test_complained.mean(),
                          "mean_c_last1": g.c_last1.mean(), "share_c_last1_zero": g.c_last1.apply(lambda s: (s == 0).mean())}).reset_index()
        t.insert(0, "group", lab); tiers.append(t)
    tiers = pd.concat(tiers, ignore_index=True)
    tiers.to_csv(OUT / "forecast_only_intensity_tiers.csv", index=False)
    N["intensity_tiers"] = tiers.to_dict(orient="records")
    hi = F.forecast_only_broad & (F.cdays_subfreezing >= 4)
    N["fo_broad_4plus_subfreezing_buildings"] = int(hi.sum())
    N["fo_broad_4plus_subfreezing_units"] = float(F.loc[hi, "unitsres"].sum())
    N["fo_broad_4plus_subfreezing_share_failed_2025_26"] = float(F.loc[hi, "test_failed"].mean())
    N["fo_broad_4plus_subfreezing_share_failed_snap"] = float(F.loc[hi, "snap_failed"].mean())
    N["snap_failed_with_c_last1_zero"] = int((F.snap_failed & (F.c_last1 == 0)).sum())
    N["snap_failed_with_c_last1_zero_share"] = float((F.snap_failed & (F.c_last1 == 0)).sum() / F.snap_failed.sum())
    N["snap_failed_zero_mild_training"] = int((F.snap_failed & F.forecast_only_broad).sum())
    N["snap_failed_zero_mild_training_units"] = float(F.loc[F.snap_failed & F.forecast_only_broad, "unitsres"].sum())
print(tiers[tiers.group == "forecast_only_broad"][["subfreezing_tier", "buildings", "share_failed48_2025_26", "share_failed48_feb7_9"]].to_string(index=False))

# ---------------------------------------------------------------- archived forecast cross-check
with Timer("archived forecast cross-check"):
    w = days[["day", "TMIN", "band"]].copy()
    w["tmin_obs_next48h"] = w[["TMIN"]].assign(n1=w.TMIN.shift(-1), n2=w.TMIN.shift(-2))[["n1", "n2"]].min(axis=1)
    # forecast issued 12:00 UTC on prediction_day covers local day+1 and day+2 nights -> compare with min(TMIN[d+1], TMIN[d+2])
    x = fc.merge(w, left_on="prediction_day", right_on="day", how="inner")
    x = x[(season(x.prediction_day) == TEST_SEASON) & x.prediction_day.dt.month.isin([10, 11, 12, 1, 2, 3, 4, 5])]
    x["fc_subfreezing"] = x.fc_tmin_next48h_f < 32
    x["obs_subfreezing"] = x.tmin_obs_next48h < 32
    x["fc_frigid"] = x.fc_tmin_next48h_f < 20
    x["obs_frigid"] = x.tmin_obs_next48h < 20
    x["error_f"] = x.fc_tmin_next48h_f - x.tmin_obs_next48h
    N["fc_test_days"] = len(x)
    N["fc_subfreezing_agreement"] = float((x.fc_subfreezing == x.obs_subfreezing).mean())
    N["fc_frigid_agreement"] = float((x.fc_frigid == x.obs_frigid).mean())
    N["fc_mean_abs_error_f"] = float(x.error_f.abs().mean())
    N["fc_mean_bias_f"] = float(x.error_f.mean())
    N["fc_triggered_days_subfreezing"] = int(x.fc_subfreezing.sum())
    N["fc_obs_days_subfreezing"] = int(x.obs_subfreezing.sum())
    N["fc_hit_rate_subfreezing"] = float(x.loc[x.obs_subfreezing, "fc_subfreezing"].mean())
    N["fc_false_alarm_rate_subfreezing"] = float(x.loc[x.fc_subfreezing, "obs_subfreezing"].eq(False).mean())
    x[["prediction_day", "target_day", "fc_tmin_next48h_f", "fc_tmin_next48h_f_bronx", "fc_freezing_hours_next48h",
       "fc_heating_degree_hours_next48h", "fc_snow_cm_next48h", "fc_lead_hours", "TMIN", "tmin_obs_next48h", "band",
       "fc_subfreezing", "obs_subfreezing", "fc_frigid", "obs_frigid", "error_f"]].to_csv(OUT / "forecast_vs_observed_2025_26.csv", index=False)
    snapfc = x[(x.prediction_day >= "2026-02-03") & (x.prediction_day <= "2026-02-09")]
    N["snap_forecast_rows"] = snapfc[["prediction_day", "fc_tmin_next48h_f", "fc_tmin_next48h_f_bronx", "tmin_obs_next48h", "TMIN"]].to_dict(orient="records")
    # group reaction on forecast-triggered vs untriggered test days (forecast issued the morning before the target day)
    trig = x[["target_day", "fc_subfreezing", "fc_frigid"]].rename(columns={"target_day": "day"})
    tb2 = tb.merge(trig, on="day", how="inner").merge(F[["building_id", "group"]], on="building_id", how="left")
    nb = F.group.value_counts()
    ndays = trig.groupby("fc_subfreezing").size()
    react = (tb2.groupby(["group", "fc_subfreezing"]).size().rename("cdays").reset_index())
    react["buildings"] = react.group.map(nb); react["days"] = react.fc_subfreezing.map(ndays)
    react["cdays_per_1000_bldg_per_day"] = 1000 * react.cdays / (react.buildings * react.days)
    react.to_csv(OUT / "forecast_only_reaction_by_forecast_trigger.csv", index=False)
    N["reaction_by_forecast_trigger"] = react.to_dict(orient="records")
print(f"  archived 48 h forecast vs observed, 2025-26: sub-freezing flag agrees on {N['fc_subfreezing_agreement']:.0%} of days, "
      f"mean abs error {N['fc_mean_abs_error_f']:.1f} F")

# ---------------------------------------------------------------- worked examples
with Timer("worked examples"):
    ex = F[F.forecast_only_strict & F.snap_failed & (F.snap_verified7 >= 1) & F.bbl.notna()].copy()
    ex = ex.sort_values(["seasons_active_train", "unitsres"], ascending=[False, False])
    keep = ["building_id", "bbl", "bin", "borough", "cd", "council", "yearbuilt", "unitsres", "numfloors", "bldgclass", "era",
            "seasons_active_train", "first_training_complaint", "last_training_complaint",
            "cdays_frigid", "cdays_freezing", "cdays_cold", "cdays_mild", "complaints_frigid", "complaints_freezing",
            "c_train_total", "c_last1", "c_prev14_before_snap", "fail48_train_total", "v_heat_train_total",
            "test_complaints", "test_fail48", "snap_complaints", "snap_fail48_n", "snap_violation_date", "snap_violation_lag_days",
            "rank__last season total complaints (2024-25)", "rank__cold-sensitivity: sub-freezing reaction rate (2018-25)"]
    ex = ex.merge(R[["building_id"] + [c for c in R.columns if c.startswith("rank__")]], on="building_id", how="left")
    ex[keep].head(25).to_csv(OUT / "forecast_only_examples.csv", index=False)
    N["examples"] = ex[keep].head(6).to_dict(orient="records")
    N["examples_pool"] = len(ex)
print(ex[["building_id", "bbl", "borough", "cd", "yearbuilt", "unitsres", "cdays_frigid", "cdays_freezing", "c_last1",
          "snap_complaints", "snap_violation_date", "rank__last season total complaints (2024-25)"]].head(6).to_string(index=False))

# ---------------------------------------------------------------- save the Stream 5 handoff
with Timer("write forecast_only_buildings.csv"):
    F = F.drop(columns=[c for c in F.columns if c.startswith("rank__") or c == "_cold_x_units"], errors="ignore")
    F = F.merge(R[["building_id", "rank__last season total complaints (2024-25)",
                   "rank__cold-sensitivity: sub-freezing reaction rate (2018-25)"]]
                .rename(columns={"rank__last season total complaints (2024-25)": "baseline_rank_last_season",
                                 "rank__cold-sensitivity: sub-freezing reaction rate (2018-25)": "cold_sensitivity_rank"}),
                on="building_id", how="left")
    feat_cols = [c for c in F.columns if not (c.startswith("test_") or c.startswith("snap_") or c == "c_prev14_before_snap")]
    F = F[feat_cols + [c for c in F.columns if c not in feat_cols]]
    F.to_csv(OUT / "forecast_only_buildings.csv", index=False)
    N["output_rows"] = len(F)
    N["feature_columns_leak_free"] = feat_cols
    N["evaluation_columns_2025_26"] = [c for c in F.columns if c not in feat_cols]

# ---------------------------------------------------------------- figure
with Timer("figure"):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": PAL["ink2"],
                         "xtick.color": PAL["muted"], "ytick.color": PAL["muted"], "axes.titlecolor": PAL["ink"],
                         "figure.facecolor": PAL["surface"], "axes.facecolor": PAL["surface"]})
    fig = plt.figure(figsize=(15, 8.2))
    gsp = fig.add_gridspec(2, 2, height_ratios=[1, 1.15])
    # (a) out-of-sample reaction by band, per group
    ax = fig.add_subplot(gsp[0, 0])
    groups = ["chronic", "forecast_only_strict", "forecast_only_broad_extra", "cold_only"]
    wdt = 0.2
    for j, grp in enumerate(groups):
        vals = [gs.loc[gs.group == grp, f"test_cdays_per_1000_bldg_per_day_{b.lower()}"].iloc[0] for b in BAND_ORDER]
        ax.bar(np.arange(4) + (j - 1.5) * wdt, vals, width=wdt, color=GROUP_COLOR[grp], label=GROUP_LABEL[grp])
    ax.set_xticks(range(4)); ax.set_xticklabels(["Frigid <20 F", "Freezing 20-31", "Cold 32-44", "Mild 45+"])
    ax.set_ylabel("complaint-days per 1,000 buildings per day"); ax.set_title("Held-out 2025-26: who reacts in which weather", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8); ax.grid(axis="y", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    # (b) precision at k on Feb 7-9
    ax = fig.add_subplot(gsp[0, 1])
    names = ["last season total complaints (2024-25)", "trailing 14-day complaints before Feb 7",
             "cold-sensitivity: sub-freezing reaction rate (2018-25)"]
    cols = [PAL["muted"], PAL["orange"], PAL["blue"]]
    labs = ["static: last season's total", "recency: trailing 14 days", "cold-sensitivity (training window)"]
    for j, (nm, c, lb) in enumerate(zip(names, cols, labs)):
        p = pk[pk.ranking == nm].set_index("k").reindex(KS)
        ax.bar(np.arange(4) + (j - 1) * 0.27, p.precision * 100, width=0.27, color=c, label=lb)
        for i, val in enumerate(p.precision * 100):
            ax.text(i + (j - 1) * 0.27, val + 0.6, f"{val:.0f}", ha="center", fontsize=8, color=PAL["ink2"])
    ax.set_xticks(range(4)); ax.set_xticklabels([f"k = {k:,}" for k in KS])
    ax.set_ylabel("share of top-k that failed Feb 7-9, 2026, %"); ax.set_title("Feb 7-9, 2026: failures caught per inspection budget", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8); ax.grid(axis="y", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    # (c) daily series Jan 10 - Feb 28 2026: TMIN (top strip) and share of each group complaining (bottom)
    sub_gs = gsp[1, :].subgridspec(2, 1, height_ratios=[1, 2.4], hspace=0.08)
    ax0 = fig.add_subplot(sub_gs[0]); ax1 = fig.add_subplot(sub_gs[1], sharex=ax0)
    span = days[(days.day >= "2026-01-10") & (days.day <= "2026-02-28")]
    ax0.plot(span.day, span.TMIN, color=PAL["ink"], linewidth=1.6)
    ax0.axhline(32, color=PAL["muted"], linewidth=0.8, linestyle="--"); ax0.axhline(20, color=PAL["muted"], linewidth=0.8, linestyle=":")
    ax0.set_ylabel("TMIN, F"); ax0.set_title("Jan 10 to Feb 28, 2026: observed low (top) and share of each group with a complaint (bottom)", loc="left", fontsize=10)
    ax0.axvspan(SNAP_DAYS[0], SNAP_DAYS[-1] + pd.Timedelta(days=1), color="#cde2fb", alpha=0.6, lw=0)
    plt.setp(ax0.get_xticklabels(), visible=False)
    for grp in ["chronic", "forecast_only_strict", "forecast_only_broad_extra"]:
        ids = F.loc[F.group == grp, "building_id"]
        s = tb[tb.building_id.isin(ids)].groupby("day").size().reindex(span.day, fill_value=0) / len(ids) * 100
        ax1.plot(s.index, s.values, color=GROUP_COLOR[grp], linewidth=2, label=GROUP_LABEL[grp])
    ax1.axvspan(SNAP_DAYS[0], SNAP_DAYS[-1] + pd.Timedelta(days=1), color="#cde2fb", alpha=0.6, lw=0)
    ax1.set_ylabel("buildings with a heat complaint, % of group"); ax1.legend(frameon=False, fontsize=8, loc="upper left")
    for a in (ax0, ax1):
        a.grid(color=PAL["grid"]); a.set_axisbelow(True)
        for s_ in ("top", "right"): a.spines[s_].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "fig_forecast_only_regimes.png", dpi=160)
    plt.close(fig)

save_numbers("04_forecast_only", N)
print("STEP 4 complete")
