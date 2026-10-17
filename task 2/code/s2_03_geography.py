"""STEP 3 / Deliverable 2: geography, Bronx Community Districts 7, 4 and 5 pitch numbers.

Joins the cleaned heat complaints, the 48 h failure clusters, the verified heat
violations and the Forecast-Only / Chronic groups to PLUTO (all 858,284 lots, so
1-2 unit homes count too) and aggregates by Community District (cd) and City
Council District (council). PLUTO is attached on bbl only; HPD tables were joined
on building_id upstream.

Outputs (out/): cd_level_map_data.csv, council_district_summary.csv,
                focus_districts_table.csv, fig_bronx_cd_impact.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from s2_common import WORK, OUT, TEST_SEASON, SNAP_DAYS, save_numbers, Timer

PAL = {"blue": "#2a78d6", "orange": "#eb6834", "muted": "#898781", "ink": "#0b0b0b", "ink2": "#52514e",
       "grid": "#e1e0d9", "surface": "#fcfcfb", "light": "#9ec5f4"}
FOCUS = [207, 204, 205, 112, 314]
BORO = {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}
HOUSEHOLD = 2.55   # persons per occupied unit, New York City average (American Community Survey); an assumption, stated in the report
N = {}

with Timer("load"):
    hc = pd.read_csv(WORK / "heat_complaints.csv", parse_dates=["first_ts", "day"])
    cl = pd.read_csv(WORK / "clusters.csv", parse_dates=["start_date", "vdate"])
    v = pd.read_csv(WORK / "violations_clean.csv", parse_dates=["inspectiondate"])
    u = pd.read_csv(WORK / "buildings_universe.csv")
    p = pd.read_csv(WORK / "pluto_all.csv")
    fo = pd.read_csv(OUT / "forecast_only_buildings.csv", usecols=["building_id", "group", "forecast_only_strict", "forecast_only_broad", "chronic"])

# ---------------------------------------------------------------- per-building totals
with Timer("per-building totals"):
    B = u[["building_id", "bbl", "bin", "borough", "cd", "council", "unitsres", "in_pluto", "res3plus", "latitude", "longitude"]].copy()
    scope = hc[hc.heat_season & hc.season.between(2017, 2025)]
    B["complaints_all"] = B.building_id.map(scope.groupby("building_id").size())
    B["complaints_2025_26"] = B.building_id.map(hc[(hc.season == TEST_SEASON) & hc.heat_season].groupby("building_id").size())
    c2 = cl[cl.label_2plus & cl.heat_season & cl.season.between(2017, 2025)]
    B["fail48_all"] = B.building_id.map(c2.groupby("building_id").size())
    B["fail48_2025_26"] = B.building_id.map(c2[c2.season == TEST_SEASON].groupby("building_id").size())
    B["fail48_verified_all"] = B.building_id.map(c2[c2.confirmed7].groupby("building_id").size())
    hv = v[(v.vtype == "heat") & v.season.between(2017, 2025)]
    B["violations_heat_all"] = B.building_id.map(hv.groupby("building_id").size())
    B["violations_heat_2025_26"] = B.building_id.map(hv[hv.season == TEST_SEASON].groupby("building_id").size())
    B["snap_complaints"] = B.building_id.map(hc[hc.day.isin(SNAP_DAYS)].groupby("building_id").size())
    B["snap_fail48"] = B.building_id.map(c2[c2.start_date.isin(SNAP_DAYS)].groupby("building_id").size())
    B = B.merge(fo, on="building_id", how="left")
    for k in ("complaints_all", "complaints_2025_26", "fail48_all", "fail48_2025_26", "fail48_verified_all",
              "violations_heat_all", "violations_heat_2025_26", "snap_complaints", "snap_fail48"):
        B[k] = B[k].fillna(0).astype(int)
    for k in ("forecast_only_strict", "forecast_only_broad", "chronic"):
        B[k] = B[k].fillna(False).astype(bool)
    B["complained_all"] = B.complaints_all > 0
    B["complained_2025_26"] = B.complaints_2025_26 > 0
    B["snap_building"] = B.snap_complaints > 0
    B["snap_failed_building"] = B.snap_fail48 > 0
    N["complaints_all_total"] = int(B.complaints_all.sum())
    N["complaints_2025_26_total"] = int(B.complaints_2025_26.sum())
    N["complaints_with_cd_share"] = float(B.loc[B.cd.notna(), "complaints_all"].sum() / B.complaints_all.sum())
    N["snap_complaints_total"] = int(B.snap_complaints.sum())
    N["snap_buildings_total"] = int(B.snap_building.sum())
    N["snap_failed_buildings_total"] = int(B.snap_failed_building.sum())
    N["snap_units_in_complaining_buildings"] = float(B.loc[B.snap_building, "unitsres"].sum())


def aggregate(key):
    base = p[p[key].notna()].copy()
    base[key] = base[key].astype(int)
    g = base.groupby(key)
    d = pd.DataFrame({
        "lots_total": g.size(),
        "residential_buildings_all": g.unitsres.apply(lambda s: (s >= 1).sum()),
        "residential_buildings_3plus": g.unitsres.apply(lambda s: (s >= 3).sum()),
        "residential_units": g.unitsres.sum(),
        "residential_units_3plus": g.unitsres.apply(lambda s: s[s >= 3].sum()),
        "latitude_centroid": g.latitude.mean(), "longitude_centroid": g.longitude.mean(),
        "latitude_min": g.latitude.min(), "latitude_max": g.latitude.max(),
        "longitude_min": g.longitude.min(), "longitude_max": g.longitude.max(),
    })
    bb = B[B[key].notna()].copy()
    bb[key] = bb[key].astype(int)
    gb = bb.groupby(key)
    d2 = pd.DataFrame({
        "complaining_buildings_all_seasons": gb.complained_all.sum(),
        "complaining_buildings_2025_26": gb.complained_2025_26.sum(),
        "heat_complaints_all_seasons": gb.complaints_all.sum(),
        "heat_complaints_2025_26": gb.complaints_2025_26.sum(),
        "failure_events_48h_all_seasons": gb.fail48_all.sum(),
        "failure_events_48h_2025_26": gb.fail48_2025_26.sum(),
        "failure_events_48h_verified_7d_all_seasons": gb.fail48_verified_all.sum(),
        "heat_violations_all_seasons": gb.violations_heat_all.sum(),
        "heat_violations_2025_26": gb.violations_heat_2025_26.sum(),
        "chronic_buildings": gb.chronic.sum(),
        "forecast_only_strict_buildings": gb.forecast_only_strict.sum(),
        "forecast_only_broad_buildings": gb.forecast_only_broad.sum(),
        "feb7_9_2026_complaints": gb.snap_complaints.sum(),
        "feb7_9_2026_buildings": gb.snap_building.sum(),
        "feb7_9_2026_failure_events_48h": gb.snap_fail48.sum(),
        "feb7_9_2026_units_in_complaining_buildings": gb.apply(lambda x: x.loc[x.snap_building, "unitsres"].sum()),
    })
    d = d.join(d2).fillna(0)
    for c in d2.columns:
        d[c] = d[c].astype(int) if c != "feb7_9_2026_units_in_complaining_buildings" else d[c]
    d["complaints_per_residential_building_all_seasons"] = d.heat_complaints_all_seasons / d.residential_buildings_all.replace(0, np.nan)
    d["complaints_per_100_units_all_seasons"] = 100 * d.heat_complaints_all_seasons / d.residential_units.replace(0, np.nan)
    d["complaints_per_100_units_2025_26"] = 100 * d.heat_complaints_2025_26 / d.residential_units.replace(0, np.nan)
    d["complaints_per_residential_building_2025_26"] = d.heat_complaints_2025_26 / d.residential_buildings_all.replace(0, np.nan)
    d["failure_events_48h_per_100_units_2025_26"] = 100 * d.failure_events_48h_2025_26 / d.residential_units.replace(0, np.nan)
    d["heat_violations_per_1000_units_2025_26"] = 1000 * d.heat_violations_2025_26 / d.residential_units.replace(0, np.nan)
    d["feb7_9_2026_complaints_per_1000_units"] = 1000 * d.feb7_9_2026_complaints / d.residential_units.replace(0, np.nan)
    d["share_of_city_units"] = d.residential_units / d.residential_units.sum()
    d["share_of_city_complaints_2025_26"] = d.heat_complaints_2025_26 / d.heat_complaints_2025_26.sum()
    d["share_of_city_feb7_9_complaints"] = d.feb7_9_2026_complaints / d.feb7_9_2026_complaints.sum()
    d["rank_complaints_per_100_units_2025_26"] = d.complaints_per_100_units_2025_26.rank(ascending=False, method="min")
    d["rank_heat_complaints_2025_26"] = d.heat_complaints_2025_26.rank(ascending=False, method="min")
    d["estimated_tenants"] = d.residential_units * HOUSEHOLD
    return d.reset_index()


with Timer("community districts"):
    cd = aggregate("cd")
    cd["borough"] = (cd.cd // 100).map(BORO)
    cd["district_number"] = cd.cd % 100
    cd["is_joint_interest_area"] = cd.district_number > 18
    cd["cd_label"] = cd.borough + " CD " + cd.district_number.astype(str)
    cd["focus_district"] = cd.cd.isin(FOCUS)
    front = ["cd", "cd_label", "borough", "district_number", "is_joint_interest_area", "focus_district"]
    cd = cd[front + [c for c in cd.columns if c not in front]]
    cd.to_csv(OUT / "cd_level_map_data.csv", index=False)
    real = cd[~cd.is_joint_interest_area]
    N["cd_count"] = len(real)
    focus = real[real.focus_district].set_index("cd").loc[FOCUS].reset_index()
    rest = real[~real.focus_district]
    tot = real

    def pack(df, label):
        return {"district": label,
                "residential_buildings_all": int(df.residential_buildings_all.sum()),
                "residential_buildings_3plus": int(df.residential_buildings_3plus.sum()),
                "residential_units": float(df.residential_units.sum()),
                "estimated_tenants": float(df.residential_units.sum() * HOUSEHOLD),
                "heat_complaints_all_seasons": int(df.heat_complaints_all_seasons.sum()),
                "heat_complaints_2025_26": int(df.heat_complaints_2025_26.sum()),
                "complaints_per_100_units_2025_26": float(100 * df.heat_complaints_2025_26.sum() / df.residential_units.sum()),
                "complaints_per_residential_building_2025_26": float(df.heat_complaints_2025_26.sum() / df.residential_buildings_all.sum()),
                "failure_events_48h_2025_26": int(df.failure_events_48h_2025_26.sum()),
                "heat_violations_2025_26": int(df.heat_violations_2025_26.sum()),
                "heat_violations_per_1000_units_2025_26": float(1000 * df.heat_violations_2025_26.sum() / df.residential_units.sum()),
                "chronic_buildings": int(df.chronic_buildings.sum()),
                "forecast_only_strict_buildings": int(df.forecast_only_strict_buildings.sum()),
                "forecast_only_broad_buildings": int(df.forecast_only_broad_buildings.sum()),
                "feb7_9_2026_complaints": int(df.feb7_9_2026_complaints.sum()),
                "feb7_9_2026_buildings": int(df.feb7_9_2026_buildings.sum()),
                "feb7_9_2026_failure_events_48h": int(df.feb7_9_2026_failure_events_48h.sum()),
                "feb7_9_2026_units_in_complaining_buildings": float(df.feb7_9_2026_units_in_complaining_buildings.sum()),
                "feb7_9_2026_complaints_per_1000_units": float(1000 * df.feb7_9_2026_complaints.sum() / df.residential_units.sum()),
                "share_of_city_units": float(df.residential_units.sum() / tot.residential_units.sum()),
                "share_of_city_complaints_2025_26": float(df.heat_complaints_2025_26.sum() / tot.heat_complaints_2025_26.sum()),
                "share_of_city_feb7_9_complaints": float(df.feb7_9_2026_complaints.sum() / tot.feb7_9_2026_complaints.sum())}

    rows = [pack(focus[focus.cd == c], focus.loc[focus.cd == c, "cd_label"].iloc[0]) for c in FOCUS]
    rows.append(pack(focus[focus.cd.isin([207, 204, 205])], "Bronx CD 7 + 4 + 5 together"))
    rows.append(pack(focus, "all five focus districts"))
    rows.append(pack(rest, "rest of New York City (54 other districts)"))
    rows.append(pack(tot, "New York City total"))
    ft = pd.DataFrame(rows)
    ft.to_csv(OUT / "focus_districts_table.csv", index=False)
    N["focus_table"] = rows
    N["top10_cd_by_complaints_per_100_units_2025_26"] = real.nsmallest(10, "rank_complaints_per_100_units_2025_26")[
        ["cd_label", "residential_units", "heat_complaints_2025_26", "complaints_per_100_units_2025_26", "feb7_9_2026_complaints",
         "chronic_buildings", "forecast_only_strict_buildings"]].to_dict(orient="records")
    N["top10_cd_by_complaints_2025_26"] = real.nsmallest(10, "rank_heat_complaints_2025_26")[
        ["cd_label", "heat_complaints_2025_26", "complaints_per_100_units_2025_26"]].to_dict(orient="records")
    N["focus_ranks_per_100_units"] = focus[["cd_label", "rank_complaints_per_100_units_2025_26", "rank_heat_complaints_2025_26"]].to_dict(orient="records")
print(ft[["district", "residential_units", "heat_complaints_2025_26", "complaints_per_100_units_2025_26",
          "feb7_9_2026_complaints", "forecast_only_strict_buildings"]].to_string(index=False))

with Timer("council districts"):
    cc = aggregate("council")
    cc = cc[cc.council.between(1, 51)]
    cc.to_csv(OUT / "council_district_summary.csv", index=False)
    N["council_count"] = len(cc)
    N["top10_council_by_complaints_per_100_units_2025_26"] = cc.nsmallest(10, "rank_complaints_per_100_units_2025_26")[
        ["council", "residential_units", "heat_complaints_2025_26", "complaints_per_100_units_2025_26", "feb7_9_2026_complaints"]].to_dict(orient="records")

# ---------------------------------------------------------------- figure
with Timer("figure"):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": PAL["ink2"],
                         "xtick.color": PAL["muted"], "ytick.color": PAL["muted"], "axes.titlecolor": PAL["ink"],
                         "figure.facecolor": PAL["surface"], "axes.facecolor": PAL["surface"]})
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4), gridspec_kw={"width_ratios": [1.1, 1.1, 1.3]})
    top = real.nlargest(15, "complaints_per_100_units_2025_26").sort_values("complaints_per_100_units_2025_26")
    ax = axes[0]
    ax.barh(top.cd_label, top.complaints_per_100_units_2025_26, color=np.where(top.focus_district, PAL["blue"], PAL["light"]))
    for i, (val, n) in enumerate(zip(top.complaints_per_100_units_2025_26, top.heat_complaints_2025_26)):
        ax.text(val + 0.3, i, f"{val:.1f}  ({n:,})", va="center", fontsize=8, color=PAL["ink2"])
    ax.set_xlabel("heat complaints per 100 residential units, 2025-26"); ax.set_title("Top 15 community districts, 2025-26 (focus districts in blue)", loc="left", fontsize=10)
    ax.grid(axis="x", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    top2 = real.nlargest(15, "feb7_9_2026_complaints_per_1000_units").sort_values("feb7_9_2026_complaints_per_1000_units")
    ax = axes[1]
    ax.barh(top2.cd_label, top2.feb7_9_2026_complaints_per_1000_units, color=np.where(top2.focus_district, PAL["blue"], PAL["light"]))
    for i, (val, n) in enumerate(zip(top2.feb7_9_2026_complaints_per_1000_units, top2.feb7_9_2026_complaints)):
        ax.text(val + 0.2, i, f"{val:.1f}  ({n:,})", va="center", fontsize=8, color=PAL["ink2"])
    ax.set_xlabel("heat complaints per 1,000 residential units, Feb 7-9, 2026"); ax.set_title("Cold-snap surge, Feb 7-9, 2026", loc="left", fontsize=10)
    ax.grid(axis="x", color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax = axes[2]
    rr = real[real.residential_units > 0]
    ax.scatter(rr.longitude_centroid, rr.latitude_centroid, s=rr.feb7_9_2026_complaints / 6 + 8,
               color=np.where(rr.focus_district, PAL["blue"], PAL["light"]), edgecolor="white", linewidth=0.6)
    offsets = {207: (8, 6), 204: (8, -10), 205: (-62, -12), 112: (-70, 8), 314: (8, -4)}
    for _, r in rr[rr.focus_district].iterrows():
        ax.annotate(r.cd_label, (r.longitude_centroid, r.latitude_centroid), textcoords="offset points",
                    xytext=offsets.get(int(r.cd), (7, 3)), fontsize=8, color=PAL["ink"])
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude"); ax.set_aspect(1 / np.cos(np.radians(40.7)))
    ax.set_title("District centroids, bubble = Feb 7-9, 2026 complaints", loc="left", fontsize=10)
    ax.grid(color=PAL["grid"]); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "fig_bronx_cd_impact.png", dpi=160)
    plt.close(fig)

save_numbers("03_geography", N)
print("STEP 3 complete")
