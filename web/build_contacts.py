"""T5a: who is responsible for each building, from public HPD registration records.

Run on the LinuxONE instance, from the repo root, before web/build_assets.py:
    ~/datathon-env/bin/python web/build_contacts.py --pull

--pull re-downloads the managing-agent and corporate-owner rows of HPD registration
contacts (NYC Open Data feu5-w2e2), paged like task 2/code/pull_open_data.sh, into
data/second_tier/hpd_contacts_business.csv. Without it the last pull is reused.
hpd_contacts.csv and bbl_landlord.csv feed the frozen model's portfolio features
(model/00_second_tier.py) and are only read here, never rewritten.

Writes data/second_tier/bbl_contacts.csv, one row per bbl in bbl_landlord.csv:
    bbl, registrationid, agent, agent_co, agent_addr, owner_addr, hpd_id, reg_last
The agent comes from the same registration as the owner name in bbl_landlord.csv,
so both describe one filing. Street addresses appear only for companies: a company
agent's business address, and owner_addr when the owner is a corporation. An agent
or owner filed as a person gets no street address (it may be a home); the agent's
city is kept, and hpd_id links the building's full public record on HPD Online.
Business addresses only: house number, street, city, state and zip; the
businessapartment column is never pulled and a unit typed into the street is cut.
pandas runs here and never on Vercel; app.py reads the CSV in FULL mode only.
"""

import argparse
import io
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
ST = ROOT / "data/second_tier"
RAW = ST / "hpd_contacts_business.csv"
OUT = ST / "bbl_contacts.csv"
API = "https://data.cityofnewyork.us/resource/feu5-w2e2.csv"
COLS = ("registrationcontactid,registrationid,type,corporationname,firstname,lastname,"
        "businesshousenumber,businessstreetname,businesscity,businessstate,businesszip")
PAGE = 50_000


def pull():
    """Agent and CorporateOwner rows of feu5-w2e2, $order=:id so pages are stable."""
    pages, off, t0 = [], 0, time.time()
    while True:
        r = requests.get(API, timeout=600, params={
            "$select": COLS, "$where": "type in('Agent','CorporateOwner')",
            "$order": ":id", "$limit": PAGE, "$offset": off})
        r.raise_for_status()
        page = pd.read_csv(io.StringIO(r.text), dtype=str)
        pages.append(page)
        print(f"  feu5-w2e2 offset={off:,} rows={len(page):,}", flush=True)
        if len(page) < PAGE:
            break
        off += PAGE
    raw = pd.concat(pages, ignore_index=True)
    assert "businessapartment" not in raw.columns
    raw.to_csv(RAW, index=False)
    print(f"pulled {len(raw):,} contact rows in {time.time() - t0:.0f} s -> {RAW.name}")
    return raw


def key(df):
    """The owner string exactly as model/00_second_tier.py builds it, to match on."""
    return (df.corporationname.fillna("")
            .str.cat(df.firstname.fillna(""), sep=" ")
            .str.cat(df.lastname.fillna(""), sep=" ")
            .str.upper().str.replace(r"[^A-Z0-9 ]", "", regex=True)
            .str.replace(r"\s+", " ", regex=True).str.strip())


# a unit typed into the street field ("NASSAU AVENUE #3A2", "MAIN ST APT 4"):
# cut from the designator on, because nothing derived from HPD may carry one
UNIT = re.compile(r"\s*(?:#|\b(?:APT|APARTMENT|UNIT)\b\.?).*$", re.I)


def _title(s):
    """'346 E 59TH ST' -> '346 E 59th St'."""
    return re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(),
                  " ".join(s.split()).title())


def _address(house, street, city, state, zip_):
    """'346 E 59th St, New York, NY 10022', or '' without a house number and street."""
    house = " ".join(str(house or "").split())
    street = UNIT.sub("", " ".join(str(street or "").split()))
    if house and street.upper().startswith(house.upper() + " "):
        street = street[len(house) + 1:]       # house number typed twice
    if not house or not street or house.startswith("#"):
        return ""
    zip5 = (re.match(r"\d{5}", str(zip_ or "")) or [""])[0]
    tail = " ".join(x for x in (str(state or "").strip().upper(), zip5) if x)
    parts = [_title(f"{house} {street}"), _city(city), tail]
    return ", ".join(p for p in parts if p)


def _city(city):
    city = UNIT.sub("", str(city or "").strip())
    if city.upper().replace(".", "").replace(" ", "") in ("NY", "NYC"):
        return "New York"
    city = re.sub(r"[,\s]+N\.?Y\.?$", "", city, flags=re.I)    # 'QUEENS NY', 'NEW YORK,NY'
    return _title(city) if re.search(r"[A-Za-z]", city) else ""


