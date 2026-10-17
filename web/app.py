"""HeatAhead web app: signup (tenant/landlord/gov/viewer), 3D risk map,
building lookup with history, live monitor on the realtime replay service.

Run from the repo root:  python web/app.py          (port 8080)
Expects model outputs in model/out/ and data in data/ (see web/README.md).
The live monitor proxies the realtime service (realtime/app.py, port 5000);
set REALTIME_URL to point elsewhere.
"""

import os
import re
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from flask import Flask, g, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model/out"
DATA = ROOT / "data"
DB = Path(__file__).resolve().parent / "heatahead.db"
REALTIME_URL = os.environ.get("REALTIME_URL", "http://127.0.0.1:5000")
GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
ROLES = ("tenant", "landlord", "government", "viewer")

app = Flask(__name__)

# ------------------------------------------------------------------ data load
print("loading model outputs...")
season_risk = pd.read_csv(OUT / "season_risk_2026.csv").set_index("bbl")
ranked = pd.read_csv(OUT / "ranked_inspection_list.csv").set_index("bbl")
reliability = pd.read_csv(OUT / "season_reliability.csv")

bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
bd["season"] = bd.day.dt.year - (bd.day.dt.month < 10)
c_hist = bd.groupby(["bbl", "season"])["n"].sum()
last_complaint = bd.groupby("bbl").day.max()

viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol.bbl.astype("int64")
viol["day"] = pd.to_datetime(viol.inspectiondate)
viol["season"] = viol.day.dt.year - (viol.day.dt.month < 10)
v_hist = viol.groupby(["bbl", "season"]).size()
last_violation = viol.groupby("bbl").day.max()

lord = pd.read_csv(DATA / "second_tier/bbl_landlord.csv")
lord["portfolio"] = lord.groupby("landlord").bbl.transform("nunique")
lord = lord.drop_duplicates("bbl").set_index("bbl")

CITYWIDE_SEASON_MEDIAN = float(season_risk.p_season.median())
print(f"loaded: {len(season_risk):,} ranked buildings")


# ------------------------------------------------------------------ database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, role TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT, address TEXT, bbl INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, bbl))""")
        g.db.execute("""CREATE TABLE IF NOT EXISTS alerts_sent (
            id INTEGER PRIMARY KEY, bbl INTEGER, email TEXT, spell_start TEXT,
            sent TEXT DEFAULT CURRENT_TIMESTAMP)""")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d is not None:
        d.close()


# ------------------------------------------------------------------ helpers
def seasons_label(s):
    return f"{s}-{str(s + 1)[2:]}"


def building_payload(bbl):
    if bbl not in season_risk.index:
        return dict(bbl=bbl, ranked=False,
                    note="No complaint or violation record; not individually "
                         "ranked. Citywide median winter risk is "
                         f"{CITYWIDE_SEASON_MEDIAN:.0%}.")
    sr = season_risk.loc[bbl]
    out = dict(
        bbl=int(bbl), ranked=True,
        season=dict(p=round(float(sr.p_season), 3),
                    rank=int(sr["rank"]), of=len(season_risk),
                    vs_median=round(float(sr.p_season) / CITYWIDE_SEASON_MEDIAN, 1)),
        complaints={seasons_label(s): int(n) for (b, s), n in
                    c_hist.loc[[bbl]].items()} if bbl in c_hist.index.get_level_values(0) else {},
        violations={seasons_label(s): int(n) for (b, s), n in
                    v_hist.loc[[bbl]].items()} if bbl in v_hist.index.get_level_values(0) else {},
        last_complaint=str(last_complaint.get(bbl, "never"))[:10],
        last_violation=str(last_violation.get(bbl, "never"))[:10],
        units=int(sr.unitsres), cd=int(sr.cd) if pd.notna(sr.cd) else None,
        chronic=bool(sr.chronic),
    )
    if bbl in ranked.index:
        r = ranked.loc[bbl]
        out["cold_day"] = dict(p=round(float(r.p_calibrated), 3),
                               rank=int(r["rank"]) if "rank" in r.index else None)
        out["coords"] = [float(r.longitude), float(r.latitude)]
    if bbl in lord.index:
        lo = lord.loc[bbl]
        other = int(lo.portfolio) - 1
        out["landlord"] = dict(name=str(lo.landlord).title(), portfolio=int(lo.portfolio),
                               note=f"owns {other} other registered building(s)" if other else
                               "single-building owner")
    return out


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return render_template("index.html", roles=ROLES)


@app.get("/map")
def map_page():
    return render_template("map.html")


@app.get("/building")
def building_page():
    return render_template("building.html")


@app.get("/monitor")
def monitor_page():
    return render_template("monitor.html")


# ------------------------------------------------------------------ api
@app.get("/api/lookup")
def api_lookup():
    address = (request.args.get("address") or "").strip()
    if len(address) < 4:
        return jsonify(error="give a street address"), 400
    try:
        r = requests.get(GEOSEARCH, params={"text": address + ", New York"},
                         timeout=6).json()
        feats = r.get("features") or []
        if not feats:
            return jsonify(error="address not found"), 404
        p = feats[0]["properties"]
        bbl = int(p["addendum"]["pad"]["bbl"])
        return jsonify(bbl=bbl, normalized=p.get("label", address))
    except Exception:
        return jsonify(error="geocoder unavailable - try the 10-digit BBL"), 502


@app.get("/api/building/<int:bbl>")
def api_building(bbl):
    return jsonify(building_payload(bbl))


@app.get("/api/reliability")
def api_reliability():
    return jsonify(reliability.to_dict("records"))


