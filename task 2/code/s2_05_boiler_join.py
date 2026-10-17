"""STEP 5 / Deliverable 4: second-tier boiler and fuel join on BIN.

Sources pulled on the LinuxONE server with curl (pull_open_data.sh, $limit=50000 pages):
  52dp-yji6  DOB NOW boiler inspection reports (892,914 rows): bin_number, inspection_date,
             defects_exist, report_status, boiler_id, boiler_make, pressure_type, late-filing fees
  f4rp-2kvy  DEP boiler fuel registrations / certificates to operate (91,370 rows): bin,
             primaryfuel, secondaryfuel, make, model, issuedate, expirationdate, status
Both join to the building universe on bin (int64). Every training feature is computed
strictly from records dated before 2025-10-01; the 2025-26 columns are evaluation only.

Outputs (out/): bin_boiler_features.csv, boiler_lift_summary.csv
"""
import numpy as np
import pandas as pd

from s2_common import RAW, WORK, OUT, TEST_SEASON, FEATURE_CUTOFF, to_int64, save_numbers, Timer

N = {}

with Timer("load"):
    u = pd.read_csv(WORK / "buildings_universe.csv")
    cl = pd.read_csv(WORK / "clusters.csv", parse_dates=["start_date", "vdate"])
    fo = pd.read_csv(OUT / "forecast_only_buildings.csv",
                     usecols=["building_id", "group", "forecast_only_strict", "forecast_only_broad", "chronic", "c_last1",
                              "c_train_total", "test_fail48", "test_complaints", "snap_fail48", "test_fail48_verified7"])
    dob = pd.read_csv(RAW / "dob_boiler_52dp-yji6.csv", dtype=str, keep_default_na=False)
    dep = pd.read_csv(RAW / "dep_boiler_fuel_f4rp-2kvy.csv", dtype=str, keep_default_na=False)

# ---------------------------------------------------------------- DOB boiler inspection reports
with Timer("DOB boiler features (pre-cutoff)"):
    dob["bin"] = to_int64(dob.bin_number)
    dob["inspection_date"] = pd.to_datetime(dob.inspection_date, format="%m/%d/%Y %H:%M:%S", errors="coerce")
    dob["defect"] = dob.defects_exist.str.strip().str.upper().eq("YES")
    dob["late_filing"] = (pd.to_numeric(dob.lff_45_days, errors="coerce").fillna(0) > 0) | (pd.to_numeric(dob.lff_180_days, errors="coerce").fillna(0) > 0)
    dob["accepted"] = dob.report_status.str.upper().str.startswith("ACCEPT")
    N["dob_rows"] = len(dob)
    N["dob_rows_with_bin"] = int(dob.bin.notna().sum())
    N["dob_date_min"], N["dob_date_max"] = dob.inspection_date.min(), dob.inspection_date.max()
    N["dob_defect_share_all"] = float(dob.defect.mean())
    N["dob_distinct_bins"] = int(dob.bin.nunique())
    pre = dob[dob.bin.notna() & (dob.inspection_date < FEATURE_CUTOFF)].copy()
    g = pre.groupby("bin")
    D = pd.DataFrame({
        "dob_reports_pre": g.size(),
        "dob_defect_reports_pre": g.defect.sum(),
        "dob_boilers_distinct": g.boiler_id.nunique(),
        "dob_late_filings_pre": g.late_filing.sum(),
        "dob_first_inspection": g.inspection_date.min(),
        "dob_last_inspection": g.inspection_date.max(),
        "dob_pressure_type": g.pressure_type.agg(lambda s: s.mode().iloc[0] if len(s.mode()) else ""),
        "dob_boiler_make": g.boiler_make.agg(lambda s: s.str.upper().str.strip().mode().iloc[0] if len(s.mode()) else ""),
    })
    last = pre.sort_values("inspection_date").groupby("bin").tail(1).set_index("bin")
    D["dob_last_inspection_defect"] = last.defect
    D["dob_defect_share_pre"] = D.dob_defect_reports_pre / D.dob_reports_pre
    D["dob_days_since_last_inspection_at_cutoff"] = (FEATURE_CUTOFF - D.dob_last_inspection).dt.days
    recent = pre[pre.inspection_date >= FEATURE_CUTOFF - pd.Timedelta(days=3 * 365)].groupby("bin")
    D["dob_reports_last3y"] = recent.size()
    D["dob_defect_reports_last3y"] = recent.defect.sum()
    D[["dob_reports_last3y", "dob_defect_reports_last3y"]] = D[["dob_reports_last3y", "dob_defect_reports_last3y"]].fillna(0).astype(int)
    D["dob_prior_defect"] = D.dob_defect_reports_pre >= 1
    D["dob_defect_category"] = pd.cut(D.dob_defect_reports_pre, [-1, 0, 1, 3, 10 ** 6], labels=["0 defects", "1 defect", "2-3 defects", "4+ defects"])
    D = D.reset_index()
    N["dob_bins_pre_cutoff"] = len(D)

