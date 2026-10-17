"""STEP 1: enforce the team traps and the Person 3 join rules, build the working tables.

Rules applied here (and nowhere else, so every later step inherits them):
  - building_id / bbl / bin cast to nullable Int64 after stripping decimal strings
  - HPD tables join to each other on building_id only; bbl is used only to attach PLUTO
  - heat-only filter: problem_code in (NO HEAT, NO HEAT AND NO HOT WATER)
  - the six Christmas-week logging-gap dates are dropped
  - violations: inspectiondate >= 2010-01-01; heat orders 666/966/674 vs hot water 670/970
  - currentstatus and problem_status_date are never loaded (post-event columns)

Outputs (work/):  heat_rows.csv, heat_complaints.csv, violations_clean.csv, pluto_all.csv,
                  buildings_universe.csv, days_weather.csv, forecast_daily.csv
"""
import numpy as np
import pandas as pd

from s2_common import (RAW, WORK, OUT, HOLIDAY_GAPS, HEAT_CODES, HEAT_ORDERS, HOTWATER_ORDERS,
                       season, in_heat_season, to_int64, tmin_band, size_bucket, era_bucket,
                       save_numbers, Timer)

N = {}

# ---------------------------------------------------------------- complaints
with Timer("load pseudonymized complaints"):
    c = pd.read_csv(WORK / "complaints_pseud.csv", dtype=str, keep_default_na=False)
N["raw_rows"] = len(c)
for k in ("building_id", "bbl", "bin", "complaint_id", "problem_id"):
    c[k] = to_int64(c[k])
c["received_ts"] = pd.to_datetime(c.received_date, format="%Y-%m-%dT%H:%M:%S.%f", errors="coerce")
c["day"] = c.received_ts.dt.normalize()
N["raw_distinct_complaints"] = int(c.complaint_id.nunique())
N["raw_date_min"], N["raw_date_max"] = c.day.min(), c.day.max()
N["rows_missing_building_id"] = int(c.building_id.isna().sum())

heat = c[c.problem_code.isin(HEAT_CODES)].copy()
del c
N["heat_rows"] = len(heat)
N["heat_share_of_rows"] = N["heat_rows"] / N["raw_rows"]
hol = heat.day.isin(HOLIDAY_GAPS)
N["heat_rows_on_holiday_gap_dates"] = int(hol.sum())
heat = heat[~hol]
heat["is_dup"] = heat.problem_duplicate_flag.eq("Y")
heat["is_anon"] = heat.complaint_anonymous_flag.eq("Y")
heat["season"] = season(heat.day)
heat["heat_season"] = in_heat_season(heat.day)
N["heat_rows_after_gap_drop"] = len(heat)
N["heat_distinct_complaints"] = int(heat.complaint_id.nunique())
N["heat_buildings"] = int(heat.building_id.nunique())
N["heat_rows_dup_share"] = float(heat.is_dup.mean())
N["heat_rows_anon_share"] = float(heat.is_anon.mean())
N["heat_rows_missing_bbl"] = int(heat.bbl.isna().sum())
N["heat_rows_missing_bin"] = int(heat.bin.isna().sum())
N["heat_distinct_complaints_2025_26"] = int(heat.loc[heat.season == 2025, "complaint_id"].nunique())
N["heat_rows_2025_26"] = int((heat.season == 2025).sum())
with Timer("write heat_rows.csv"):
    heat[["received_ts", "day", "complaint_id", "problem_id", "building_id", "bbl", "bin", "problem_code",
          "is_dup", "is_anon", "apt_hash", "season", "heat_season"]].to_csv(WORK / "heat_rows.csv", index=False)

# one row per distinct (building_id, complaint_id): the unit that the label and the tiers count
with Timer("collapse to distinct complaints"):
    g = heat.groupby(["building_id", "complaint_id"], sort=False)
    hc = g.agg(first_ts=("received_ts", "min"), n_rows=("problem_id", "size"), n_dup_rows=("is_dup", "sum"),
               is_anon=("is_anon", "max"), n_apts=("apt_hash", "nunique"),
               bbl=("bbl", "first"), bin=("bin", "first")).reset_index()
    hc["any_nondup"] = hc.n_rows > hc.n_dup_rows
    hc["day"] = hc.first_ts.dt.normalize()
    hc["season"] = season(hc.day)
    hc["heat_season"] = in_heat_season(hc.day)
