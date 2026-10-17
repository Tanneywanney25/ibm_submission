"""HeatAhead web app: signup (tenant/landlord/gov/viewer), 3D risk map,
building lookup with history, live monitor on the realtime replay service.

One app, two modes (docs/VERCEL.md section 2):
  FULL  on the LinuxONE instance: pandas over model/out/ and data/, SQLite
        registrations in web/heatahead.db. Chosen when model/out/season_risk_2026.csv
        exists.
  LITE  on Vercel: the JSON that web/build_assets.py precomputes into public/data/,
        Flask + requests + the standard library only. Registrations are forwarded to
        REGISTER_FORWARD_URL (the instance) when it is set, else kept in /tmp.
Override with APP_MODE=full|lite.

Run from the repo root:  python web/app.py          (port 8080)
The live monitor proxies the realtime service (realtime/app.py, port 5000);
set REALTIME_URL to point elsewhere.
"""

import json
import os
import platform
import re
import sqlite3
import sys
import threading
import time
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import requests
from flask import (Flask, g, jsonify, redirect, render_template, request,
                   send_from_directory)

sys.path.append(str(Path(__file__).resolve().parent))
import mailer  # noqa: E402
import account_auth  # noqa: E402
import site_guide  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model/out"
DATA = ROOT / "data"
ASSETS = ROOT / "public/data"
ON_VERCEL = bool(os.environ.get("VERCEL"))
DB = Path("/tmp/heatahead.db") if ON_VERCEL else Path(__file__).resolve().parent / "heatahead.db"
MODE = (os.environ.get("APP_MODE") or
        ("full" if (OUT / "season_risk_2026.csv").exists() else "lite")).lower()
REALTIME_URL = os.environ.get("REALTIME_URL", "http://127.0.0.1:5000").rstrip("/")
COMPLAINT_URL = os.environ.get("COMPLAINT_URL", "http://127.0.0.1:5001").rstrip("/")
FORWARD_URL = os.environ.get("REGISTER_FORWARD_URL", "").rstrip("/") if MODE == "lite" else ""
ARCH = platform.machine().lower()
HOST = "vercel" if ON_VERCEL else ("linuxone" if ARCH == "s390x" else "local")
GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
ROLES = ("tenant", "landlord", "government", "viewer")
SHARDS = 128
# one building record; build_assets.py writes these as positional lists in public/data/b/.
# New fields go at the end: a shard built before them still reads (missing ones are None).
FIELDS = ("p", "rank", "units", "cd", "chronic", "c_last1", "v_last1", "complaints",
          "violations", "last_c", "last_v", "cold_p", "cold_rank", "lon", "lat",
          "lord", "lord_n",
          # T5a, from web/build_contacts.py (public HPD registration, business addresses)
          "agent", "agent_co", "agent_addr", "lord_addr", "hpd_id", "reg_last")
LAST_SEASON = 2025               # c_last1 and v_last1 count the 2025-26 heat season
DRAFT_ROLES = ("tenant", "landlord")
HPD_ONLINE = "https://hpdonline.nyc.gov/hpdonline/building/"
QUEUE_COLS = ["rank", "p_calibrated", "tenants_at_risk", "unitsres", "cd",
              "latitude", "longitude", "c_last1", "v_last1", "chronic"]

app = Flask(__name__)


def _int(x):
    return None if x is None or x != x else int(x)


# ------------------------------------------------------------------ data load
if MODE == "full":
    import numpy as np
    import pandas as pd

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

    # T5a: managing agent and business addresses; optional, the site runs without it
    f = DATA / "second_tier/bbl_contacts.csv"
    contacts = (pd.read_csv(f, keep_default_na=False, na_values={"hpd_id": [""]})
                .set_index("bbl") if f.exists() else None)

    # per-building history as plain dicts: one record costs a few dict lookups
    C_BY = {}
    for (b, s), n in c_hist.items():
        C_BY.setdefault(int(b), []).append([int(s), int(n)])
    V_BY = {}
    for (b, s), n in v_hist.items():
        V_BY.setdefault(int(b), []).append([int(s), int(n)])
    LAST_C = {int(b): str(d)[:10] for b, d in last_complaint.items()}
    LAST_V = {int(b): str(d)[:10] for b, d in last_violation.items()}

    META = dict(median=float(season_risk.p_season.median()), ranked=len(season_risk),
                cold_ranked=len(ranked), mode="full")
    RELIABILITY = reliability.to_dict("records")
    print(f"loaded: {len(season_risk):,} ranked buildings")