# ---------------------------------------------------------------- DEP boiler fuel registrations
with Timer("DEP boiler fuel features (pre-cutoff)"):
    dep["bin"] = to_int64(dep.bin)
    dep["issuedate"] = pd.to_datetime(dep.issuedate, errors="coerce")
    dep["expirationdate"] = pd.to_datetime(dep.expirationdate, errors="coerce")
    dep["primaryfuel"] = dep.primaryfuel.str.upper().str.strip().replace("", "UNKNOWN")
    dep["secondaryfuel"] = dep.secondaryfuel.str.upper().str.strip().replace("", "NONE")
    N["dep_rows"] = len(dep)
    N["dep_rows_with_bin"] = int(dep.bin.notna().sum())
    N["dep_distinct_bins"] = int(dep.bin.nunique())
    N["dep_fuel_mix_rows"] = dep.primaryfuel.value_counts().head(8).to_dict()
    dpre = dep[dep.bin.notna() & (dep.issuedate < FEATURE_CUTOFF)].copy()
    latest = dpre.sort_values("issuedate").groupby("bin").tail(1).set_index("bin")
    g = dpre.groupby("bin")
    E = pd.DataFrame({
        "dep_records_pre": g.size(),
        "dep_first_issue_year": g.issuedate.min().dt.year,
        "dep_latest_issue_date": g.issuedate.max(),
        "dep_latest_expiration": g.expirationdate.max(),
        "dep_boilers_quantity_max": pd.to_numeric(g.quantity.max(), errors="coerce"),
    })
    E["dep_primary_fuel"] = latest.primaryfuel
    E["dep_secondary_fuel"] = latest.secondaryfuel
    E["dep_boiler_make"] = latest.make.str.upper().str.strip()
    E["dep_latest_status"] = latest.status.str.upper().str.strip()
    E["dep_latest_requesttype"] = latest.requesttype.str.upper().str.strip()
    E["dep_fuel_grade"] = np.select(
        [E.dep_primary_fuel.str.contains("NATURAL", na=False), E.dep_primary_fuel.str.contains("NO2", na=False),
         E.dep_primary_fuel.str.contains("NO4", na=False), E.dep_primary_fuel.str.contains("NO6", na=False)],
        ["natural gas", "No. 2 oil", "No. 4 oil", "No. 6 oil"], "other/unknown")
    E["dep_registration_age_years_at_cutoff"] = FEATURE_CUTOFF.year - E.dep_first_issue_year
    E["dep_certificate_expired_at_cutoff"] = E.dep_latest_expiration < FEATURE_CUTOFF
    E = E.reset_index()
    N["dep_bins_pre_cutoff"] = len(E)