N["heat_complaints_rows"] = len(hc)
N["heat_complaints_all_rows_duplicate_share"] = float(1 - hc.any_nondup.mean())
N["heat_complaints_anonymous_share"] = float(hc.is_anon.mean())
hc.to_csv(WORK / "heat_complaints.csv", index=False)
print(f"  heat rows {N['heat_rows_after_gap_drop']:,} -> distinct complaints {len(hc):,} at {N['heat_buildings']:,} buildings; "
      f"{N['heat_rows_dup_share']:.1%} of rows flagged duplicate, {N['heat_rows_anon_share']:.1%} anonymous")

# ---------------------------------------------------------------- violations
with Timer("violations"):
    v = pd.read_csv(WORK / "violations_pseud.csv", dtype=str, keep_default_na=False)
    N["violations_raw_rows"] = len(v)
    v["building_id"] = to_int64(v.buildingid)
    v["bbl"] = to_int64(v.bbl)
    v["bin"] = to_int64(v.bin)
    v["violationid"] = to_int64(v.violationid)
    v["ordernumber"] = pd.to_numeric(v.ordernumber, errors="coerce")   # float: isin() must return plain bools
    v["inspectiondate"] = pd.to_datetime(v.inspectiondate, errors="coerce").dt.normalize()
    v["novissueddate"] = pd.to_datetime(v.novissueddate, errors="coerce").dt.normalize()
    N["violations_inspection_date_min_raw"] = v.inspectiondate.min()
    pre = v.inspectiondate < "2010-01-01"
    N["violations_dropped_pre_2010"] = int(pre.sum())
    v = v[~pre & v.inspectiondate.notna()].copy()
    v["vtype"] = np.select([v.ordernumber.isin(HEAT_ORDERS), v.ordernumber.isin(HOTWATER_ORDERS)],
                           ["heat", "hotwater"], "other")
    v["season"] = season(v.inspectiondate)
    N["violations_kept"] = len(v)
    N["violations_heat"] = int((v.vtype == "heat").sum())
    N["violations_hotwater"] = int((v.vtype == "hotwater").sum())
    N["violations_other_orders"] = int((v.vtype == "other").sum())
    N["violations_inspection_date_max"] = v.inspectiondate.max()
    N["violations_heat_2025_26"] = int(((v.vtype == "heat") & (v.season == 2025)).sum())
    v[["violationid", "building_id", "bbl", "bin", "inspectiondate", "novissueddate", "ordernumber", "vtype",
       "apt_hash", "season"]].to_csv(WORK / "violations_clean.csv", index=False)
print(f"  violations kept {N['violations_kept']:,} (dropped {N['violations_dropped_pre_2010']:,} pre-2010); "
      f"heat {N['violations_heat']:,}, hot water {N['violations_hotwater']:,}; last inspection {N['violations_inspection_date_max'].date()}")

# ---------------------------------------------------------------- PLUTO (all lots, pulled on the server from 64uk-42ks)
with Timer("PLUTO"):
    p = pd.read_csv(RAW / "pluto_all_lots_64uk-42ks.csv", dtype=str, keep_default_na=False)
    p["bbl"] = to_int64(p.bbl)
    for k in ("cd", "council", "zipcode", "numbldgs", "numfloors", "unitsres", "unitstotal", "yearbuilt",
              "yearalter1", "bldgarea", "latitude", "longitude"):
        p[k] = pd.to_numeric(p[k], errors="coerce")
    p = p.dropna(subset=["bbl"]).drop_duplicates("bbl")
    p["borough"] = p.borough.map({"MN": "Manhattan", "BX": "Bronx", "BK": "Brooklyn", "QN": "Queens", "SI": "Staten Island"})
    p["res3plus"] = p.unitsres >= 3
    p["multi_building_lot"] = p.numbldgs > 1
    N["pluto_lots"] = len(p)
    N["pluto_res3plus_lots"] = int(p.res3plus.sum())
    N["pluto_res_any_lots"] = int((p.unitsres >= 1).sum())
    p.to_csv(WORK / "pluto_all.csv", index=False)
    team = pd.read_csv(RAW / "buildings.csv", usecols=["bbl"])
    team["bbl"] = to_int64(team.bbl)
    N["pluto_res3plus_overlap_with_team_file"] = int(p.loc[p.res3plus, "bbl"].isin(team.bbl).sum())
    N["team_res3plus_rows"] = len(team)