else:
    def _disk_asset(name):
        f = ASSETS / name
        return json.loads(f.read_text()) if f.exists() else None

    META = _disk_asset("meta.json") or dict(median=None, ranked=0, cold_ranked=0)
    RELIABILITY = _disk_asset("reliability.json") or []
    print(f"lite mode: {META.get('ranked', 0):,} ranked buildings from public/data "
          f"(built {META.get('built_at', 'never')}); "
          f"registrations -> {FORWARD_URL or DB}")

CITYWIDE_SEASON_MEDIAN = META["median"] or 0.0


@lru_cache(maxsize=32)
def _shard(n):
    """LITE: one public/data/b/<n>.json shard, from the bundle or (if the bundle
    left public/ out) from this deployment's own static CDN."""
    f = ASSETS / "b" / f"{n}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = requests.get(f"{request.host_url}data/b/{n}.json", timeout=4)
    r.raise_for_status()
    return r.json()


def building_record(bbl):
    """Everything the site knows about one building, as a dict over FIELDS,
    or None when the building is not in the season-risk ranking."""
    bbl = int(bbl)
    if MODE != "full":
        row = _shard(bbl % SHARDS).get(str(bbl))
        if not row:
            return None
        rec = dict.fromkeys(FIELDS)
        rec.update(zip(FIELDS, row))
        return rec
    if bbl not in season_risk.index:
        return None
    sr = season_risk.loc[bbl]
    rec = dict.fromkeys(FIELDS)
    rec.update(p=round(float(sr.p_season), 3), rank=int(sr["rank"]),
               units=_int(sr.unitsres), cd=_int(sr.cd), chronic=int(sr.chronic == 1),
               c_last1=_int(sr.c_last1), v_last1=_int(sr.v_last1),
               complaints=C_BY.get(bbl, []), violations=V_BY.get(bbl, []),
               last_c=LAST_C.get(bbl, "never"), last_v=LAST_V.get(bbl, "never"))
    if bbl in ranked.index:
        r = ranked.loc[bbl]
        rec.update(cold_p=round(float(r.p_calibrated), 3), cold_rank=_int(r["rank"]))
        if pd.notna(r.longitude) and pd.notna(r.latitude):
            rec.update(lon=round(float(r.longitude), 5), lat=round(float(r.latitude), 5))
    if bbl in lord.index:
        lo = lord.loc[bbl]
        rec.update(lord=display_name(lo.landlord), lord_n=int(lo.portfolio))
    if contacts is not None and bbl in contacts.index:
        ct = contacts.loc[bbl]
        rec.update(agent=display_name(ct.agent), agent_co=int(ct.agent_co),
                   agent_addr=ct.agent_addr or None, lord_addr=ct.owner_addr or None,
                   hpd_id=_int(ct.hpd_id), reg_last=ct.reg_last or None)
    return rec


def map_rows():
    """FULL: every ranked building with coordinates, for the risk map."""
    m = season_risk.join(ranked[["latitude", "longitude", "p_calibrated"]], how="inner")
    m = m.dropna(subset=["latitude", "longitude"])
    cols = np.column_stack([m.longitude.round(5), m.latitude.round(5),
                            m.p_season.round(3), m.c_last1.fillna(0).astype(int),
                            m.unitsres.fillna(0).astype(int)])
    return dict(columns=["lon", "lat", "p_season", "c_last1", "units"],
                rows=cols.tolist(), bbls=m.index.astype(str).tolist())


def queue_csv(k):
    """The top-k inspection list as CSV (FULL computes it, LITE slices top500.csv)."""
    if MODE == "full":
        q = ranked.sort_values("rank").head(k)[QUEUE_COLS].copy()
        q["p_calibrated"] = q.p_calibrated.clip(upper=0.99)
        return q.to_csv()
    f = ASSETS / "top500.csv"
    if not f.exists():
        return None
    return "\n".join(f.read_text().splitlines()[:k + 1]) + "\n"