# ---------------------------------------------------------------- join to the building universe on bin
with Timer("join on bin"):
    X = u[["building_id", "bbl", "bin", "borough", "cd", "unitsres", "yearbuilt", "res3plus", "size_bucket", "era", "altered"]].copy()
    X = X.merge(D, on="bin", how="left").merge(E, on="bin", how="left")
    X["has_dob_boiler_record"] = X.dob_reports_pre.notna()
    X["has_dep_fuel_record"] = X.dep_records_pre.notna()
    X["dob_prior_defect"] = X.dob_prior_defect.fillna(False).astype(bool)
    for c in ("dob_reports_pre", "dob_defect_reports_pre", "dob_boilers_distinct", "dob_late_filings_pre", "dob_reports_last3y", "dob_defect_reports_last3y", "dep_records_pre"):
        X[c] = X[c].fillna(0).astype(int)
    X["dob_defect_category"] = X.dob_defect_category.cat.add_categories(["no DOB record"]).fillna("no DOB record")
    X["dob_inspection_recency"] = pd.cut(X.dob_days_since_last_inspection_at_cutoff, [-1, 365, 730, 1095, 10 ** 6],
                                         labels=["< 1 year", "1-2 years", "2-3 years", "3+ years"]).cat.add_categories(["no DOB record"]).fillna("no DOB record")
    X = X.merge(fo, on="building_id", how="left")
    X["test_failed48"] = X.test_fail48.fillna(0) >= 1
    X["test_verified"] = X.test_fail48_verified7.fillna(0) >= 1
    X["snap_failed48"] = X.snap_fail48.fillna(0) >= 1
    X["group"] = X.group.fillna("no_training_complaints")
    N["universe_buildings"] = len(X)
    N["universe_with_bin"] = int(X.bin.notna().sum())
    N["coverage_dob_all"] = float(X.has_dob_boiler_record.mean())
    N["coverage_dep_all"] = float(X.has_dep_fuel_record.mean())
    N["coverage_dob_res3plus"] = float(X.loc[X.res3plus, "has_dob_boiler_record"].mean())
    N["coverage_dep_res3plus"] = float(X.loc[X.res3plus, "has_dep_fuel_record"].mean())
    N["coverage_dob_1_2_units"] = float(X.loc[X.unitsres <= 2, "has_dob_boiler_record"].mean())
    N["coverage_dob_by_size"] = X.groupby("size_bucket", observed=True).has_dob_boiler_record.mean().to_dict()
    N["prior_defect_buildings"] = int(X.dob_prior_defect.sum())
    N["prior_defect_share_among_dob"] = float(X.loc[X.has_dob_boiler_record, "dob_prior_defect"].mean())
print(f"  universe {len(X):,} buildings; DOB boiler record on bin for {N['coverage_dob_all']:.1%} (3+ units: {N['coverage_dob_res3plus']:.1%}); "
      f"DEP fuel record for {N['coverage_dep_all']:.1%} (3+ units: {N['coverage_dep_res3plus']:.1%})")