print(f"  PLUTO lots {N['pluto_lots']:,}; 3+ unit lots {N['pluto_res3plus_lots']:,} "
      f"({N['pluto_res3plus_overlap_with_team_file']:,} overlap the team's pluto_res3plus file of {N['team_res3plus_rows']:,})")

# ---------------------------------------------------------------- HPD Buildings (Active) + registrations: building_id -> bbl, bin
with Timer("HPD buildings + registrations"):
    hb = pd.read_csv(RAW / "hpd_buildings_active_kj4p-ruqc.csv", dtype=str, keep_default_na=False)
    hb = hb[hb.recordstatus.eq("Active")].copy()
    for k in ("buildingid", "boroid", "block", "lot", "bin", "legalstories", "legalclassa", "legalclassb"):
        hb[k] = pd.to_numeric(hb[k], errors="coerce")
    hb["bbl_hpd"] = (hb.boroid * 1_000_000_000 + hb.block * 10_000 + hb.lot).round().astype("Int64")
    hb.loc[(hb.block <= 0) | (hb.lot <= 0), "bbl_hpd"] = pd.NA
    hb = hb.rename(columns={"buildingid": "building_id", "bin": "bin_hpd", "communityboard": "hpd_communityboard"})
    hb["building_id"] = hb.building_id.astype("Int64")
    hb["bin_hpd"] = hb.bin_hpd.astype("Int64")
    hb = hb.drop_duplicates("building_id")
    N["hpd_buildings_active"] = len(hb)
    rg = pd.read_csv(RAW / "hpd_registrations_tesw-yqqr.csv", dtype=str, keep_default_na=False)
    for k in ("buildingid", "boroid", "block", "lot", "bin"):
        rg[k] = pd.to_numeric(rg[k], errors="coerce")
    rg["bbl_reg"] = (rg.boroid * 1_000_000_000 + rg.block * 10_000 + rg.lot).round().astype("Int64")
    rg = rg.rename(columns={"buildingid": "building_id", "bin": "bin_reg"})
    rg["building_id"] = rg.building_id.astype("Int64")
    rg["bin_reg"] = rg.bin_reg.astype("Int64")
    rg = rg.sort_values("lastregistrationdate").drop_duplicates("building_id", keep="last")
    N["hpd_registrations_rows"] = len(rg)

