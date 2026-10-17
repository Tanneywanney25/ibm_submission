# HeatAhead web app — spec for the building-lookup + live map

Hand-off doc for streams 3/6. Everything here runs on the LinuxONE instance with
Flask; the model side is done and its outputs are listed below. Nothing in this
spec requires retraining.

## Are the probabilities "bad"? Read this first

No — and the app should say this out loud. On a freezing day only **1.2% of
buildings** fail. So:

- A building showing **2%** is ~2× the citywide risk; **15%** is ~13×; **65%** is
  ~54× — the model concentrates risk extremely well.
- Of the **top 100** buildings each cold day, **68.7% fail within 48h** and
  **96.5% fail within 30 days**. Random inspection gets 1 of 100.
- The probabilities are **calibrated**: when the app says 15%, 15% actually fail
  (verified on held-out days — table below). Most "AI scores" are made-up numbers;
  ours are measured. Small-looking and honest beats big and fake.

Calibration verified across 9 held-out splits (random, day-wise, and
fit-on-mild-days → test-on-coldest-days):

| displayed risk | buildings/day (typ.) | actually failed |
|---|---|---|
| ~0.1% | ~60,000 | 0.1-0.2% |
| ~2% | ~7,000 | 1.9-2.7% |
| ~7% | ~1,700 | 5-10% |
| ~15% | ~1,100 | 12-16% |
| ~25% | ~400 | 23-30% |
| ~40% | ~300 | 36-46% |
| ~65% | ~130 | 58-71% |

**Display rule:** below 20%, show the exact number. At 20%+, show bands
("high — roughly 25-35%", "very high — roughly 55-70%"): the top bins hold only a
few hundred buildings, so exact digits aren't supported there.

## The two user-facing views

### 1. Inspector view (already specced in stream6-realtime.md)
Map + ranked queue, polling `/queue` during the cold-snap replay. Two sort modes:
most likely to fail (`p_calibrated`) and most tenants at risk (`tenants_at_risk`).

### 2. Tenant lookup — "check your building"
Search box: address → BBL → that building's risk and full history.

- **Geocoding:** NYC GeoSearch, free, no key:
  `https://geosearch.planninglabs.nyc/v2/search?text=330 E 139 St, Bronx`
  → take `features[0].properties.addendum.pad.bbl` (10-digit string). Cache results.
- **Page contents, top to bottom:**
  1. **"Chance this building loses heat this winter": `p_season` from
     `model/out/season_risk_2026.csv`** — the headline number, verified bin-by-bin
     on the held-out 2025-26 winter (`season_reliability.csv`: predicted 89% ->
     actual 89%; every bin within ~2 points). 3,927 buildings sit at >=80%.
     Below it, the sharper number: risk on the next freezing day (calibrated %,
     "N× the citywide average", rank "#312 of 67,125").
  2. **Complaint history:** complaints per season (bar row, 2017-18 → now), last
     complaint date, count of whole-building (ENTIRE BUILDING) complaints.
  3. **Violation history:** heat violations per season, last violation date.
  4. Context chips: units, year built, chronic flag, landlord portfolio size and
     complaints across the landlord's other buildings, boiler defects on record,
     oil-fired flag.
  5. The one-line trust note: "When we say 15%, 15 of 100 such buildings lost
     heat — verified on last winter." Link/expand to the table above.
  6. "What to do": 311 instructions + the Oct 1, 2026 rule (HPD must attempt an
     inspection for every non-anonymous heat complaint).
- **Tone rule:** this describes the building's track record, never an accusation.
  Building-level only — no apartment numbers anywhere (the raw HPD file has them;
  never ship that file to the frontend).
- A building not in the ranked list = no history → show "no complaint or violation
  record; not individually ranked" + citywide base rate, not a zero.

## Data files the app loads at startup (all already produced)

| file | rows | gives |
|---|---|---|
| `model/out/ranked_inspection_list.csv` | 67,125 | rank, score, **p_calibrated**, tenants_at_risk, units, cd, lat/lon, c_last1, v_last1, chronic |
| `model/out/building_day_counts.csv` | 2.0M | complaints per building per day → season history + sparkline |
| `model/out/building_day_counts_bw.csv` | ~0.9M | whole-building complaints per day |
| `data/hpd_heat_violations.csv` | 223k | violation dates per building (filter orders 666/966/674) |
| `data/second_tier/bbl_landlord.csv` | 159k | landlord + portfolio size |
| `data/second_tier/bbl_boiler.csv` | 63k | boiler defects, fuel |
| `model/out/heat_model.json` + `calibration.csv` | — | only needed for live re-scoring (stream 6 loop) |

Precompute at startup: `hist[bbl] = {complaints_by_season, violations_by_season,
last_complaint, last_violation, bw_count}` — a dict in memory; the files above are
small enough (~100 MB total) for the 7.8 GB guest.

## Endpoints (add to the stream-6 Flask service)