# ---------------------------------------------------------------- lift tables
with Timer("lift"):
    t25 = cl[(cl.season == TEST_SEASON) & cl.heat_season & cl.label_2plus][["building_id", "confirmed7"]]
    rows = []

    def lift(df, by, label, scope_label):
        g = df.groupby(by, observed=True)
        out = pd.DataFrame({"buildings": g.size(), "units": g.unitsres.sum(),
                            "share_failed48_2025_26": g.test_failed48.mean(), "share_verified_2025_26": g.test_verified.mean(),
                            "share_failed48_feb7_9": g.snap_failed48.mean(), "mean_c_last1": g.c_last1.mean(),
                            "share_forecast_only_strict": g.forecast_only_strict.mean(), "share_chronic": g.chronic.mean()}).reset_index()
        out = out.rename(columns={by: "level"}); out["level"] = out.level.astype(str)
        cc = t25[["building_id", "confirmed7"]].merge(df[["building_id", by]], on="building_id", how="inner").groupby(by, observed=True).confirmed7.agg(["size", "mean"]).reset_index().rename(
            columns={by: "level", "size": "clusters_2plus_2025_26", "mean": "rate_7d_confirmation_2025_26"})
        cc["level"] = cc.level.astype(str)
        out = out.merge(cc, on="level", how="left")
        out.insert(0, "dimension", label); out.insert(0, "scope", scope_label)
        return out

    for scope_label, df in [("all universe buildings", X), ("3+ unit buildings with a DOB boiler record", X[X.res3plus & X.has_dob_boiler_record]),
                            ("all buildings with a DOB boiler record", X[X.has_dob_boiler_record])]:
        dd = df.copy()
        dd["prior_defect_flag"] = np.select([~dd.has_dob_boiler_record, dd.dob_prior_defect], ["no DOB record", "prior defect logged"], "DOB record, no defect")
        rows.append(lift(dd, "prior_defect_flag", "prior boiler defect (pre Oct 1, 2025)", scope_label))
        rows.append(lift(dd, "dob_defect_category", "count of prior defect reports", scope_label))
        rows.append(lift(dd, "dob_inspection_recency", "time since last DOB boiler inspection at cutoff", scope_label))
        dd["late_filing_flag"] = np.select([~dd.has_dob_boiler_record, dd.dob_late_filings_pre >= 1], ["no DOB record", "late filing fee logged"], "filed on time")
        rows.append(lift(dd, "late_filing_flag", "late boiler-inspection filings", scope_label))
        dd["fuel"] = dd.dep_fuel_grade.fillna("no DEP record")
        rows.append(lift(dd, "fuel", "DEP primary fuel grade (latest pre-cutoff registration)", scope_label))
        dd["reg_age"] = pd.cut(dd.dep_registration_age_years_at_cutoff, [-1, 5, 10, 20, 30, 200],
                               labels=["0-5 y", "6-10 y", "11-20 y", "21-30 y", "30+ y"]).cat.add_categories(["no DEP record"]).fillna("no DEP record")
        rows.append(lift(dd, "reg_age", "years since first DEP boiler registration (boiler-age proxy)", scope_label))
        rows.append(lift(dd, "group", "Forecast-Only / Chronic group", scope_label))
    L = pd.concat(rows, ignore_index=True)
    L.to_csv(OUT / "boiler_lift_summary.csv", index=False)

    def pick(scope_label, dim, lvl, col):
        r = L[(L.scope == scope_label) & (L.dimension == dim) & (L.level == lvl)]
        return float(r[col].iloc[0]) if len(r) and pd.notna(r[col].iloc[0]) else float("nan")

    for sc_ in ("all universe buildings", "3+ unit buildings with a DOB boiler record", "all buildings with a DOB boiler record"):
        k = sc_.split()[0] + ("_dob" if "DOB" in sc_ else "")
        for lvl in ("prior defect logged", "DOB record, no defect", "no DOB record"):
            kk = lvl.replace(" ", "_").replace(",", "")
            N[f"fail48_rate_{kk}_{k}"] = pick(sc_, "prior boiler defect (pre Oct 1, 2025)", lvl, "share_failed48_2025_26")
            N[f"verified_rate_{kk}_{k}"] = pick(sc_, "prior boiler defect (pre Oct 1, 2025)", lvl, "share_verified_2025_26")
            N[f"confirm7_rate_{kk}_{k}"] = pick(sc_, "prior boiler defect (pre Oct 1, 2025)", lvl, "rate_7d_confirmation_2025_26")
            N[f"snap_fail_rate_{kk}_{k}"] = pick(sc_, "prior boiler defect (pre Oct 1, 2025)", lvl, "share_failed48_feb7_9")
            N[f"buildings_{kk}_{k}"] = pick(sc_, "prior boiler defect (pre Oct 1, 2025)", lvl, "buildings")
    # forecast-only vs chronic: boiler profile
    prof = X.groupby("group").agg(buildings=("building_id", "size"), share_dob_record=("has_dob_boiler_record", "mean"),
                                  share_prior_defect=("dob_prior_defect", "mean"),
                                  share_prior_defect_among_dob=("dob_prior_defect", lambda s: s[X.loc[s.index, "has_dob_boiler_record"]].mean()),
                                  mean_defect_reports=("dob_defect_reports_pre", "mean"),
                                  share_late_filing=("dob_late_filings_pre", lambda s: (s >= 1).mean()),
                                  median_days_since_inspection=("dob_days_since_last_inspection_at_cutoff", "median"),
                                  share_dep_record=("has_dep_fuel_record", "mean"),
                                  mean_registration_age_years=("dep_registration_age_years_at_cutoff", "mean"),
                                  share_oil_fuel=("dep_fuel_grade", lambda s: s.str.contains("oil", na=False).mean()),
                                  share_res3plus=("res3plus", "mean")).reset_index()
    prof3 = X[X.res3plus].groupby("group").agg(buildings_3plus=("building_id", "size"), share_dob_record_3plus=("has_dob_boiler_record", "mean"),
                                               share_prior_defect_among_dob_3plus=("dob_prior_defect", lambda s: s[X.loc[s.index, "has_dob_boiler_record"]].mean()),
                                               mean_registration_age_years_3plus=("dep_registration_age_years_at_cutoff", "mean"),
                                               share_oil_fuel_among_dep_3plus=("dep_fuel_grade", lambda s: s.dropna().str.contains("oil").mean())).reset_index()
    prof = prof.merge(prof3, on="group", how="left")
    prof.to_csv(OUT / "boiler_profile_by_group.csv", index=False)
    N["profile_by_group"] = prof.to_dict(orient="records")
    N["fuel_lift_res3plus_dob"] = L[(L.scope == "3+ unit buildings with a DOB boiler record") & (L.dimension.str.startswith("DEP primary fuel"))][
        ["level", "buildings", "share_failed48_2025_26", "rate_7d_confirmation_2025_26"]].to_dict(orient="records")
    N["recency_lift_res3plus_dob"] = L[(L.scope == "3+ unit buildings with a DOB boiler record") & (L.dimension.str.startswith("time since"))][
        ["level", "buildings", "share_failed48_2025_26", "rate_7d_confirmation_2025_26"]].to_dict(orient="records")