# ---------------------------------------------------------------- building universe keyed by building_id
with Timer("building universe"):
    ids = pd.Index(hc.building_id.dropna().unique()).union(v.building_id.dropna().unique())
    u = pd.DataFrame({"building_id": ids.astype("Int64")})

    def modal(df, key, col):
        t = df.dropna(subset=[col]).groupby([key, col]).size().reset_index(name="n")
        t = t.sort_values([key, "n"], ascending=[True, False]).drop_duplicates(key)
        return t[[key, col]]

    u = u.merge(modal(heat, "building_id", "bbl").rename(columns={"bbl": "bbl_cmp"}), on="building_id", how="left")
    u = u.merge(modal(heat, "building_id", "bin").rename(columns={"bin": "bin_cmp"}), on="building_id", how="left")
    u = u.merge(modal(v, "building_id", "bbl").rename(columns={"bbl": "bbl_vio"}), on="building_id", how="left")
    u = u.merge(modal(v, "building_id", "bin").rename(columns={"bin": "bin_vio"}), on="building_id", how="left")
    u = u.merge(hb[["building_id", "bbl_hpd", "bin_hpd", "hpd_communityboard", "legalstories", "legalclassa", "legalclassb"]],
                on="building_id", how="left")
    u = u.merge(rg[["building_id", "bbl_reg", "bin_reg"]], on="building_id", how="left")
    u["in_hpd_active"] = u.bbl_hpd.notna() | u.bin_hpd.notna()
    u["bbl"] = u.bbl_cmp.fillna(u.bbl_vio).fillna(u.bbl_hpd).fillna(u.bbl_reg).astype("Int64")
    u["bbl_source"] = np.select([u.bbl_cmp.notna(), u.bbl_vio.notna(), u.bbl_hpd.notna(), u.bbl_reg.notna()],
                                ["complaints", "violations", "hpd_buildings", "registrations"], "none")
    u["bin"] = u.bin_cmp.fillna(u.bin_vio).fillna(u.bin_hpd).fillna(u.bin_reg).astype("Int64")
    u["bin_source"] = np.select([u.bin_cmp.notna(), u.bin_vio.notna(), u.bin_hpd.notna(), u.bin_reg.notna()],
                                ["complaints", "violations", "hpd_buildings", "registrations"], "none")
    u["bbl_conflict_complaints_vs_hpd"] = u.bbl_cmp.notna() & u.bbl_hpd.notna() & (u.bbl_cmp != u.bbl_hpd)
    u = u.drop(columns=["bbl_cmp", "bbl_vio", "bbl_hpd", "bbl_reg", "bin_cmp", "bin_vio", "bin_hpd", "bin_reg"])
    pl = p[["bbl", "borough", "cd", "council", "zipcode", "bldgclass", "numbldgs", "numfloors", "unitsres", "unitstotal",
            "yearbuilt", "yearalter1", "bldgarea", "latitude", "longitude", "res3plus", "multi_building_lot"]]
    u = u.merge(pl, on="bbl", how="left")
    u["in_pluto"] = u.cd.notna()
    u["res3plus"] = u.res3plus.fillna(False).astype(bool)
    u["multi_building_lot"] = u.multi_building_lot.fillna(False).astype(bool)
    u["size_bucket"] = size_bucket(u.unitsres)
    u["era"] = era_bucket(u.yearbuilt)
    u["altered"] = (u.yearalter1.fillna(0) > 0)
    u["borough"] = u.borough.fillna(u.bbl.floordiv(1_000_000_000).map(
        {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}))
    # buildings per lot (how many HPD building ids share this bbl in the universe)
    u["buildings_on_lot_in_universe"] = u.groupby("bbl").building_id.transform("size")
    u.to_csv(WORK / "buildings_universe.csv", index=False)
    N["universe_buildings"] = len(u)
    N["universe_missing_bbl"] = int(u.bbl.isna().sum())
    N["universe_bbl_from_hpd_or_reg"] = int(u.bbl_source.isin(["hpd_buildings", "registrations"]).sum())
    N["universe_in_pluto"] = int(u.in_pluto.sum())
    N["universe_in_res3plus"] = int(u.res3plus.sum())
    N["universe_multi_building_lot"] = int(u.multi_building_lot.sum())
    N["universe_bbl_conflicts_complaints_vs_hpd"] = int(u.bbl_conflict_complaints_vs_hpd.sum())
    cmp_b = u[u.building_id.isin(hc.building_id)]
    N["complaint_buildings"] = len(cmp_b)
    N["complaint_buildings_in_pluto"] = int(cmp_b.in_pluto.sum())
    N["complaint_buildings_1_2_units"] = int((cmp_b.unitsres <= 2).sum())
    N["complaint_buildings_share_1_2_units"] = float((cmp_b.unitsres <= 2).mean())
    N["complaint_buildings_share_on_multi_building_lots"] = float(cmp_b.multi_building_lot.mean())
print(f"  universe {len(u):,} buildings; {N['universe_in_pluto']:,} matched to PLUTO on bbl, "
      f"{N['universe_in_res3plus']:,} in the 3+ unit model universe, {N['universe_multi_building_lot']:,} sit on multi-building lots")

