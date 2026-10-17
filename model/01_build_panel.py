"""Phases 0-3 of docs/model-plan.md: load -> label -> panel -> features.

Runs the same on the laptop and LinuxONE (pandas/numpy only).
Run from the repo root:  python model/01_build_panel.py
Writes: model/out/panel.csv, model/out/building_day_counts.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path

from common import NEVER, band_prep, band_rates

DATA = Path("data")
OUT = Path("model/out")
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(42)


def season(d):
    # Oct-May season named by its starting year: Dec 2022 and Feb 2023 -> 2022
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)


# ---------------------------------------------------------------- Phase 0: load
print("Phase 0: load")
usecols = ["received_date", "complaint_id", "bbl", "problem_code", "minor_category"]
heat = pd.concat(
    pd.read_csv(DATA / "hpd_heat_complaints.csv", usecols=usecols,
                chunksize=500_000, low_memory=False),
    ignore_index=True)
heat = heat[heat.problem_code.isin(["NO HEAT", "NO HEAT AND NO HOT WATER"])]
heat = heat.dropna(subset=["bbl"])
heat["bbl"] = heat["bbl"].astype(float).astype("int64")   # floats kill joins
heat["day"] = pd.to_datetime(heat["received_date"]).dt.normalize()

days = pd.read_csv(DATA / "days.csv", parse_dates=["day"])
buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")

viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False)
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])]  # heat only
viol = viol.dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])
viol = viol[viol.inspectiondate >= "2010-01-01"]          # 1968 garbage out

heat = heat[heat.bbl.isin(buildings.bbl)]
viol = viol[viol.bbl.isin(buildings.bbl)]
print(f"  heat rows {len(heat):,} | buildings {len(buildings):,} | heat violations {len(viol):,}")

# ---------------------------------------------------------------- Phase 1: label
print("Phase 1: label")
bd = (heat.groupby(["bbl", "day"])["complaint_id"]
          .nunique().rename("n").reset_index())
# ENTIRE BUILDING complaints = whole-building outages (vs one cold apartment)
bw = (heat[heat.minor_category == "ENTIRE BUILDING"]
      .groupby(["bbl", "day"])["complaint_id"].nunique().rename("n").reset_index())

nxt = bd.copy()
nxt["day"] -= pd.Timedelta(days=1)
nxt = nxt.rename(columns={"n": "n_next"})
lab = bd.merge(nxt, on=["bbl", "day"], how="outer").fillna(0)
lab["failed48"] = (lab.n + lab.n_next) >= 2
lab["season"] = season(lab.day)

pos = lab[lab.failed48 & lab.season.between(2018, 2025)].copy()
print(f"  building-days {len(lab):,} | positives (2018-25 seasons) {len(pos):,}")
assert len(pos) > 50_000, "positive rate too low - fall back to n >= 1 (decide now)"

# verified tier: heat violation within 7 days of the label day (report-only, never a feature)
v = (viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "vdate"})
     .sort_values("vdate"))
pos = pos.sort_values("day")
pos = pd.merge_asof(pos, v, left_on="day", right_on="vdate", by="bbl",
                    direction="forward", tolerance=pd.Timedelta(days=7))
pos["verified"] = pos.vdate.notna()
print(f"  verified within 7d: {pos.verified.mean():.1%}")

# ---------------------------------------------------------------- Phase 2: panel
print("Phase 2: panel")
hd = days.loc[days.heat_season & days.day.dt.year.ge(2018), "day"]
neg = pd.DataFrame({
    "bbl": rng.choice(buildings.bbl.to_numpy(), size=len(pos) * 2),
    "day": rng.choice(hd.to_numpy(), size=len(pos) * 2),
}).drop_duplicates()
neg = neg.merge(pos[["bbl", "day"]], on=["bbl", "day"], how="left", indicator=True)
neg = neg[neg._merge == "left_only"].drop(columns="_merge")
neg["failed48"] = False

panel = pd.concat(
    [pos[["bbl", "day", "failed48", "verified"]],
     neg.assign(verified=False)],
    ignore_index=True)
panel["season"] = season(panel.day)
panel = panel[panel.season.between(2018, 2025)]
print(f"  panel rows {len(panel):,} ({panel.failed48.mean():.1%} positive - sampled, not a real-world rate)")

# ---------------------------------------------------------------- Phase 3: features
print("Phase 3: features")

# -- history from PRIOR seasons only (the one rule)
heat["season"] = season(heat.day)
sc = (heat.groupby(["bbl", "season"])["complaint_id"]
          .nunique().rename("c").reset_index())
sc1 = sc.assign(season=sc.season + 1).rename(columns={"c": "c_last1"})
sc2 = sc.assign(season=sc.season + 2).rename(columns={"c": "c_last2_part"})
panel = panel.merge(sc1, on=["bbl", "season"], how="left")
panel = panel.merge(sc2, on=["bbl", "season"], how="left")
panel["c_last1"] = panel.c_last1.fillna(0)
panel["c_last2"] = panel.c_last1 + panel.c_last2_part.fillna(0)  # total of two prior seasons

viol["season"] = season(viol.inspectiondate)
sv = viol.groupby(["bbl", "season"]).size().rename("v").reset_index()
sv1 = sv.assign(season=sv.season + 1).rename(columns={"v": "v_last1"})
sv2 = sv.assign(season=sv.season + 2).rename(columns={"v": "v_last2_part"})
panel = panel.merge(sv1, on=["bbl", "season"], how="left")
panel = panel.merge(sv2, on=["bbl", "season"], how="left")
panel["v_last1"] = panel.v_last1.fillna(0)
panel["v_last2"] = panel.v_last1 + panel.v_last2_part.fillna(0)
panel["chronic"] = ((panel.c_last1 >= 5) & (panel.c_last2_part.fillna(0) >= 5)).astype(int)
panel = panel.drop(columns=["c_last2_part", "v_last2_part"])

# whole-building outages last season (stronger signal than apartment-only)
bw["season"] = season(bw.day)
sb = bw.groupby(["bbl", "season"])["n"].sum().rename("b").reset_index()
panel = panel.merge(sb.assign(season=sb.season + 1).rename(columns={"b": "bw_last1"}),
                    on=["bbl", "season"], how="left")
panel["bw_last1"] = panel.bw_last1.fillna(0)

# -- reaction rates by weather band: share of the prior two seasons' frigid /
#    freezing / cold days on which this building complained (stream 1's bands)
num, den = band_prep(bd, days)
rates = pd.concat([band_rates(num, den, S, buildings.bbl).assign(season=S)
                   for S in range(2018, 2026)], ignore_index=True)
panel = panel.merge(rates, on=["bbl", "season"], how="left")

# -- trailing in-season activity + days-since, strictly BEFORE the row's day
#    (windows end at d-1, so no leakage)
bdc = bd.sort_values(["bbl", "day"]).copy()
bdc["csum"] = bdc.groupby("bbl")["n"].cumsum()
bdc["lastd"] = bdc["day"]
bdc = bdc.sort_values("day")          # merge_asof needs the 'on' key globally sorted
vdc = (viol[["bbl", "inspectiondate"]].rename(columns={"inspectiondate": "day"})
       .sort_values("day"))
vdc["lastd"] = vdc["day"]


def asof_before(keys, offset_days, right, cols):
    """per-(bbl) state as of day + offset_days (backward asof), row-aligned to keys."""
    t = keys[["bbl", "day"]].copy()
    t["day"] = t.day + pd.Timedelta(days=offset_days)
    t["_i"] = np.arange(len(t))
    t = t.sort_values("day")
    r = pd.merge_asof(t, right, on="day", by="bbl", direction="backward")
    return r.sort_values("_i")[cols].reset_index(drop=True)


a = asof_before(panel, -1, bdc[["bbl", "day", "csum", "lastd"]], ["csum", "lastd"])
at_d1 = a.csum.fillna(0).to_numpy()
panel["days_since_c"] = ((panel.day.to_numpy() - a.lastd.to_numpy())
                         / np.timedelta64(1, "D"))
for w in (7, 14, 30):
    panel[f"c_prev{w}"] = at_d1 - asof_before(
        panel, -(w + 1), bdc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy()
av = asof_before(panel, -1, vdc[["bbl", "day", "lastd"]], ["lastd"])
panel["days_since_v"] = ((panel.day.to_numpy() - av.lastd.to_numpy())
                         / np.timedelta64(1, "D"))
bwc = bw.sort_values(["bbl", "day"]).copy()
bwc["csum"] = bwc.groupby("bbl")["n"].cumsum()
bwc = bwc.sort_values("day")
panel["bw_prev14"] = (
    asof_before(panel, -1, bwc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy()
    - asof_before(panel, -15, bwc[["bbl", "day", "csum"]], ["csum"]).csum.fillna(0).to_numpy())
for c in ("rate_frigid2", "rate_freezing2", "rate_cold2"):
    panel[c] = panel[c].fillna(0.0)
for c in ("days_since_c", "days_since_v"):
    panel[c] = panel[c].fillna(NEVER)

# -- the inspectable universe: keep only buildings with ANY history before the row's
#    day (team decision; matches the deployment universe in 03/05/06)
hist = (panel.days_since_c < NEVER) | (panel.days_since_v < NEVER)
print(f"  dropping {(~hist).sum():,} no-history rows "
      f"(incl. {(~hist & panel.failed48).sum():,} positives invisible to any ranker)")
panel = panel[hist]

# -- building features (NOT buildings.csv's complaints/violations totals: those
#    span all seasons including the row's own and the test season -> leakage)
bf = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                "numfloors", "bldgarea", "cd"]].copy()
bf["yearbuilt"] = bf.yearbuilt.replace(0, np.nan)
bf["altered"] = (bf.yearalter1.fillna(0) > 0).astype(int)
bf = bf.drop(columns="yearalter1")
panel = panel.merge(bf, on="bbl", how="left")

# -- weather for the row's day
days = days.sort_values("day")
days["tmin_roll3"] = days.TMIN.rolling(3).min()
days["tmin_drop"] = days.TMIN.diff()
days["wday_num"] = days.day.dt.weekday
wcols = ["day", "TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop",
         "SNOW", "AWND", "wday_num"]
panel = panel.merge(days[wcols], on="day", how="left")

# ---------------------------------------------------------------- checkpoint + write
# leakage sanity: a 2025 row's c_last1 must equal its 2024-season count
chk = panel[panel.season == 2025].merge(
    sc[sc.season == 2024].rename(columns={"c": "c_2024"}), left_on="bbl", right_on="bbl",
    how="left", suffixes=("", "_y"))
assert (chk.c_last1.to_numpy() == chk.c_2024.fillna(0).to_numpy()).all(), "history leak!"

print(panel.groupby("season").agg(rows=("bbl", "size"), pos=("failed48", "sum")))
panel.to_csv(OUT / "panel.csv", index=False)
bd.to_csv(OUT / "building_day_counts.csv", index=False)   # eval + baselines need this
bw.drop(columns="season").to_csv(OUT / "building_day_counts_bw.csv", index=False)
print(f"wrote {OUT/'panel.csv'} ({len(panel):,} rows, {panel.shape[1]} cols)")