@app.get("/api/map_data")
def api_map_data():
    m = season_risk.join(ranked[["latitude", "longitude", "p_calibrated"]], how="inner")
    m = m.dropna(subset=["latitude", "longitude"])
    cols = np.column_stack([m.longitude.round(5), m.latitude.round(5),
                            m.p_season.round(3), m.c_last1.astype(int),
                            m.unitsres.astype(int)])
    return jsonify(dict(columns=["lon", "lat", "p_season", "c_last1", "units"],
                        rows=cols.tolist(), bbls=m.index.astype(str).tolist()))


@app.post("/api/register")
def api_register():
    b = request.get_json(silent=True) or {}
    role = str(b.get("role", "")).lower()
    email = str(b.get("email", "")).strip()
    phone = str(b.get("phone", "")).strip() or None
    address = str(b.get("address", "")).strip() or None
    if role not in ROLES:
        return jsonify(error=f"role must be one of {ROLES}"), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="valid email required"), 400
    bbl = b.get("bbl")
    if bbl is None and address and role in ("tenant", "landlord"):
        with app.test_request_context(f"/api/lookup?address={address}"):
            looked = api_lookup()
        if isinstance(looked, tuple):
            return jsonify(error="could not resolve that address"), 400
        bbl = looked.get_json()["bbl"]
    try:
        db().execute("INSERT OR IGNORE INTO users(role, email, phone, address, bbl) "
                     "VALUES (?,?,?,?,?)", (role, email, phone, address, bbl))
        db().commit()
    except sqlite3.Error as e:
        return jsonify(error=str(e)), 500
    resp = dict(ok=True, role=role, bbl=bbl)
    if bbl and int(bbl) in season_risk.index:
        resp["p_season"] = round(float(season_risk.loc[int(bbl)].p_season), 3)
    return jsonify(resp)


@app.get("/api/live/<path:endpoint>")
def api_live(endpoint):
    """Proxy to the realtime replay service so the monitor page is same-origin."""
    if endpoint not in ("queue", "stats"):
        return jsonify(error="unknown endpoint"), 404
    try:
        r = requests.get(f"{REALTIME_URL}/{endpoint}",
                         params=request.args, timeout=4)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except requests.RequestException:
        return jsonify(offline=True, error="realtime service unreachable"), 503


@app.post("/api/live/replay/start")
def api_live_start():
    try:
        r = requests.post(f"{REALTIME_URL}/replay/start",
                          json=request.get_json(silent=True) or {}, timeout=4)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except requests.RequestException:
        return jsonify(offline=True, error="realtime service unreachable"), 503


@app.get("/unsubscribe")
def unsubscribe():
    email = (request.args.get("email") or "").strip()
    bbl = request.args.get("bbl")
    cur = db().execute("DELETE FROM users WHERE email=? AND (bbl=? OR ? IS NULL)",
                       (email, bbl, bbl))
    db().commit()
    return (f"Unsubscribed {cur.rowcount} registration(s) for {email}. "
            "You can re-register any time.", 200, {"Content-Type": "text/plain"})


@app.get("/api/my_buildings")
def api_my_buildings():
    """Landlord view: every building registered under this email, plus the
    rest of each building's landlord portfolio (public record)."""
    email = (request.args.get("email") or "").strip()
    rows = db().execute("SELECT bbl FROM users WHERE email=? AND bbl IS NOT NULL",
                        (email,)).fetchall()
    own = {int(r[0]) for r in rows}
    portfolio = set(own)
    for b in own:
        if b in lord.index:
            portfolio |= set(lord[lord.landlord == lord.loc[b].landlord].index)
    out = []
    for b in sorted(portfolio):
        if b in season_risk.index:
            sr = season_risk.loc[b]
            out.append(dict(bbl=int(b), registered=b in own,
                            p_season=round(float(sr.p_season), 3),
                            rank=int(sr["rank"]), units=int(sr.unitsres),
                            c_last1=int(sr.c_last1), v_last1=int(sr.v_last1)))
        else:
            out.append(dict(bbl=int(b), registered=b in own, ranked=False))
    return jsonify(buildings=out)


@app.get("/api/queue.csv")
def api_queue_csv():
    """Government export: the current top-k inspection list as CSV."""
    k = max(1, min(int(request.args.get("k", 500)), 5000))
    cols = ["rank", "p_calibrated", "tenants_at_risk", "unitsres", "cd",
            "latitude", "longitude", "c_last1", "v_last1", "chronic"]
    body = ranked.sort_values("rank").head(k)[cols].to_csv()
    return (body, 200, {"Content-Type": "text/csv",
                        "Content-Disposition": f"attachment; filename=heatahead_top{k}.csv"})


@app.get("/api/draft_message/<int:bbl>")
def api_draft_message(bbl):
    """Template a message to the building's registered owner (the later
    'Claude-drafted email' feature slots in here)."""
    p = building_payload(bbl)
    if not p.get("ranked"):
        return jsonify(error="building not ranked"), 404
    name = p.get("landlord", {}).get("name", "Building owner")
    seasons = sorted(p["complaints"].keys())[-1:]
    recent = p["complaints"].get(seasons[0], 0) if seasons else 0
    body = (f"Dear {name},\n\n"
            f"Our records show this building (BBL {bbl}) has a "
            f"{p['season']['p']:.0%} modeled chance of a heat outage this "
            f"winter (citywide rank {p['season']['rank']:,} of "
            f"{p['season']['of']:,}), with {recent} heat complaints last "
            f"season. NYC heat season requires 68F by day and 62F overnight "
            f"from October 1 to May 31. We encourage a boiler inspection "
            f"before the first cold spell.\n\nHeatAhead")
    return jsonify(to=name, subject=f"Heat-risk notice for BBL {bbl}", body=body,
                   note="draft only - nothing is sent")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)),
            threaded=True, use_reloader=False)
