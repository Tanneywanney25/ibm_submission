"""Second-tier data prep: landlord portfolios + boiler facts, keyed by bbl.

Inputs (data/second_tier/, pulled from NYC Open Data):
  hpd_contacts.csv       feu5-w2e2  registration contacts (owners)
  boiler_inspections.csv 52dp-yji6  DOB boiler inspection reports
  boiler_fuel.csv        f4rp-2kvy  DOB boiler registrations (fuel type)
Plus data/hpd_registrations.csv to map registrationid/bin -> bbl.

Run from the repo root:  python model/00_second_tier.py
Writes: data/second_tier/bbl_landlord.csv, data/second_tier/bbl_boiler.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path("data")
ST = DATA / "second_tier"

reg = pd.read_csv(DATA / "hpd_registrations.csv")
reg["bbl"] = (reg.boroid * 1_000_000_000 + reg.block * 10_000 + reg.lot).astype("int64")

# ---- landlord: one owner string per registration, preferring corporate owner
c = pd.read_csv(ST / "hpd_contacts.csv")
pref = {"CorporateOwner": 0, "IndividualOwner": 1, "HeadOfficer": 2}
c["rank"] = c.type.map(pref)
c["landlord"] = (c.corporationname.fillna("")
                 .str.cat(c.firstname.fillna(""), sep=" ")
                 .str.cat(c.lastname.fillna(""), sep=" ")
                 .str.upper().str.replace(r"[^A-Z0-9 ]", "", regex=True)
                 .str.replace(r"\s+", " ", regex=True).str.strip())
c = c[c.landlord.str.len() >= 3].sort_values("rank").drop_duplicates("registrationid")

lord = (reg[["bbl", "registrationid"]]
        .merge(c[["registrationid", "landlord"]], on="registrationid", how="inner")
        .drop_duplicates("bbl"))
lord.to_csv(ST / "bbl_landlord.csv", index=False)
sizes = lord.groupby("landlord").size()
print(f"landlord map: {len(lord):,} bbls, {sizes.size:,} landlords, "
      f"{(sizes >= 2).sum():,} own 2+ buildings (largest {sizes.max()})")

# ---- boiler: defects + fuel, bin -> bbl through registrations
bin2bbl = reg.dropna(subset=["bin"]).astype({"bin": "int64"}) \
    .drop_duplicates("bin").set_index("bin")["bbl"]

bi = pd.read_csv(ST / "boiler_inspections.csv")
bi["bbl"] = bi.bin_number.map(bin2bbl)
bi = bi.dropna(subset=["bbl"])
bo = bi.groupby("bbl").agg(boiler_reports=("defects_exist", "size"),
                           boiler_defects=("defects_exist", lambda s: (s == "Yes").sum()))

bf = pd.read_csv(ST / "boiler_fuel.csv")
bf["bbl"] = bf.bin.map(bin2bbl)
bf = bf.dropna(subset=["bbl"])
bf["oil"] = bf.primaryfuel.fillna("").str.upper().str.contains("FUEL|OIL")
fuel = bf.groupby("bbl").agg(fuel_oil=("oil", "max"))

boiler = bo.join(fuel, how="outer").fillna(0).astype(int).reset_index()
boiler["bbl"] = boiler.bbl.astype("int64")
boiler.to_csv(ST / "bbl_boiler.csv", index=False)
print(f"boiler table: {len(boiler):,} bbls | with defects {int((boiler.boiler_defects > 0).sum()):,} "
      f"| oil-fired {int(boiler.fuel_oil.sum()):,}")