print(L[(L.scope == "3+ unit buildings with a DOB boiler record") & (L.dimension == "prior boiler defect (pre Oct 1, 2025)")]
      [["level", "buildings", "share_failed48_2025_26", "share_verified_2025_26", "rate_7d_confirmation_2025_26", "share_failed48_feb7_9"]].to_string(index=False))
print(prof[["group", "buildings", "share_dob_record", "share_prior_defect_among_dob", "mean_registration_age_years", "share_oil_fuel"]].to_string(index=False))

# ---------------------------------------------------------------- handoff for Stream 5
with Timer("write bin_boiler_features.csv"):
    feat = ["bin", "building_id", "bbl", "res3plus", "has_dob_boiler_record", "dob_reports_pre", "dob_defect_reports_pre", "dob_defect_share_pre",
            "dob_prior_defect", "dob_last_inspection_defect", "dob_boilers_distinct", "dob_late_filings_pre", "dob_first_inspection",
            "dob_last_inspection", "dob_days_since_last_inspection_at_cutoff", "dob_reports_last3y", "dob_defect_reports_last3y",
            "dob_pressure_type", "dob_boiler_make", "has_dep_fuel_record", "dep_records_pre", "dep_first_issue_year",
            "dep_registration_age_years_at_cutoff", "dep_primary_fuel", "dep_secondary_fuel", "dep_fuel_grade", "dep_boiler_make",
            "dep_latest_status", "dep_latest_expiration", "dep_certificate_expired_at_cutoff", "dep_boilers_quantity_max"]
    evalc = ["group", "test_failed48", "test_verified", "snap_failed48"]
    X[feat + evalc].to_csv(OUT / "bin_boiler_features.csv", index=False)
    N["output_rows"] = len(X)
    N["feature_columns_leak_free"] = feat
    N["evaluation_columns_2025_26"] = evalc

save_numbers("05_boiler_join", N)
print("STEP 5 complete")