# ---------------------------------------------------------------- weather: observed Central Park daily + archived 48 h forecasts
with Timer("weather"):
    w = pd.read_csv(RAW / "noaa_daily_centralpark.csv")
    w = w.rename(columns={"DATE": "day"})
    w["day"] = pd.to_datetime(w.day)
    w = w.sort_values("day").drop_duplicates("day")
    for k in ("TMIN", "TMAX", "SNOW", "AWND"):
        w[k] = pd.to_numeric(w[k], errors="coerce")
    w["tmin_lag1"] = w.TMIN.shift(1)
    w["tmin_next1"] = w.TMIN.shift(-1)
    w["tmin_48h"] = w[["TMIN", "tmin_next1"]].min(axis=1)       # coldest low across day d and d+1
    w["band"] = tmin_band(w.TMIN)
    w["frigid25"] = w.TMIN < 25
    w["season"] = season(w.day)
    w["heat_season"] = in_heat_season(w.day)
    w["holiday_gap"] = w.day.isin(HOLIDAY_GAPS)
    w["wday"] = w.day.dt.day_name().str[:3]
    daily = hc.groupby("day").agg(complaints=("complaint_id", "size"), buildings=("building_id", "nunique")).reset_index()
    w = w.merge(daily, on="day", how="left")
    w[["complaints", "buildings"]] = w[["complaints", "buildings"]].fillna(0).astype(int)
    team_days = pd.read_csv(RAW / "days.csv", parse_dates=["day"])
    chk = w.merge(team_days[["day", "TMIN"]].rename(columns={"TMIN": "TMIN_team"}), on="day")
    N["weather_days"] = len(w)
    N["weather_day_max"] = w.day.max()
    N["weather_tmin_matches_team_days_csv"] = int((chk.TMIN == chk.TMIN_team).sum())
    N["weather_tmin_compared_days"] = len(chk)
    N["weather_tmin_missing"] = int(w.TMIN.isna().sum())
    w.to_csv(WORK / "days_weather.csv", index=False)

    f = pd.read_csv(RAW / "weather_archived_forecast_features_2024_onward.csv")
    f["prediction_time_utc"] = pd.to_datetime(f.prediction_time_utc, utc=True)
    f["prediction_day"] = f.prediction_time_utc.dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    f["fc_tmin_next48h_f"] = f.forecast_temp_min_next_48h_c * 9 / 5 + 32
    city = f.groupby("prediction_day").agg(fc_tmin_next48h_f=("fc_tmin_next48h_f", "min"),
                                           fc_freezing_hours_next48h=("forecast_freezing_hours_next_48h", "max"),
                                           fc_heating_degree_hours_next48h=("forecast_heating_degree_hours_next_48h", "max"),
                                           fc_snow_cm_next48h=("forecast_snowfall_sum_next_48h_cm", "max"),
                                           fc_lead_hours=("forecast_lead_hours_at_prediction", "first")).reset_index()
    bx = f[f.borough.eq("Bronx")][["prediction_day", "fc_tmin_next48h_f"]].rename(columns={"fc_tmin_next48h_f": "fc_tmin_next48h_f_bronx"})
    city = city.merge(bx, on="prediction_day", how="left")
    # the forecast issued at 12:00 UTC on day D (07:00 or 08:00 in New York) covers all of local day D+1
    city["target_day"] = city.prediction_day + pd.Timedelta(days=1)
    city["fc_band"] = tmin_band(city.fc_tmin_next48h_f)
    city.to_csv(WORK / "forecast_daily.csv", index=False)
    N["forecast_days"] = len(city)
    N["forecast_day_min"], N["forecast_day_max"] = city.prediction_day.min(), city.prediction_day.max()
    agree = city.merge(w[["day", "TMIN", "band"]], left_on="target_day", right_on="day")
    agree = agree[agree.day.dt.month.isin([10, 11, 12, 1, 2, 3, 4, 5])]
    N["forecast_vs_observed_band_agreement"] = float((agree.fc_band == agree.band).mean())
    N["forecast_vs_observed_subfreezing_agreement"] = float(((agree.fc_tmin_next48h_f < 32) == (agree.TMIN < 32)).mean())
    N["forecast_vs_observed_days_compared"] = len(agree)
    N["forecast_minus_observed_tmin_mean_f"] = float((agree.fc_tmin_next48h_f - agree.TMIN).mean())
print(f"  weather days {N['weather_days']:,} through {N['weather_day_max'].date()}; TMIN equals the team days.csv on "
      f"{N['weather_tmin_matches_team_days_csv']:,}/{N['weather_tmin_compared_days']:,} days; archived forecasts cover "
      f"{N['forecast_days']:,} days, next-48h-minimum band agrees with observed TMIN on {N['forecast_vs_observed_band_agreement']:.0%} of heat-season days")

save_numbers("01_clean", N)
print("STEP 1 complete")
