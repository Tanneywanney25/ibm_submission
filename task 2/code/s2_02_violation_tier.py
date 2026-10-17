"""STEP 2 / Deliverable 1: violation tier and label credibility check.

Builds building-level 48-hour complaint clusters from the heat-only complaints
(sessionized: a complaint starts a new cluster when it arrives more than 48 h after
the current cluster's first complaint), matches each cluster to verified heat
violations (orders 666/966/674) inspected 0-7 days after the cluster start (14-day
sensitivity), and reports the violation-confirmation rate by cluster tier, TMIN
band, building size, construction era and alteration status. Also builds the
per-day inspector saturation table.

Outputs (out/): violation_confirmation_summary.csv, violation_saturation_by_day.csv,
                fig_violation_confirmation.png, numbers_02_violation_tier.json
          (work/): clusters.csv  (reused by steps 3, 4 and 5)
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from s2_common import (WORK, OUT, TRAIN_SEASONS, TEST_SEASON, SNAP_DAYS, BAND_ORDER, SIZE_ORDER, ERA_ORDER,
                       season, in_heat_season, tmin_band, load_days, save_numbers, Timer)

PAL = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "magenta": "#e87ba4",
       "violet": "#6250d6", "red": "#e34948", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
       "grid": "#e1e0d9", "surface": "#fcfcfb"}
BAND_COLOR = {"Frigid": "#104281", "Freezing": "#2a78d6", "Cold": "#86b6ef", "Mild": "#cde2fb"}
N = {}

# ---------------------------------------------------------------- load
with Timer("load working tables"):
    hc = pd.read_csv(WORK / "heat_complaints.csv", parse_dates=["first_ts", "day"])
    v = pd.read_csv(WORK / "violations_clean.csv", parse_dates=["inspectiondate", "novissueddate"])
    u = pd.read_csv(WORK / "buildings_universe.csv")
    days = load_days()

# ---------------------------------------------------------------- 48 h clusters
with Timer("sessionize complaints into 48 h clusters"):
    hc = hc.sort_values(["building_id", "first_ts"]).reset_index(drop=True)
    b = hc.building_id.to_numpy()
    t = hc.first_ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
    W = 48 * 3600 * 10 ** 9
    cluster = np.empty(len(hc), dtype=np.int64)
    cid, cur_b, start = -1, None, 0
    for i in range(len(hc)):
        if b[i] != cur_b or t[i] - start > W:
            cid += 1; cur_b = b[i]; start = t[i]
        cluster[i] = cid
    hc["cluster_id"] = cluster
    cl = (hc.groupby("cluster_id")
            .agg(building_id=("building_id", "first"), start_ts=("first_ts", "min"), end_ts=("first_ts", "max"),
                 n=("complaint_id", "size"), n_nondup=("any_nondup", "sum"), n_anon=("is_anon", "sum"),
                 n_rows=("n_rows", "sum"), n_dup_rows=("n_dup_rows", "sum"))
            .reset_index())
    # distinct complaining apartments per cluster, from the pseudonymized rows (apt_hash only)
    hr = pd.read_csv(WORK / "heat_rows.csv", usecols=["complaint_id", "building_id", "apt_hash"])
    hr = hr.merge(hc[["building_id", "complaint_id", "cluster_id"]], on=["building_id", "complaint_id"], how="inner")
    apts = hr.groupby("cluster_id").apt_hash.nunique().rename("n_apts")
    cl = cl.merge(apts, on="cluster_id", how="left")
    del hr
    cl["start_date"] = cl.start_ts.dt.normalize()
    cl["span_hours"] = (cl.end_ts - cl.start_ts).dt.total_seconds() / 3600
    cl["season"] = season(cl.start_date)
    cl["heat_season"] = in_heat_season(cl.start_date)
    cl = cl.merge(days[["day", "TMIN", "tmin_48h", "band"]].rename(columns={"day": "start_date"}), on="start_date", how="left")
    cl["band48"] = tmin_band(cl.tmin_48h)
    cl["frigid25"] = cl.TMIN < 25
    cl = cl.merge(u[["building_id", "bbl", "bin", "borough", "cd", "council", "unitsres", "yearbuilt", "altered",
                     "size_bucket", "era", "res3plus", "multi_building_lot"]], on="building_id", how="left")
    cl["tier"] = pd.Categorical(np.select([cl.n == 1, cl.n == 2, cl.n <= 4], ["1", "2", "3-4"], "5+"),
                                categories=["1", "2", "3-4", "5+"], ordered=True)
    cl["label_2plus"] = cl.n >= 2
    cl["label_2plus_nondup"] = cl.n_nondup >= 2
    cl["label_3plus"] = cl.n >= 3
    cl["label_5plus"] = cl.n >= 5
    cl["label_2plus_2apts"] = (cl.n >= 2) & (cl.n_apts >= 2)
N["clusters_total"] = len(cl)
N["clusters_2plus"] = int(cl.label_2plus.sum())
N["clusters_single"] = int((cl.n == 1).sum())
N["clusters_2plus_share"] = float(cl.label_2plus.mean())
N["complaints_in_2plus_clusters_share"] = float(cl.loc[cl.label_2plus, "n"].sum() / cl.n.sum())
N["cluster_median_span_hours_2plus"] = float(cl.loc[cl.label_2plus, "span_hours"].median())
print(f"  {len(cl):,} clusters; {N['clusters_2plus']:,} have 2+ distinct complaints within 48 h "
      f"({N['clusters_2plus_share']:.1%} of clusters, {N['complaints_in_2plus_clusters_share']:.1%} of complaints)")

# ---------------------------------------------------------------- match to verified violations
with Timer("match clusters to heat violations (0-7 d, 0-14 d)"):
    hv = (v[v.vtype == "heat"][["building_id", "inspectiondate", "violationid"]]
          .rename(columns={"inspectiondate": "vdate"}).sort_values("vdate"))
    hw = (v[v.vtype == "hotwater"][["building_id", "inspectiondate"]]
          .rename(columns={"inspectiondate": "hwdate"}).sort_values("hwdate"))
    cl = cl.sort_values("start_date")
    m = pd.merge_asof(cl[["cluster_id", "building_id", "start_date"]], hv, left_on="start_date", right_on="vdate",
                      by="building_id", direction="forward", tolerance=pd.Timedelta(days=14))
    m2 = pd.merge_asof(cl[["cluster_id", "building_id", "start_date"]], hw, left_on="start_date", right_on="hwdate",
                       by="building_id", direction="forward", tolerance=pd.Timedelta(days=7))
    cl = cl.merge(m[["cluster_id", "vdate", "violationid"]], on="cluster_id", how="left")
    cl = cl.merge(m2[["cluster_id", "hwdate"]], on="cluster_id", how="left")
    cl["lag_days"] = (cl.vdate - cl.start_date).dt.days
    cl["confirmed7"] = cl.lag_days.le(7).fillna(False)
    cl["confirmed14"] = cl.lag_days.le(14).fillna(False)
    cl["hotwater_confirmed7"] = cl.hwdate.notna()
    cl["first_heat_violation_id"] = cl.violationid.astype("Int64")
    cl = cl.drop(columns=["violationid"])
    # strict scope for rates: heat-season clusters in the nine complete seasons (2017-18 .. 2025-26)
    scope = cl[cl.heat_season & cl.season.between(2017, 2025)].copy()
    scope["window"] = np.select([scope.season.isin(TRAIN_SEASONS), scope.season == TEST_SEASON], ["train 2018-25", "test 2025-26"], "2017-18")
    cl.to_csv(WORK / "clusters.csv", index=False)
N["scope_clusters"] = len(scope)
N["scope_clusters_2plus"] = int(scope.label_2plus.sum())


def rate_table(df, by, label):
    g = df.groupby(by, observed=True)
    out = pd.DataFrame({
        "n_clusters": g.size(),
        "n_confirmed_7d": g.confirmed7.sum(),
        "rate_7d": g.confirmed7.mean(),
        "n_confirmed_14d": g.confirmed14.sum(),
        "rate_14d": g.confirmed14.mean(),
        "hotwater_rate_7d": g.hotwater_confirmed7.mean(),
        "median_lag_days_confirmed": g.apply(lambda x: x.loc[x.confirmed14, "lag_days"].median()),
        "mean_complaints_per_cluster": g.n.mean(),
        "mean_apartments_per_cluster": g.n_apts.mean(),
    }).reset_index()
    out.insert(0, "dimension", label)
    return out


with Timer("confirmation rates"):
    rows = []
    for win_name, df in [("all seasons", scope), ("train 2018-25", scope[scope.window == "train 2018-25"]),
                         ("test 2025-26", scope[scope.window == "test 2025-26"])]:
        tiers = pd.concat([
            df.assign(level="1 complaint")[df.n == 1],
            df.assign(level="2+ complaints (primary label)")[df.n >= 2],
            df.assign(level="2+ non-duplicate complaints")[df.n_nondup >= 2],
            df.assign(level="2+ complaints from 2+ apartments")[df.label_2plus_2apts],
            df.assign(level="3+ complaints")[df.n >= 3],
            df.assign(level="5+ complaints")[df.n >= 5],
            df.assign(level="exactly 2")[df.n == 2],
            df.assign(level="exactly 3-4")[df.tier == "3-4"],
        ])
        t = rate_table(tiers, "level", "cluster tier"); t.insert(0, "window", win_name); rows.append(t)
        two = df[df.n >= 2]
        for by, lab in [("band", "TMIN band on cluster start day (2+ clusters)"),
                        ("band48", "coldest TMIN over start day and next day (2+ clusters)"),
                        ("size_bucket", "building size, unitsres (2+ clusters)"),
                        ("era", "construction era, yearbuilt (2+ clusters)"),
                        ("altered", "yearalter1 > 0 (2+ clusters)"),
                        ("res3plus", "in 3+ unit PLUTO universe (2+ clusters)"),
                        ("multi_building_lot", "lot holds more than one building (2+ clusters)"),
                        ("borough", "borough (2+ clusters)")]:
            t = rate_table(two, by, lab).rename(columns={by: "level"}); t.insert(0, "window", win_name); rows.append(t)
        fr = two.assign(level=np.where(two.frigid25, "Frigid widened (<25 F)", "25 F and above"))
        t = rate_table(fr, "level", "widened frigid band, start-day TMIN (2+ clusters)"); t.insert(0, "window", win_name); rows.append(t)
        one = df[df.n == 1]
        t = rate_table(one, "band", "TMIN band on cluster start day (single-complaint clusters)").rename(columns={"band": "level"})
        t.insert(0, "window", win_name); rows.append(t)
        # era x band for pre-war
        pw = two[two.era == "1901-1939 pre-war"]
        t = rate_table(pw, "band", "pre-war 1901-1939 buildings by TMIN band (2+ clusters)").rename(columns={"band": "level"})
        t.insert(0, "window", win_name); rows.append(t)
    summary = pd.concat(rows, ignore_index=True)
    summary.to_csv(OUT / "violation_confirmation_summary.csv", index=False)

    def pick(win, dim, lvl, col="rate_7d"):
        r = summary[(summary.window == win) & (summary.dimension == dim) & (summary.level.astype(str) == lvl)]
        return float(r[col].iloc[0]) if len(r) else float("nan")

    for win in ("all seasons", "train 2018-25", "test 2025-26"):
        k = win.replace(" ", "_").replace("-", "_")
        N[f"rate7_1_{k}"] = pick(win, "cluster tier", "1 complaint")
        N[f"rate7_2plus_{k}"] = pick(win, "cluster tier", "2+ complaints (primary label)")
        N[f"rate7_2plus_nondup_{k}"] = pick(win, "cluster tier", "2+ non-duplicate complaints")
        N[f"rate7_2plus_2apts_{k}"] = pick(win, "cluster tier", "2+ complaints from 2+ apartments")
        N[f"rate7_3plus_{k}"] = pick(win, "cluster tier", "3+ complaints")
        N[f"rate7_5plus_{k}"] = pick(win, "cluster tier", "5+ complaints")
        N[f"rate14_1_{k}"] = pick(win, "cluster tier", "1 complaint", "rate_14d")
        N[f"rate14_2plus_{k}"] = pick(win, "cluster tier", "2+ complaints (primary label)", "rate_14d")
        N[f"multiplier_2plus_vs_1_{k}"] = N[f"rate7_2plus_{k}"] / N[f"rate7_1_{k}"]
        N[f"multiplier_3plus_vs_1_{k}"] = N[f"rate7_3plus_{k}"] / N[f"rate7_1_{k}"]
        N[f"n_1_{k}"] = int(summary[(summary.window == win) & (summary.dimension == "cluster tier") & (summary.level == "1 complaint")].n_clusters.iloc[0])
        N[f"n_2plus_{k}"] = int(summary[(summary.window == win) & (summary.dimension == "cluster tier") & (summary.level == "2+ complaints (primary label)")].n_clusters.iloc[0])
        for band in BAND_ORDER:
            N[f"rate7_2plus_band_{band}_{k}"] = pick(win, "TMIN band on cluster start day (2+ clusters)", band)
        for sz in SIZE_ORDER:
            N[f"rate7_2plus_size_{sz}_{k}"] = pick(win, "building size, unitsres (2+ clusters)", sz)
        for er in ERA_ORDER:
            N[f"rate7_2plus_era_{er}_{k}"] = pick(win, "construction era, yearbuilt (2+ clusters)", er)
        N[f"rate7_2plus_altered_True_{k}"] = pick(win, "yearalter1 > 0 (2+ clusters)", "True")
        N[f"rate7_2plus_altered_False_{k}"] = pick(win, "yearalter1 > 0 (2+ clusters)", "False")
    print(summary[(summary.window == "all seasons") & (summary.dimension == "cluster tier")]
          [["level", "n_clusters", "rate_7d", "rate_14d", "median_lag_days_confirmed"]].to_string(index=False))

# ---------------------------------------------------------------- Stream 5's exact day-grid label, for reference
with Timer("Stream 5 day-grid label check"):
    bd = hc.groupby(["building_id", "day"]).complaint_id.size().rename("n").reset_index()
    nxt = bd.copy(); nxt["day"] -= pd.Timedelta(days=1); nxt = nxt.rename(columns={"n": "n_next"})
    lab = bd.merge(nxt, on=["building_id", "day"], how="outer").fillna(0)
    lab["failed48"] = (lab.n + lab.n_next) >= 2
    lab["season"] = season(lab.day)
    lab = lab[in_heat_season(lab.day) & lab.season.between(2017, 2025) & lab.failed48].sort_values("day")
    mm = pd.merge_asof(lab, hv, left_on="day", right_on="vdate", by="building_id", direction="forward",
                       tolerance=pd.Timedelta(days=7))
    lab["confirmed7"] = mm.vdate.notna().to_numpy()
    N["stream5_daygrid_positives"] = len(lab)
    N["stream5_daygrid_positives_train"] = int(lab.season.isin(TRAIN_SEASONS).sum())
    N["stream5_daygrid_positives_test"] = int((lab.season == TEST_SEASON).sum())
    N["stream5_daygrid_rate7"] = float(lab.confirmed7.mean())
    N["stream5_daygrid_rate7_test"] = float(lab.loc[lab.season == TEST_SEASON, "confirmed7"].mean())
    # latest 2+ cluster that started no later than d+1; the positive sits inside it if that cluster ends on/after d
    c2 = cl.loc[cl.label_2plus, ["building_id", "start_date", "end_ts"]].sort_values("start_date")
    lab2 = lab[["building_id", "day"]].copy()
    lab2["day_plus1"] = lab2.day + pd.Timedelta(days=1)
    lab2 = lab2.sort_values("day_plus1")
    mm2 = pd.merge_asof(lab2, c2, left_on="day_plus1", right_on="start_date", by="building_id", direction="backward")
    inside = mm2.start_date.notna() & (mm2.end_ts.dt.normalize() >= mm2.day)
    N["stream5_daygrid_positives_inside_2plus_cluster_share"] = float(inside.mean())
print(f"  Stream 5 day-grid positives {N['stream5_daygrid_positives']:,}; 7-day confirmation {N['stream5_daygrid_rate7']:.1%}")

# ---------------------------------------------------------------- inspector saturation by day
with Timer("saturation by day"):
    d2 = scope[scope.label_2plus]
    per_day = (scope.groupby("start_date").agg(clusters_started=("cluster_id", "size"),
                                               clusters_2plus_started=("label_2plus", "sum"),
                                               rate_7d_all_clusters=("confirmed7", "mean"))
               .join(d2.groupby("start_date").agg(confirmed_7d_2plus=("confirmed7", "sum"),
                                                  rate_7d_2plus=("confirmed7", "mean"),
                                                  rate_14d_2plus=("confirmed14", "mean"),
                                                  median_lag_days_2plus=("lag_days", "median")))
               .reset_index().rename(columns={"start_date": "day"}))
    rows_day = pd.read_csv(WORK / "heat_rows.csv", usecols=["day", "is_dup", "complaint_id", "building_id"], parse_dates=["day"])
    rd = rows_day.groupby("day").agg(problem_rows=("complaint_id", "size"), duplicate_rows=("is_dup", "sum"),
                                     complaints=("complaint_id", "nunique"), buildings=("building_id", "nunique")).reset_index()
    rd["duplicate_row_share"] = rd.duplicate_rows / rd.problem_rows
    del rows_day
    vi = hv.groupby("vdate").size().rename("heat_violations_inspected").reset_index().rename(columns={"vdate": "day"})
    sat = days.loc[~days.holiday_gap, ["day", "season", "heat_season", "TMIN", "TMAX", "tmin_lag1", "band", "wday"]].merge(rd, on="day", how="left")
    sat = sat.merge(per_day, on="day", how="left").merge(vi, on="day", how="left")
    sat = sat[sat.heat_season & sat.season.between(2017, 2025)].sort_values("day")
    for k in ("problem_rows", "duplicate_rows", "complaints", "buildings", "clusters_started", "clusters_2plus_started",
              "confirmed_7d_2plus", "heat_violations_inspected"):
        sat[k] = sat[k].fillna(0).astype(int)
    sat["heat_violations_inspected_next_7d"] = sat.groupby("season").heat_violations_inspected.transform(
        lambda s: s[::-1].rolling(8, min_periods=1).sum()[::-1])
    sat["inspections_per_100_complaints_7d"] = 100 * sat.heat_violations_inspected_next_7d / sat.complaints.replace(0, np.nan)
    sat["volume_bin"] = pd.cut(sat.complaints, [-1, 500, 1000, 2000, 3000, 4500, 10 ** 6],
                               labels=["0-500", "501-1000", "1001-2000", "2001-3000", "3001-4500", "4500+"])
    sat["feb_7_9_2026"] = sat.day.isin(SNAP_DAYS)
    sat.to_csv(OUT / "violation_saturation_by_day.csv", index=False)

    test = sat[sat.season == TEST_SEASON]
    snap = test[test.feb_7_9_2026]
    N["snap_complaints"] = int(snap.complaints.sum())
    N["snap_buildings_by_day"] = snap.buildings.tolist()
    N["snap_peak_day_complaints"] = int(test.complaints.max())
    N["snap_peak_day"] = test.loc[test.complaints.idxmax(), "day"]
    N["snap_clusters_2plus"] = int(snap.clusters_2plus_started.sum())
    N["snap_rate7_2plus"] = float(snap.confirmed_7d_2plus.sum() / max(snap.clusters_2plus_started.sum(), 1))
    N["snap_duplicate_row_share"] = float(snap.duplicate_rows.sum() / snap.problem_rows.sum())
    N["snap_median_lag"] = float(d2[d2.start_date.isin(SNAP_DAYS)].lag_days.median())
    N["snap_tmin"] = snap.TMIN.tolist()
    # late-January 2026 sub-freezing stretch: the longest run of TMIN < 32 days in Jan 2026
    jan = test[(test.day >= "2026-01-15") & (test.day <= "2026-02-05")].copy()
    jan["run"] = (jan.TMIN >= 32).cumsum()
    runs = jan[jan.TMIN < 32].groupby("run")
    best = max(runs, key=lambda kv: len(kv[1]))[1] if len(jan[jan.TMIN < 32]) else jan.iloc[:0]
    N["late_jan_run_days"] = len(best)
    N["late_jan_run_start"], N["late_jan_run_end"] = (best.day.min(), best.day.max()) if len(best) else (None, None)
    N["late_jan_run_complaints"] = int(best.complaints.sum())
    N["late_jan_run_clusters_2plus"] = int(best.clusters_2plus_started.sum())
    N["late_jan_run_rate7_2plus"] = float(best.confirmed_7d_2plus.sum() / max(best.clusters_2plus_started.sum(), 1))
    N["late_jan_run_duplicate_row_share"] = float(best.duplicate_rows.sum() / max(best.problem_rows.sum(), 1))
    # surge vs moderate cold days in 2025-26
    surge = test[test.complaints >= 4000]
    moderate = test[(test.band.isin(["Freezing", "Frigid"])) & (test.complaints.between(800, 2000))]
    N["test_surge_days"] = len(surge)
    N["test_surge_rate7_2plus"] = float(surge.confirmed_7d_2plus.sum() / max(surge.clusters_2plus_started.sum(), 1))
    N["test_surge_median_lag"] = float(d2[d2.start_date.isin(surge.day)].lag_days.median())
    N["test_surge_dup_share"] = float(surge.duplicate_rows.sum() / max(surge.problem_rows.sum(), 1))
    N["test_surge_inspections_per_100_complaints_7d"] = float(100 * surge.heat_violations_inspected_next_7d.sum() / max(surge.complaints.sum(), 1))
    N["test_moderate_days"] = len(moderate)
    N["test_moderate_rate7_2plus"] = float(moderate.confirmed_7d_2plus.sum() / max(moderate.clusters_2plus_started.sum(), 1))
    N["test_moderate_median_lag"] = float(d2[d2.start_date.isin(moderate.day)].lag_days.median())
    N["test_moderate_dup_share"] = float(moderate.duplicate_rows.sum() / max(moderate.problem_rows.sum(), 1))
    N["test_moderate_inspections_per_100_complaints_7d"] = float(100 * moderate.heat_violations_inspected_next_7d.sum() / max(moderate.complaints.sum(), 1))
    # volume bins within the sub-freezing bands, all seasons: same temperature, more volume -> lower confirmation
    sub = sat[sat.band.isin(["Frigid", "Freezing"])]
    vb = sub.groupby("volume_bin", observed=True).agg(days=("day", "size"), complaints=("complaints", "sum"),
                                                     clusters_2plus=("clusters_2plus_started", "sum"),
                                                     confirmed=("confirmed_7d_2plus", "sum"),
                                                     mean_tmin=("TMIN", "mean"), dup_share=("duplicate_row_share", "mean"))
    vb["rate_7d_2plus"] = vb.confirmed / vb.clusters_2plus
    vb = vb.reset_index()
    vb.insert(0, "dimension", "daily complaint volume bin, Frigid+Freezing days, all seasons (2+ clusters)")
    vb = vb.rename(columns={"volume_bin": "level"})
    N["volume_bins_subfreezing"] = vb.to_dict(orient="records")
    vb.to_csv(OUT / "violation_saturation_by_volume.csv", index=False)
    # a per-day regression-free summary: correlation of volume and confirmation among sub-freezing days
    sub2 = sub[sub.clusters_2plus_started >= 20]
    N["corr_volume_vs_rate7_subfreezing_days"] = float(sub2[["complaints", "rate_7d_2plus"]].corr().iloc[0, 1])
    N["corr_tmin_vs_rate7_subfreezing_days"] = float(sub2[["TMIN", "rate_7d_2plus"]].corr().iloc[0, 1])
    # top 10 test-season days by volume
    N["test_top10_days"] = test.nlargest(10, "complaints")[["day", "TMIN", "complaints", "buildings", "clusters_2plus_started",
                                                            "rate_7d_2plus", "duplicate_row_share", "median_lag_days_2plus"]].to_dict(orient="records")
print(f"  Feb 7-9 2026: {N['snap_complaints']:,} complaints, {N['snap_clusters_2plus']:,} 2+ clusters, "
      f"7-day confirmation {N['snap_rate7_2plus']:.1%} vs {N['test_moderate_rate7_2plus']:.1%} on moderate cold days")
print(vb[["level", "days", "complaints", "clusters_2plus", "rate_7d_2plus", "mean_tmin"]].to_string(index=False))

# ---------------------------------------------------------------- figure
with Timer("figure"):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": PAL["ink2"],
                         "xtick.color": PAL["muted"], "ytick.color": PAL["muted"], "axes.titlecolor": PAL["ink"],
                         "figure.facecolor": PAL["surface"], "axes.facecolor": PAL["surface"]})
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    # (a) confirmation by tier
    ax = axes[0]
    tiers = summary[(summary.window == "all seasons") & (summary.dimension == "cluster tier")]
    order = ["1 complaint", "2+ complaints (primary label)", "2+ non-duplicate complaints", "3+ complaints", "5+ complaints"]
    tiers = tiers.set_index("level").loc[order]
    y = np.arange(len(order))
    ax.barh(y + 0.18, tiers.rate_14d * 100, height=0.36, color="#86b6ef", label="within 14 days")
    ax.barh(y - 0.18, tiers.rate_7d * 100, height=0.36, color=PAL["blue"], label="within 7 days")
    for i, (r7, n) in enumerate(zip(tiers.rate_7d, tiers.n_clusters)):
        ax.text(r7 * 100 + 0.4, i - 0.18, f"{r7*100:.1f}%  (n={n:,})", va="center", fontsize=8, color=PAL["ink2"])
    ax.set_yticks(y); ax.set_yticklabels(["1 complaint", "2+ (label)", "2+ non-dup", "3+", "5+"]); ax.invert_yaxis()
    ax.set_xlabel("clusters followed by a verified heat violation, %"); ax.set_title("Confirmation rate by cluster tier, 2017-18 to 2025-26", loc="left", fontsize=10)
    ax.legend(frameon=False, loc="lower right"); ax.grid(axis="x", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    # (b) by band, train vs test
    ax = axes[1]
    w = 0.36
    for j, (win, col) in enumerate([("train 2018-25", PAL["blue"]), ("test 2025-26", PAL["orange"])]):
        bb = summary[(summary.window == win) & (summary.dimension == "TMIN band on cluster start day (2+ clusters)")].set_index("level").reindex(BAND_ORDER)
        ax.bar(np.arange(4) + (j - 0.5) * w, bb.rate_7d * 100, width=w, color=col, label=win)
        for i, r in enumerate(bb.rate_7d):
            ax.text(i + (j - 0.5) * w, r * 100 + 0.3, f"{r*100:.1f}", ha="center", fontsize=8, color=PAL["ink2"])
    ax.set_xticks(range(4)); ax.set_xticklabels(["Frigid <20 F", "Freezing 20-31", "Cold 32-44", "Mild 45+"])
    ax.set_ylabel("7-day confirmation of 2+ clusters, %"); ax.set_title("7-day confirmation of the 2+ label by TMIN band on the start day", loc="left", fontsize=10)
    ax.legend(frameon=False); ax.grid(axis="y", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    # (c) saturation scatter, 2025-26
    ax = axes[2]
    tt = test[test.clusters_2plus_started >= 10]
    for band in BAND_ORDER:
        q = tt[tt.band == band]
        ax.scatter(q.complaints, q.rate_7d_2plus * 100, s=22 + q.clusters_2plus_started / 15, color=BAND_COLOR[band],
                   edgecolor="white", linewidth=0.6, label=band, alpha=0.95)
    for _, r in tt[tt.feb_7_9_2026].iterrows():
        ax.annotate(r.day.strftime("%b %d"), (r.complaints, r.rate_7d_2plus * 100), textcoords="offset points",
                    xytext=(6, 4), fontsize=8, color=PAL["ink"])
    ax.set_xlabel("heat complaints received that day (2025-26 season)"); ax.set_ylabel("7-day confirmation of 2+ clusters started that day, %")
    ax.set_title("2025-26 days: confirmation vs same-day complaint volume (Feb 8 peak lowest)", loc="left", fontsize=10)
    ax.legend(frameon=False, title="TMIN band", fontsize=8); ax.grid(color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "fig_violation_confirmation.png", dpi=160)
    plt.close(fig)

save_numbers("02_violation_tier", N)
print("STEP 2 complete")
