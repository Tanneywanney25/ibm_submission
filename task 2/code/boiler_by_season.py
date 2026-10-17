"""Leak-free replacement for data/second_tier/bbl_boiler.csv: one row per (bbl, season) with
boiler_defects and fuel_oil computed only from DOB / DEP records dated before October 1 of
that season (the V1a variant of model/08_stream2_ablation.py). Same two column names, so
add_second_tier() can merge it on (bbl, season) instead of on bbl alone."""
import pandas as pd
from pathlib import Path
DATA = Path("data"); ST = DATA / "second_tier"
reg = pd.read_csv(DATA / "hpd_registrations.csv", low_memory=False)
reg["bbl"] = (reg.boroid * 1_000_000_000 + reg.block * 10_000 + reg.lot).astype("int64")
bin2bbl = reg.dropna(subset=["bin"]).astype({"bin": "int64"}).drop_duplicates("bin").set_index("bin")["bbl"]
bi = pd.read_csv(ST / "boiler_inspections.csv", dtype=str, keep_default_na=False)
bi["bbl"] = pd.to_numeric(bi.bin_number, errors="coerce").astype("Int64").map(bin2bbl)
bi = bi.dropna(subset=["bbl"]); bi["bbl"] = bi.bbl.astype("int64")
bi["date"] = pd.to_datetime(bi.inspection_date, format="%m/%d/%Y %H:%M:%S", errors="coerce")
bi["defect"] = bi.defects_exist.str.upper().eq("YES")
bf = pd.read_csv(ST / "boiler_fuel.csv", dtype=str, keep_default_na=False)
bf["bbl"] = pd.to_numeric(bf.bin, errors="coerce").astype("Int64").map(bin2bbl)
bf = bf.dropna(subset=["bbl"]); bf["bbl"] = bf.bbl.astype("int64")
bf["date"] = pd.to_datetime(bf.issuedate, errors="coerce")
bf["oil"] = bf.primaryfuel.str.upper().str.contains("FUEL|OIL")
out = []
for S in range(2018, 2027):
    cut = pd.Timestamp(S, 10, 1)
    d = bi[bi.date < cut].groupby("bbl").defect.sum().rename("boiler_defects")
    f = bf[bf.date < cut].groupby("bbl").oil.max().rename("fuel_oil")
    t = pd.concat([d, f], axis=1).fillna(0).astype(int).reset_index().assign(season=S)
    out.append(t)
res = pd.concat(out, ignore_index=True)[["bbl", "season", "boiler_defects", "fuel_oil"]]
res.to_csv(ST / "bbl_boiler_by_season.csv", index=False)
print(len(res), "rows;", res.groupby("season").apply(lambda t: int((t.boiler_defects > 0).sum())).to_dict())