```
GET /lookup?address=...        -> {bbl, normalized_address}        (GeoSearch proxy)
GET /building/<bbl>            -> {risk: {p_calibrated, band, rank, multiple_of_avg},
                                   complaints: {by_season: {...}, last_date, building_wide},
                                   violations: {by_season: {...}, last_date},
                                   context: {unitsres, yearbuilt, chronic, landlord_nbldg,
                                             landlord_other_complaints, boiler_defects, fuel_oil},
                                   not_ranked: false}
GET /queue?k=50&sort=risk|tenants   (exists in stream-6 spec)
GET /stats                          (exists)
GET /reliability               -> the calibration table (for the trust expander)
```

## Minimal skeleton (building page; ~60 lines on top of stream 6's service)

```python
import pandas as pd, requests
from flask import Flask, jsonify, request

app = Flask(__name__)
ranked = pd.read_csv("model/out/ranked_inspection_list.csv").set_index("bbl")
bd = pd.read_csv("model/out/building_day_counts.csv", parse_dates=["day"])
bd["season"] = bd.day.dt.year - (bd.day.dt.month < 10)
C = bd.groupby(["bbl", "season"])["n"].sum()
viol = pd.read_csv("data/hpd_heat_violations.csv",
                   usecols=["bbl", "inspectiondate", "ordernumber"], low_memory=False)
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol.bbl.astype("int64")
viol["d"] = pd.to_datetime(viol.inspectiondate)
viol["season"] = viol.d.dt.year - (viol.d.dt.month < 10)
V = viol.groupby(["bbl", "season"]).size()
BASE = 0.012                                  # citywide cold-day failure rate

@app.get("/lookup")
def lookup():
    r = requests.get("https://geosearch.planninglabs.nyc/v2/search",
                     params={"text": request.args["address"]}, timeout=5).json()
    f = r["features"][0]["properties"]
    return jsonify(bbl=int(f["addendum"]["pad"]["bbl"]), normalized_address=f["label"])

@app.get("/building/<int:bbl>")
def building(bbl):
    cs = {int(s): int(n) for (b, s), n in C.items() if b == bbl}   # or C.loc[bbl].to_dict()
    vs = V.loc[bbl].to_dict() if bbl in V.index.get_level_values(0) else {}
    if bbl in ranked.index:
        row = ranked.loc[bbl]
        risk = dict(p_calibrated=round(float(row.p_calibrated), 3),
                    rank=int(row["rank"]) if "rank" in row else None,
                    multiple_of_avg=round(float(row.p_calibrated) / BASE, 1))
    else:
        risk, cs, vs = dict(not_ranked=True, citywide_avg=BASE), {}, {}
    return jsonify(risk=risk, complaints_by_season=cs, violations_by_season=vs)
```

(Use `C.loc[bbl]` with a try/except in real code — the comprehension above is
illustrative. Open the Flask port with iptables and persist to
`/etc/iptables/rules.v4`; only 22 is open by default.)

## Forecast-driven alerts — "register your building"

The model takes temperature as input, so risk under a *predicted* temperature list
is just scoring with forecast values — no retraining.

- **Register:** address (→ BBL via GeoSearch) + email + consent checkbox, stored in
  SQLite on the instance. Unsubscribe link in every mail.
- **Hourly job:** pull the Open-Meteo 7-day forecast. When it shows a freezing day,
  score all buildings under those forecast temperatures (0.4 s batch) and alert
  registered buildings whose risk crosses the threshold.
- **Alert on the spell/30-day probability, not the 48h one** — "high risk during
  this cold snap" is the actionable claim (and the one at 96% in the top ranks).
- **Threshold = calibrated bands** (e.g. alert at ≥20%): the reliability table
  states alert precision in advance — that is the alert-accuracy guarantee.
- **One alert per cold spell**, 7-day cooldown; never one email per cold day.
- Email copy: risk band, citywide rank, spell dates, and the action line: "call
  311 non-anonymously — since Oct 1, 2026 HPD must attempt an inspection."

Extra endpoints:

```
POST /register             {address, email}            -> {bbl, ok}
GET  /risk_curve/<bbl>     -> [{tmin: 30, p: ...}, {tmin: 20, ...}, {tmin: 10, ...}, {tmin: 0, ...}]
```

`/risk_curve` sweeps TMIN through 30/20/10/0°F (adjusting roll/lag fields
consistently) and returns the model's output - the per-building "risk vs
temperature" chart that shows temperature is the live input. SMTP: any free-tier
sender works for a demo; print-to-log is fine for the video.

## Demo beats (30 seconds in the video)

1. Type a Bronx address → page shows 62% risk band, 11 straight seasons of
   complaints, landlord owns 14 buildings with 212 complaints, 3 boiler defects.
2. Cut to the inspector map replaying Feb 8 — the same building climbs the queue
   live as replayed complaints arrive.
3. Point at the reliability table: "when we say 15%, it's 15%."