# ------------------------------------------------------------------ database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, timeout=5)
        g.db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, role TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT, address TEXT, bbl INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, bbl))""")
        g.db.execute("""CREATE TABLE IF NOT EXISTS alerts_sent (
            id INTEGER PRIMARY KEY, bbl INTEGER, email TEXT, spell_start TEXT,
            sent TEXT DEFAULT CURRENT_TIMESTAMP)""")
        g.db.execute("""CREATE TABLE IF NOT EXISTS account_request_nonces (
            nonce TEXT PRIMARY KEY, expires INTEGER NOT NULL)""")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d is not None:
        d.close()


def forward(method, path, **kw):
    """Forward an account request and verify the matching signed backend reply."""
    try:
        body = (json.dumps(kw.pop("json"), separators=(",", ":"), ensure_ascii=False).encode()
                if "json" in kw else b"")
        target, headers, nonce = account_auth.signed_forward(
            method, path, kw.pop("actor", None) or account_auth.user(), body, kw.pop("params", None))
        if body:
            headers["Content-Type"] = "application/json"
        r = requests.request(method, f"{FORWARD_URL}{target}", data=body or None,
                             headers=headers, timeout=7, allow_redirects=False, **kw)
        if not account_auth.verify_reply(r, nonce):
            return None
        return (r.content, r.status_code, {"Content-Type": r.headers.get(
            "Content-Type", "application/json")})
    except (requests.RequestException, ValueError):
        return None


def consume_account_nonce(nonce, ttl=90):
    con = db()
    now = int(time.time())
    con.execute("DELETE FROM account_request_nonces WHERE expires < ?", (now,))
    cur = con.execute("INSERT OR IGNORE INTO account_request_nonces(nonce, expires) VALUES (?, ?)",
                      (nonce, now + ttl))
    con.commit()
    return cur.rowcount == 1


# ------------------------------------------------------- email sign-in (T14)
# The website signs a one-use 15-minute link; only the durable backend sends
# the email (instance SMTP) and consumes the link's nonce. No passwords exist.
def send_sign_in_link(email, link):
    if FORWARD_URL:
        sent = forward("POST", "/api/account/email_link", json=dict(link=link),
                       actor=account_auth.email_identity(email))
        return sent is not None and sent[1] == 200
    if ON_VERCEL:
        return False
    msg = mailer.sign_in_email(email, link)
    threading.Thread(target=mailer.send, args=(msg,), daemon=True).start()
    return True


def consume_sign_in_nonce(nonce, email):
    """True = fresh, False = already used, None = backend unavailable (fail closed)."""
    if FORWARD_URL:
        sent = forward("POST", "/api/account/email_consume", json=dict(nonce=nonce),
                       actor=account_auth.email_identity(email))
        if sent is None or sent[1] != 200:
            return None
        try:
            return bool(json.loads(sent[0]).get("fresh"))
        except (ValueError, TypeError, AttributeError):
            return None
    if ON_VERCEL:
        return None
    return consume_account_nonce("email-link:" + nonce, ttl=account_auth.EMAIL_LINK_MAX_AGE)


# ------------------------------------------------------------------ helpers
def seasons_label(s):
    return f"{s}-{str(s + 1)[2:]}"


# filed names are mostly upper case; these stay upper when the rest is title-cased
UPPER = {"LLC", "LP", "LLP", "HDFC", "HFDC", "NY", "NYC", "USA", "II", "III", "IV",
         "AMO", "PC", "CPA", "JV", "NYCHA", "HUD", "YMCA", "YWCA"}
# short vowel-less words that are abbreviations, not acronyms: title-cased
ABBREV = {"ST", "RD", "DR", "LN", "CT", "PL", "PKWY", "BLVD", "FT", "MT", "JR", "SR", "MR",
          "MRS", "MS", "MGMT", "MGT", "BKLYN", "BX"}


# "apt.# 11", "#3", "Unit 4B": a few filers typed an address into the name field
UNIT_NUMBER = re.compile(r"\s*(?:#\s*\d\w*|\b(?:apt|apartment|unit)\b\.?\s*#?\s*\d\w*)", re.I)


def display_name(s):
    """'HSC MANAGEMENT CORP., AMO' -> 'HSC Management Corp., AMO'; None when empty.
    A name filed in mixed case is kept as filed. Any unit number is cut, which also
    drops a company's own numbering ('Realty #1 LLC' -> 'Realty LLC')."""
    s = re.sub(r"^\s*C/O\s+", "", str(s or "").strip(), flags=re.I)
    s = re.sub(r"\s+,", ",", " ".join(UNIT_NUMBER.sub("", s).split())).strip(" ,")
    if not s:
        return None
    if s != s.upper():
        return s
    out = []
    for w in s.split():
        bare = w.strip(".,&()")
        if bare in UPPER or (bare.isalpha() and 2 <= len(bare) <= 4 and bare not in ABBREV
                             and not re.search(r"[AEIOUY]", bare)):
            out.append(w)                          # an acronym: HSC, TZM, LLC
        else:                                      # 59TH -> 59th, O'BRIEN -> O'Brien
            out.append(re.sub(r"(\d)([A-Z]+)", lambda m: m.group(1) + m.group(2).lower(),
                              w.title()))
    return " ".join(out)


def _round_js(x, places=0):
    """Rounds like JS Math.round and toFixed: halves go up (Python's round() goes to even)."""
    return Decimal(x).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)