def _locality(city, state):
    """'Brooklyn, NY': all that is shown for an agent who files as a person. A city with
    a digit in it is dropped, since it may be a street typed into the wrong field."""
    city = _city(city)
    return ", ".join(p for p in ("" if re.search(r"\d", city) else city,
                                 str(state or "").strip().upper()) if p)


def address(df):
    cols = ["businesshousenumber", "businessstreetname", "businesscity", "businessstate",
            "businesszip"]
    return pd.Series([_address(*r) for r in df[cols].fillna("").itertuples(index=False)],
                     index=df.index, dtype=str)


def build(raw):
    lord = pd.read_csv(ST / "bbl_landlord.csv")
    lord["bbl"] = lord.bbl.astype("int64")
    lord["registrationid"] = lord.registrationid.astype("int64")
    raw = raw.dropna(subset=["registrationid"]).copy()
    raw["registrationid"] = raw.registrationid.astype("int64")
    raw["registrationcontactid"] = pd.to_numeric(raw.registrationcontactid, errors="coerce")
    raw = raw.sort_values("registrationcontactid")
    raw["name"] = key(raw)
    raw["addr"] = address(raw)

    ag = raw[(raw.type == "Agent") & (raw.name.str.len() >= 3)].copy()
    # a company agent goes by the company and shows its business street address; an
    # agent filed as a person shows name and city only (the street may be a home)
    ag["agent_co"] = ag.corporationname.fillna("").str.strip().str.len().gt(0).astype(int)
    ag["agent"] = ag.corporationname.fillna("").str.strip().where(ag.agent_co == 1, ag.name)
    ag["agent_addr"] = ag.addr.where(ag.agent_co == 1, [
        _locality(c, s) for c, s in zip(ag.businesscity, ag.businessstate)])
    ag = ag.drop_duplicates("registrationid")[["registrationid", "agent", "agent_co",
                                               "agent_addr"]]

    co = raw[raw.type == "CorporateOwner"][["registrationid", "name", "addr"]]
    co = lord[["registrationid", "landlord"]].merge(
        co, left_on=["registrationid", "landlord"], right_on=["registrationid", "name"])
    co = co.drop_duplicates("registrationid")[["registrationid", "addr"]] \
        .rename(columns={"addr": "owner_addr"})

    # filing date and the HPD building id (for the hpdonline.nyc.gov link) of the
    # registration row on this very lot; a registration can span several lots
    reg = pd.read_csv(ROOT / "data/hpd_registrations.csv", usecols=[
        "registrationid", "buildingid", "boroid", "block", "lot", "lastregistrationdate"])
    reg = reg.dropna(subset=["registrationid", "buildingid", "boroid", "block", "lot"])
    reg["bbl"] = (reg.boroid * 1_000_000_000 + reg.block * 10_000 + reg.lot).astype("int64")
    reg["registrationid"] = reg.registrationid.astype("int64")
    reg["hpd_id"] = reg.buildingid.astype("int64")
    reg["reg_last"] = reg.lastregistrationdate.str[:10]
    reg = reg.sort_values(["reg_last", "hpd_id"]).drop_duplicates(
        ["registrationid", "bbl"])[["registrationid", "bbl", "hpd_id", "reg_last"]]

    out = (lord[["bbl", "registrationid"]]
           .merge(ag, on="registrationid", how="left")
           .merge(co, on="registrationid", how="left")
           .merge(reg, on=["registrationid", "bbl"], how="left"))
    for c in ("agent", "agent_addr", "owner_addr"):
        out[c] = out[c].fillna("").str.strip()
    out["agent_co"] = out.agent_co.fillna(0).astype(int)
    out["hpd_id"] = out.hpd_id.astype("Int64")
    assert out.bbl.is_unique, "bbl_contacts would have duplicate bbls"
    for c in ("agent_addr", "owner_addr"):
        assert not out[c].str.contains(r"#|\b(?:apt|apartment|unit)\b", case=False,
                                       regex=True).any(), f"a unit survived in {c}"
    out.to_csv(OUT, index=False)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pull", action="store_true", help="re-download feu5-w2e2 first")
    a = ap.parse_args()
    if a.pull or not RAW.exists():
        raw = pull()
    else:
        raw = pd.read_csv(RAW, dtype=str)
        print(f"reusing {RAW.name}: {len(raw):,} rows")
    out = build(raw)
    n = len(out)
    print(f"wrote {OUT.relative_to(ROOT)}: {n:,} bbls | managing agent {(out.agent != '').mean():.1%}"
          f" (company {out.agent_co.mean():.1%}) | corporate owner address "
          f"{(out.owner_addr != '').mean():.1%} | HPD building id {out.hpd_id.notna().mean():.1%}")
    return out


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)