def fmt_risk(p):
    """The same text as fmtRisk() in base.html, so a draft quotes what the page shows."""
    p = min(float(p), 0.99)
    if p < 0.2:
        return f"{_round_js(p * 100, 1 if p < 0.1 else 0)}%"
    mid = min(99, int(_round_js(p * 20)) * 5)
    return (f"{'very high' if p >= 0.5 else 'high'} (roughly "
            f"{max(20, mid - 5)}–{min(99, mid + 5)}%)")


def building_payload(bbl):
    rec = building_record(bbl)
    if rec is None:
        return dict(bbl=int(bbl), ranked=False,
                    note="No complaint or violation record; not individually "
                         "ranked. Citywide median winter risk is "
                         f"{CITYWIDE_SEASON_MEDIAN:.0%}.")
    out = dict(
        bbl=int(bbl), ranked=True,
        season=dict(p=rec["p"], rank=rec["rank"], of=META["ranked"],
                    vs_median=round(rec["p"] / CITYWIDE_SEASON_MEDIAN, 1)
                    if CITYWIDE_SEASON_MEDIAN else None),
        complaints={seasons_label(s): n for s, n in rec["complaints"]},
        violations={seasons_label(s): n for s, n in rec["violations"]},
        last_complaint=rec["last_c"], last_violation=rec["last_v"],
        last_season=dict(season=seasons_label(LAST_SEASON), complaints=rec["c_last1"] or 0,
                         violations=rec["v_last1"] or 0),
        units=rec["units"], cd=rec["cd"], chronic=bool(rec["chronic"]),
    )
    if rec["cold_p"] is not None:
        out["cold_day"] = dict(p=rec["cold_p"], rank=rec["cold_rank"])
    if rec["lon"] is not None:
        out["coords"] = [rec["lon"], rec["lat"]]
    if rec["lord"]:
        other = rec["lord_n"] - 1
        out["landlord"] = dict(name=rec["lord"], portfolio=rec["lord_n"],
                               note=f"owns {other} other registered building(s)" if other else
                               "single-building owner")
        if rec["lord_addr"]:                     # corporate owners only (build_contacts.py)
            out["landlord"]["address"] = rec["lord_addr"]
    if rec["agent"]:
        # a company agent carries its business street address; a person, city only
        out["agent"] = dict(name=rec["agent"], company=bool(rec["agent_co"]),
                            address=rec["agent_addr"])
    if rec["hpd_id"]:
        out["registration"] = dict(hpd_building_id=rec["hpd_id"], last_filed=rec["reg_last"],
                                   record_url=f"{HPD_ONLINE}{rec['hpd_id']}")
    return out


# street-name words that say nothing about which street it is
NOISE = {"st", "street", "ave", "av", "avenue", "rd", "road", "pl", "place", "blvd",
         "boulevard", "dr", "drive", "ln", "lane", "ct", "court", "pkwy", "parkway",
         "ter", "terrace", "e", "east", "w", "west", "n", "north", "s", "south", "the",
         "of", "ny", "nyc", "new", "york", "usa", "us", "apt", "bronx", "brooklyn",
         "manhattan", "queens", "staten", "island"}
BOROUGHS = {"bronx": "Bronx", "brooklyn": "Brooklyn", "manhattan": "Manhattan",
            "queens": "Queens", "staten island": "Staten Island"}


def _words(s):
    return {re.sub(r"^(\d+)(st|nd|rd|th)$", r"\1", t) for t in re.findall(r"[a-z0-9]+", s.lower())}


def geocode(address):
    """Address -> ({bbl, normalized}, 200) or ({error}, 4xx/502).

    GeoSearch always answers with its nearest guess ("1600 Pennsylvania Ave" comes
    back as 218 Pennsylvania Avenue), so a match must share the house number, a
    street word and, when the address names one, the borough. A wrong building is
    worse than no building."""
    address = address.strip()
    if len(address) < 4:
        return dict(error="give a street address"), 400
    try:
        r = requests.get(GEOSEARCH, params={"text": address}, timeout=6)
        r.raise_for_status()
        feats = r.json().get("features") or []
    except (requests.RequestException, ValueError):
        return dict(error="geocoder unavailable - try the 10-digit BBL"), 502
    q = address.lower()
    m = re.match(r"\s*(\d+(?:-\d+)?[a-z]?)\b", q)
    house = m.group(1) if m else None
    words = {w for w in _words(q[m.end():] if m else q)
             if w not in NOISE and not re.fullmatch(r"\d{5}", w)}
    borough = next((v for k, v in BOROUGHS.items() if k in q), None)
    for f in feats:
        p = f.get("properties") or {}
        bbl = ((p.get("addendum") or {}).get("pad") or {}).get("bbl")
        if not bbl:
            continue
        if house and (p.get("housenumber") or "").lower() != house:
            continue
        if words and not words & _words(f"{p.get('street', '')} {p.get('name', '')}"):
            continue
        if borough and p.get("borough") != borough:
            continue
        return dict(bbl=int(bbl), normalized=p.get("label", address)), 200
    return dict(error="address not found in New York City - check the house number "
                      "and street, or enter the 10-digit BBL"), 404


def clean_bbl(v):
    s = str(v).strip()
    return int(s) if re.fullmatch(r"[1-5]\d{9}", s) else None


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return render_template("index.html", roles=ROLES, page="signup")


@app.get("/map")
def map_page():
    return render_template("map.html", page="map")


@app.get("/building")
def building_page():
    return render_template("building.html", page="building")


@app.get("/monitor")
def monitor_page():
    return render_template("monitor.html", page="monitor")


@app.get("/data/<path:name>")
def data_file(name):
    """public/data/ for local runs; on Vercel the CDN serves these before any rewrite."""
    return send_from_directory(ASSETS, name, max_age=3600)


# ------------------------------------------------------------------ api
@app.get("/api/health")
def api_health():
    out = dict(ok=True, mode=MODE, host=HOST, arch=ARCH, ranked=META["ranked"],
               built_at=META.get("built_at"),
               account_protocol=1 if len(app.secret_key or "") >= 32 else None,
               google_sign_in=account_auth.configured(),
               email_sign_in=account_auth.email_configured(),
               registrations_to="linuxone" if FORWARD_URL else
               ("unavailable (configure REGISTER_FORWARD_URL)" if ON_VERCEL else f"sqlite on {HOST}"))
    if MODE == "full" or not FORWARD_URL:
        out["registrations"] = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if FORWARD_URL:
        try:
            out["linuxone"] = requests.get(f"{FORWARD_URL}/api/health", timeout=3).json()
        except (requests.RequestException, ValueError):
            out["linuxone"] = dict(offline=True)
    return jsonify(out)


@app.get("/api/lookup")
def api_lookup():
    body, status = geocode(request.args.get("address") or "")
    return jsonify(body), status


@app.get("/api/building/<int:bbl>")
def api_building(bbl):
    try:
        return jsonify(building_payload(bbl))
    except (requests.RequestException, ValueError, OSError):
        return jsonify(error="building data unavailable right now"), 503


@app.get("/api/reliability")
def api_reliability():
    return jsonify(RELIABILITY)


@app.get("/api/map_data")
def api_map_data():
    if MODE != "full":
        return redirect("/data/map_data.json", 302)
    return jsonify(map_rows())


@app.post("/api/register")
def api_register():
    b = request.get_json(silent=True) or {}
    if not isinstance(b, dict):
        return jsonify(error="registration must be a JSON object"), 400
    role = str(b.get("role", "")).strip().lower()
    email = account_auth.user()["email"]
    supplied_email = str(b.get("email") or email).strip().lower()
    if supplied_email != email:
        return jsonify(error="Use the email address from your signed-in Google account."), 403
    phone = str(b.get("phone") or "").strip() or None
    address = UNIT_IN_ADDRESS.sub("", str(b.get("address") or "")).strip()[:200] or None
    raw_bbl = b.get("bbl")
    if role not in ROLES:
        return jsonify(error=f"role must be one of {', '.join(ROLES)}"), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(email) > 254:
        return jsonify(error="valid email required"), 400
    if phone and not 7 <= len(re.sub(r"\D", "", phone)) <= 15:
        return jsonify(error="phone looks wrong - leave it empty or give 7 to 15 digits"), 400
    needs_building = role in ("tenant", "landlord")
    bbl = None
    if needs_building and raw_bbl not in (None, ""):
        bbl = clean_bbl(raw_bbl)
        if bbl is None:
            return jsonify(error="a BBL is 10 digits starting with the borough (1-5)"), 400
    if needs_building and bbl is None and not address:
        return jsonify(error=f"a {role} sign-up needs the building's street address "
                             "(or its 10-digit BBL)"), 400
    if not needs_building:
        address = None           # government and viewer accounts are not tied to a building

    if FORWARD_URL:
        sent = forward("POST", "/api/register",
                       json=dict(role=role, email=email, phone=phone, address=address, bbl=bbl))
        if sent is not None:
            return sent
        return jsonify(error="Your building could not be saved right now. You are still signed in; please try again shortly.",
                       code="account_service_unavailable"), 503
    if ON_VERCEL:
        return jsonify(error="Building registration is being set up. You are signed in; please try again shortly.",
                       code="account_service_unavailable"), 503

    normalized = None
    if needs_building and bbl is None:
        looked, status = geocode(address)
        if status == 502:
            return jsonify(error="the address lookup service is down - enter the "
                                 "10-digit BBL instead"), 502
        if status != 200:
            return jsonify(error=looked["error"]), 400
        bbl, normalized = looked["bbl"], looked["normalized"]
    try:
        con = db()
        existed = con.execute(
            "SELECT 1 FROM users WHERE email=? AND bbl IS ? AND (bbl IS NOT NULL OR role=?)",
            (email, bbl, role)).fetchone() is not None
        if bbl is not None:
            con.execute("INSERT INTO users(role, email, phone, address, bbl) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(email, bbl) DO UPDATE SET role=excluded.role, "
                        "phone=COALESCE(excluded.phone, phone), "
                        "address=COALESCE(excluded.address, address)",
                        (role, email, phone, normalized, bbl))
        elif not existed:
            con.execute("INSERT INTO users(role, email, phone) VALUES (?,?,?)",
                        (role, email, phone))
        con.commit()
    except sqlite3.Error as e:
        return jsonify(error=f"could not save the sign-up: {e}"), 500
    resp = dict(ok=True, role=role, bbl=bbl, already_registered=existed,
                stored_on=HOST, arch=ARCH, durable=HOST != "vercel")
    if normalized:
        resp["normalized"] = normalized
    if bbl is not None:
        rec = building_record(bbl)
        if rec:
            resp["p_season"] = rec["p"]
    # welcome email (web/mailer.py: SMTP env on the instance, logged without it).
    # Only where sign-ups are durable: a Vercel function must not outlive its request.
    if not existed and not ON_VERCEL:
        msg = mailer.welcome_email(email, role, bbl, resp.get("p_season"))
        threading.Thread(target=mailer.send, args=(msg,), daemon=True).start()
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


@app.get("/api/current/<path:endpoint>")
def api_current(endpoint):
    """Published HPD heat complaints; separate from historical model replay."""
    if endpoint not in ("stats", "queue", "events"):
        return jsonify(error="unknown endpoint"), 404
    try:
        r = requests.get(f"{COMPLAINT_URL}/{endpoint}",params=request.args,timeout=3)
        payload=r.json()
        if not isinstance(payload,dict):
            raise ValueError("invalid response")
        return jsonify(payload),r.status_code,{"Cache-Control":"no-store"}
    except (requests.RequestException,ValueError):
        return jsonify(offline=True,error="current complaint service unreachable"),503


@app.get("/unsubscribe")
def unsubscribe():
    actor = account_auth.user()
    if not actor:
        if account_auth.configured():
            return redirect("/api/auth/google?" + requests.compat.urlencode({"next": request.full_path.rstrip("?")}))
        return redirect("/")     # sign in (Google or email link) from the home page first
    email = (request.args.get("email") or actor["email"]).strip().lower()
    if email != actor["email"]:
        return render_template("auth_message.html", title="Unsubscribe",
                               message="Sign in with the account that received this alert."), 403
    raw = request.args.get("bbl")
    bbl = clean_bbl(raw) if raw else None
    if raw and bbl is None:
        return render_template("auth_message.html", title="Unsubscribe", message="This building link is not valid."), 400
    return render_template("auth_message.html", title="Unsubscribe",
                           message=(f"Stop heat alerts for BBL {bbl}?" if bbl else "Stop all heat alerts for your account?"),
                           confirm_remove=True, bbl=bbl)


@app.post("/api/account/remove")
def api_remove_registration():
    b = request.get_json(silent=True) or request.form
    if not hasattr(b, "get"):
        return jsonify(error="account update must be a JSON object"), 400
    raw = b.get("bbl")
    bbl = clean_bbl(raw) if raw not in (None, "") else None
    if raw not in (None, "") and bbl is None:
        return jsonify(error="invalid building"), 400
    email = account_auth.user()["email"]
    if FORWARD_URL:
        sent = forward("POST", "/api/account/remove", json=dict(bbl=bbl))
        if sent is None:
            return jsonify(error="Your alerts could not be updated right now. Please try again shortly."), 503
        if request.form and sent[1] == 200:
            return redirect("/")
        return sent
    if ON_VERCEL:
        return jsonify(error="Account storage is temporarily unavailable."), 503
    cur = db().execute("DELETE FROM users WHERE email=? AND (bbl=? OR ? IS NULL)", (email, bbl, bbl))
    db().commit()
    if request.form:
        return redirect("/")
    return jsonify(ok=True, removed=cur.rowcount)


@app.post("/api/account/email_link")
def api_account_email_link():
    """Instance side of email sign-in: mail the website's signed link. Only the
    signed website-to-backend protocol may call this, never a browser session."""
    if not getattr(g, "account_proxy_nonce", None):
        return jsonify(error="This endpoint accepts only signed website requests."), 403
    b = request.get_json(silent=True) or {}
    link = str(b.get("link") or "")
    if len(link) > 2000 or not link.startswith(mailer.SITE_URL + "/api/auth/email/callback?"):
        return jsonify(error="invalid sign-in link"), 400
    msg = mailer.sign_in_email(account_auth.user()["email"], link)
    threading.Thread(target=mailer.send, args=(msg,), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/account/email_consume")
def api_account_email_consume():
    """Instance side of email sign-in: one-use consumption of a link's nonce."""
    if not getattr(g, "account_proxy_nonce", None):
        return jsonify(error="This endpoint accepts only signed website requests."), 403
    b = request.get_json(silent=True) or {}
    nonce = b.get("nonce")
    if not isinstance(nonce, str) or not 20 <= len(nonce) <= 100:
        return jsonify(error="invalid nonce"), 400
    return jsonify(ok=True, fresh=consume_account_nonce(
        "email-link:" + nonce, ttl=account_auth.EMAIL_LINK_MAX_AGE))


@app.get("/api/my_buildings")
def api_my_buildings():
    """Landlord view: every building registered under this email, plus the
    rest of each building's landlord portfolio (public record)."""
    email = account_auth.user()["email"]
    if (request.args.get("email") or email).strip().lower() != email:
        return jsonify(error="You can only open buildings registered to your own account."), 403
    if FORWARD_URL:
        sent = forward("GET", "/api/my_buildings", params=dict(email=email))
        if sent is not None:
            return sent
        return jsonify(error="Your saved buildings could not be loaded. Please try again shortly."), 503
    if ON_VERCEL:
        return jsonify(error="Account storage is temporarily unavailable."), 503
    registrations = [dict(role=r[0], bbl=r[1]) for r in db().execute(
        "SELECT role, bbl FROM users WHERE email=? ORDER BY id DESC", (email,)).fetchall()]
    rows = db().execute("SELECT bbl FROM users WHERE email=? AND bbl IS NOT NULL",
                        (email,)).fetchall()
    own = {int(r[0]) for r in rows}
    portfolio = set(own)
    if MODE == "full":           # LITE has no landlord index: registered buildings only
        for b in own:
            if b in lord.index:
                portfolio |= set(lord[lord.landlord == lord.loc[b].landlord].index)
    out = []
    for b in portfolio:
        rec = building_record(b)
        if rec:
            out.append(dict(bbl=int(b), registered=b in own, p_season=rec["p"],
                            rank=rec["rank"], units=rec["units"], c_last1=rec["c_last1"],
                            v_last1=rec["v_last1"], landlord=rec["lord"]))
        else:
            out.append(dict(bbl=int(b), registered=b in own, ranked=False))
    out.sort(key=lambda x: (not x["registered"], -(x.get("p_season") or 0), x["bbl"]))
    return jsonify(buildings=out[:200], total=len(out), registrations=registrations)


@app.get("/api/queue.csv")
def api_queue_csv():
    """Government export: the current top-k inspection list as CSV."""
    try:
        k = int(request.args.get("k", 500))
    except ValueError:
        return jsonify(error="k must be an integer"), 400
    k = max(1, min(k, 5000 if MODE == "full" else 500))
    body = queue_csv(k)
    if body is None:
        return jsonify(error="inspection list not built yet"), 503
    return (body, 200, {"Content-Type": "text/csv",
                        "Content-Disposition": f"attachment; filename=heatahead_top{k}.csv"})


# a unit in a user-supplied address is cut: drafts are building-level like everything else
UNIT_IN_ADDRESS = re.compile(r"\s*(?:#|\b(?:apt|apartment|unit)\b\.?)\s*[\w-]*", re.I)
HEAT_LAW = ("From October 1 to May 31, city law requires at least 68°F indoors between "
            "6 a.m. and 10 p.m. whenever it is below 55°F outside, and at least 62°F "
            "indoors overnight.")


def _n(k, word):
    return f"{k:,} {word}{'' if k == 1 else 's'}"


def draft_message(p, role, address=""):
    """T5b: a notice the user sends from their own mail client, built only from the
    building payload. tenant: a resident's request to the registered owner, care of the
    managing agent. landlord: the owner's own pre-winter self-audit. Every number is
    one the building page shows; the model's estimate is framed as an estimate."""
    bbl, s, last = p["bbl"], p["season"], p["last_season"]
    owner, agent = p.get("landlord") or {}, p.get("agent") or {}
    where = f"{address} (BBL {bbl})" if address else f"the building at BBL {bbl}"
    times = (f", about {s['vs_median']:g} times the citywide median"
             if s.get("vs_median") and s["vs_median"] >= 1.5 else "")
    record = (f"{_n(last['complaints'], 'heat complaint')} and "
              f"{_n(last['violations'], 'heat violation')} in the {last['season']} heat season")
    if p.get("last_complaint") not in (None, "never"):
        record += f"; the most recent complaint on record was filed on {p['last_complaint']}"
    estimate = (f"a {fmt_risk(s['p'])} modeled chance of at least one heat outage this "
                f"winter, rank {s['rank']:,} of {s['of']:,} buildings citywide{times}")
    recipients = []
    if owner:
        recipients.append(", ".join(x for x in (owner["name"], "registered owner",
                                                 owner.get("address")) if x))
    if agent:
        recipients.append(", ".join(x for x in ((("c/o " if role == "tenant" else "") +
                                                  agent["name"]), "managing agent",
                                                 agent.get("address")) if x))
    label = address or f"BBL {bbl}"

    if role == "tenant":
        to = owner.get("name") or "Building owner"
        subject = f"Request for a heating check before winter: {label}"
        body = (f"Dear {to},\n\n"
                f"I am a resident of {where}, and I am writing before the cold weather to "
                f"ask that the building's heating system be inspected and serviced.\n\n"
                f"HeatAhead, a public model built from New York City heat complaint and "
                f"violation records, gives this building {estimate}. City records show "
                f"{record}.\n\n"
                f"This is a statistical estimate, not a finding about the building's "
                f"equipment. I would still appreciate a boiler inspection before the first "
                f"cold spell, and a notice in the lobby saying whom residents should contact "
                f"if the heat goes out.\n\n"
                f"{HEAT_LAW}\n\n"
                f"Thank you,\n[Your name]")
    else:
        to = agent.get("name") or owner.get("name") or "Building file"
        others = (owner.get("portfolio") or 1) - 1
        portfolio = (f"\n\nThe same registered owner holds {_n(others, 'other registered building')}"
                     f"; the landlord view on HeatAhead lists them riskiest first."
                     if others else "")
        subject = f"Pre-winter heating self-audit: {label}"
        body = (f"Self-audit note for {where}"
                f"{', registered to ' + owner['name'] if owner else ''}.\n\n"
                f"HeatAhead's model, built from New York City heat complaint and violation "
                f"records, gives this building {estimate}. The public record behind that "
                f"estimate: {record}.{portfolio}\n\n"
                f"Before the first cold spell:\n"
                f"1. Have a licensed contractor service the boiler and burner and test the "
                f"low-water cutoff.\n"
                f"2. Confirm the fuel supply or gas account, and that this year's DOB boiler "
                f"inspection is filed.\n"
                f"3. Check heat on the top floors and at the far ends of the building, and "
                f"bleed radiators where needed.\n"
                f"4. Post a 24-hour heat contact in the lobby so residents can reach someone "
                f"before they call 311.\n\n"
                f"{HEAT_LAW}\n\n"
                f"This is a modeled estimate for planning, not a violation or a finding by HPD.")
    return dict(to=to, recipients=recipients, subject=subject, body=body, framing=role,
                note="draft only - nothing is sent")


@app.get("/api/draft_message/<int:bbl>")
def api_draft_message(bbl):
    """?as=tenant (default) or landlord; ?address= names the building in the text (the
    page passes the looked-up street address). Nothing is ever sent from here: the user
    copies the draft or opens it in their own mail client (T5c, an AI-written draft,
    would swap in behind this same response shape)."""
    role = (request.args.get("as") or "tenant").strip().lower()
    if role not in DRAFT_ROLES:
        return jsonify(error=f"as must be one of {', '.join(DRAFT_ROLES)}"), 400
    try:
        p = building_payload(bbl)
    except (requests.RequestException, ValueError, OSError):
        return jsonify(error="building data unavailable right now"), 503
    if not p.get("ranked"):
        return jsonify(error="building not ranked"), 404
    address = UNIT_IN_ADDRESS.sub("", request.args.get("address") or "")
    address = " ".join(address.split()).strip(" ,")[:120]
    return jsonify(draft_message(p, role, address))


account_auth.init_app(app, consume_account_nonce, email_backend=dict(
    ready=lambda: not ON_VERCEL or bool(FORWARD_URL),
    send_link=send_sign_in_link, consume=consume_sign_in_nonce))
site_guide.init_app(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)),
            threaded=True, use_reloader=False)
