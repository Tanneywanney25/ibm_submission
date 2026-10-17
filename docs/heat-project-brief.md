# NYC Heat Failure Ranker — full project brief

IBM Z Datathon 2026 (Oct 17-18). Everything verified as of Oct 16, 2026. Hand this to a fresh session or teammate and they can build from it.

---

## 1. The project

Predict which NYC residential buildings will lose heat during an upcoming cold snap, using each building's complaint and violation history plus the weather forecast, and output a ranked list so inspectors can visit before tenants call 311.

**Research question.** Can short-range temperature forecasts, combined with building-level complaint, violation and structural histories, predict which New York City residential buildings will experience heat service failures during an upcoming cold period, enabling proactive inspection before tenants file complaints?

**Hypothesis.** A forecast-triggered, building-level risk ranking identifies a larger share of verified heat failures per inspection than retrospective targeting, with the greatest gain in the first 48 hours of a cold period.

**Track:** Real-Time AI for Critical Decisions, if a replayed cold-snap event loop gets built. Wildcard as fallback.

---

## 2. Event facts

### Scoring rubric (from IBM's host guide; rows sum to 90 though the guide says 100, so treat as likely-not-final)

| Row | Points |
|---|---|
| Problem relevance and impact | 20 |
| Data handling and methodology | 20 |
| Innovation and creativity | 20 |
| IBM Z technology integration | 15 |
| Presentation and storytelling | 10 |
| Reproducibility and documentation | 5 |
| Bonus: community impact (underserved communities) | +5 |
| Bonus: polished live demo | +3 |
| Bonus: public documented GitHub repo | +2 |

### Submission
- Video, max 3 minutes: problem, data behind it, solution, and **how it uses IBM Z** (must show the LinuxONE instance and the model)
- Code on GitHub, team number in the project title, e.g. `[ONLXXX]`
- Submitted on Hack2skill
- Winners announced Oct 28; IBM Z Day showcase Nov 18

### Rules
- No work created in advance; projects must start within the hacking window
- Open-source libraries allowed, links required in the submission
- Team size stated as both "up to five" and "up to six" in the same guide; five is safe

### Unverified, confirm by hand
- Exact submission deadline in Eastern time (two readings differ by ~10.5 hours)
- Whether a New York hub exists (only UT Dallas confirmed)
- Per-place prize amounts
- Whether the rubric above is final

---

## 3. Data on hand

All downloaded Oct 16, 2026, in `C:\Users\emfco` on the team's Windows laptop. Needs copying to the LinuxONE instance.

| File | Rows | Covers |
|---|---|---|
| `ygpa-z7cr.csv` (361 MB) | 2,219,844 | HPD heat/hot water complaints, 2017-07-01 to 2026-10-14 |
| `wvxf-dwi5.csv` (26.7 MB) | 223,430 | HPD heat and hot water violations |
| `pluto_res3plus.csv` | 172,485 | PLUTO 26v2, lots with 3+ residential units |
| `hpd_registrations.csv` (18.5 MB) | 203,887 | Multiple Dwelling Registrations (the building universe) |
| `weather_centralpark.csv` (177 KB) | 3,572 | NOAA daily, station USW00094728, 2017-01-01 onward |

### Columns

**Complaints** (`ygpa-z7cr.csv`)
```
received_date, problem_id, complaint_id, building_id, bbl, bin, apartment,
minor_category, problem_code, problem_duplicate_flag, complaint_anonymous_flag,
unique_key, problem_status_date
```

**Violations** (`wvxf-dwi5.csv`)
```
violationid, buildingid, bbl, bin, apartment, inspectiondate, novissueddate,
ordernumber, currentstatus
```
Order numbers present: 666, 966, 674 (heat, Admin Code 27-2029); 670, 970 (hot water, 27-2031). The `class` column was not pulled; all these are Class C.

**PLUTO** (`pluto_res3plus.csv`)
```
bbl, cd, council, zipcode, bldgclass, numbldgs, numfloors, unitsres,
unitstotal, yearbuilt, yearalter1, bldgarea, latitude, longitude
```

**Weather** (`weather_centralpark.csv`)
```
STATION, DATE, AWND, SNOW, TAVG, TMAX, TMIN
```

### Verified value distributions (5,000-row sample, early-period rows)
- `minor_category`: ENTIRE BUILDING 68%, APARTMENT ONLY 32%
- `problem_code`: NO HEAT 60%, NO HEAT AND NO HOT WATER 25%, NO HOT WATER 15%, HEAT ON IN SUMMER 0.3%
- `problem_duplicate_flag`: Y 40%, N 60%
- `complaint_anonymous_flag`: Y 52%, N 48%

### Data traps (all confirmed)

1. **`TAVG` is entirely NaN.** Central Park does not report it. Compute `(TMAX + TMIN) / 2`.
2. **PLUTO `yearbuilt` min is 0** (missing coded as zero) and **both the 25th and 50th percentiles are 1900**, which is a dump value for "old, unknown." Treat 0 as missing; don't trust 1900 as a real year.
3. **`currentstatus` on violations is today's status, not the status at inspection.** Pure leakage. Use `inspectiondate` only.
4. **`bbl` and `bin` read as floats** in scientific notation (`3.013610e+09`). Cast to int64 before any join or every join silently fails.
5. **Violation `inspectiondate` runs back to 1968-12-06**, a data-entry error. Drop anything before 2010.
6. **Duplicate flag groups complaints.** Closing one complaint closes its whole group, so 47% of recent heat problems are flagged duplicate.
7. **64% of complaints are building-wide** (`apartment='BLDG'`), so "two or more distinct apartments" is only countable for a minority. Use distinct `complaint_id` within 48 hours.
8. **Rows are effectively complaints for heat.** 2,219,844 rows against 2,196,887 distinct `complaint_id` is a 1.01 ratio, so the problem-vs-complaint distinction barely matters here.
9. **`major_category` is not in the file.** The heat filter was applied server-side at download; every row is already HEAT/HOT WATER.
10. **HPD buildings and registration tables were last refreshed Aug 12, 2026** despite a "monthly" label.

### Join plan
BBL is the spine; complaints, violations and PLUTO all carry it. Registrations and violations also carry `buildingid`. Complaints carry `bin` for reaching DOB boiler data later. A BBL is a tax lot and can hold several buildings (PLUTO `numbldgs`), so a BBL-level label mixes buildings on multi-building lots.

### Not pulled (second tier)
DOB boiler defects `52dp-yji6`, boiler fuel type `f4rp-2kvy`, heat litigation `59kj-x8nc`, emergency repair orders `mdbu-nrqn`, Heat Sensors Program list `h4mf-f24e`, Open-Meteo live forecast feed.

---

## 4. Label design

**Filter first:** keep `problem_code` in (`NO HEAT`, `NO HEAT AND NO HOT WATER`). Drop hot-water-only (not temperature driven) and heat-on-in-summer (opposite problem). Keeps ~85% of rows.

**Two tiers:**
- **Primary target:** a complaint cluster, meaning two or more distinct `complaint_id` at one building within 48 hours.
- **Verified check:** an HPD heat violation (order 666, 966, 674) within 7 days. Clean but sparse, about 3% of complaints.

Report precision on both tiers. The second is what makes the claim credible.

---

## 5. Features

**Building history** (computed from prior seasons only, never the current one)
- Heat complaints last season, last two seasons
- Heat violations last season, last two seasons
- Days since last heat complaint, since last violation
- Whether chronic (5+ complaints in each of the last two seasons)

**Building attributes** (PLUTO)
- `yearbuilt` (0 → missing), `unitsres`, `numfloors`, `bldgarea`, `bldgclass`, `unitsres` per floor
- `cd` / `council` for geography

**Weather, mirroring the law**
- Hours below 55 °F between 6 AM and 10 PM
- Overnight minimum
- 3-day rolling minimum
- Day-over-day temperature drop
- Days since the season's first sub-55 °F day
- `AWND`, `SNOW`

**Row unit:** one building per cold spell.

---

## 6. Model and evaluation

**Model.** `HistGradientBoostingClassifier` (scikit-learn) or XGBoost. Both are preinstalled in IBM's container. Import the trained model into Snap ML for the platform story.

**Split.** Train 2018-19 through 2024-25 (seven seasons). Test on 2025-26 only, held out entirely. The first season (2017-18) is unusable as a target because lagged complaint history needs a full prior season.

**Metrics.** Precision and recall at k = 100, 500, 1,000 and 2,500 buildings per cold spell. Lift against three baselines:
1. Last season's complaint counts
2. Complaints in the previous 14 days
3. Last season's violation counts

**The credibility test.** 70% of chronic buildings stayed chronic for seven years, so "rank by last season's complaints" is a strong baseline. The model must show value in *timing* (which week, which buildings newly at risk), not in identifying the chronically bad ones.

**Leakage traps.** `currentstatus`, `problem_status_date`, closure fields, snapshot tables, duplicate rows on both sides of a split, and using observed temperatures as a stand-in for the forecast. Say the last one out loud in the pitch.

**Demo.** October is mild, so replay **February 7-9, 2026** (14,059 complaints from 6,725 buildings) beside the live forecast. Folium static HTML served by Flask on the instance's public IP.

---

## 7. LinuxONE / s390x constraints

**The instance.** Free Ubuntu guest on real s390x hardware at Marist. Public IPv4, key-only SSH as `linux1` with sudo. Only port 22 open until you add an iptables rule. Documented size is 2 cores / 4 GB / 50 GB; event code `SSF2026` grants more (amount unpublished).

**The trap.** Almost nothing in the compiled Python stack has s390x wheels on PyPI: numpy, pandas, scipy, scikit-learn, xgboost, lightgbm, pyarrow, duckdb, shapely, pyproj are all source-only. A bare `pip install pandas` means long compiles or outright failure.

**The fix.** Use IBM's prebuilt JupyterLab container (refreshed Oct 8, 2026), which already has pandas 3.0.6, scikit-learn 1.9.0, XGBoost 3.4.1, PyTorch 2.11, TensorFlow 2.18 on Python 3.12.

```
docker pull registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
docker run --network host --name notebook -v /home/linux1/shared:/home/ibm-user/shared -d <image>
```

Add only: `pip install --only-binary=:all: flask folium snapml`

**Do not:**
- Let pip upgrade numpy/pandas/scikit-learn/xgboost (triggers a source build)
- Use Streamlit (hard-requires pyarrow), DuckDB (unsupported on big-endian), Parquet, or geopandas
- Load a model pickled on x86 (big-endian bug that cost two past winning teams hours)

**Do:**
- Change the Jupyter token before opening port 38888 (default `Your_Token1` is in a public README)
- Persist iptables to `/etc/iptables/rules.v4` on Ubuntu (the lab README gives the RHEL path)
- Push to GitHub often; no backups, and instances have hung mid-event
- Run `grep -o nnpa /proc/cpuinfo` to check for the Telum accelerator; if absent, say so and show CPU numbers

**Platform story for the 15-point row.** Snap ML has a real cp312 s390x wheel, imports the trained XGBoost model, and with `tree_format='auto', verbose=True` reports whether the on-chip accelerator was detected. Measure events per second and p99 latency on the guest. No documented past winner has shown measured performance, so this is cheap differentiation. Do not claim Spyre, Secure Execution or Hyper Protect; none is exposed on the community cloud.

---

## 8. Pitch numbers (all sourced)

- **344,437** heat complaints in the 2025-26 season, up from 282,606 ([HPD](https://www.nyc.gov/site/hpd/services-and-information/heat-and-hot-water-information.page))
- Peak day **Feb 8, 2026: 6,144** complaints
- Nine sub-freezing days in late Jan 2026 produced **30,000+** complaints; only **1,381** became violations; **58%** were closed as duplicates ([City Limits](https://citylimits.org/how-nyc-closed-tens-of-thousands-of-no-heat-complaints-without-conducting-an-inspection/))
- About **3%** of heat complaints ever lead to a violation
- **901 of 1,283** chronic buildings stayed chronic across seven winters ([Comptroller 2025](https://comptroller.nyc.gov/reports/turn-up-the-heat-2025-update/))
- The Heat Sensors Program covers **50 buildings a year** (~250 enrolled), selected on past violations, no model, no weather
- **From Oct 1, 2026, HPD must attempt an inspection for every unit filing a non-anonymous heat complaint**, with 321-369 inspectors ([Gothamist](https://gothamist.com/news/mamdani-says-nyc-will-investigate-every-tenant-heat-complaint-starting-this-october)) — more workload, no way to prioritize it
- The Comptroller's first recommendation, still unimplemented, is data-driven prioritization of inspections
- Heat season Oct 1 to May 31; 68 °F required 6 AM-10 PM when below 55 °F outside; 62 °F overnight
- **Community impact (+5 bonus):** chronic buildings cluster in Bronx CDs 7, 4, 5, Manhattan 12, Brooklyn 14; the five districts with the most complaints average 90% people of color; the Jan 2022 Twin Parks fire that killed 17 started with a space heater in a building with prior heat complaints

---

## 9. Prior art — name it in the first minute

The building classifier is **not original**. Name these, then state the difference:

- **GotHeat** (Columbia hackathon, Oct 2015): building-level heat-complaint risk from 311 plus building attributes, ~77% accuracy
- **Kontokosta, Hong, Korsberg** (NYU, 2017): gradient boosting on building-level heat/hot water violations, 139,993 buildings, 75% accuracy ([arXiv 1710.02452](https://arxiv.org/abs/1710.02452))
- **Boxer, Hong, Kontokosta, Neill** (Annals of Applied Statistics, 2025): building-level estimate of *unreported* heat problems
- **IBM's own edX capstone DS0720EN**: 311 plus PLUTO for HPD, heat complaints as the answer, 10+ public GitHub replicas. An IBM judge may recognize this.
- **Localize.city** (2019): commercial predictive tool flagging 8,400+ at-risk buildings
- **HPD Heat Sensors Program**: rule-based selection of 50 buildings/year

**What is unclaimed:** a short-horizon, weather-forecast-triggered, building-level ranked inspection list, scored on failures caught per fixed inspection budget. Nothing public does this. That is the entire novelty claim, so it must be the whole pitch.

**Also differentiating:** prior models used no weather, no time dimension, often one borough, and reported accuracy inflated by class imbalance (one capstone write-up claims 98% when 94% of buildings were positive).

---

## 10. Honest limitations to state out loud

- The label is "who called 311", not "who was cold." Half of complaints are anonymous, 47% duplicate-flagged, and under-reporting is documented at building level by the NYU work.
- Backtests use observed temperature, which is a perfect forecast. Live use runs on a real forecast and will be slightly worse.
- Display nothing below building level. The raw HPD table contains apartment numbers and anonymous flags.
- A "quiet but risky" list drawn from physical risk factors with low complaint history partly addresses the reporting bias.

---

## 11. Build budget (24 hours)

| Stage | Hours |
|---|---|
| Environment and data onto the instance | 3 |
| Label and features | 6 |
| Baseline and model | 5 |
| Evaluation at fixed budgets | 3 |
| Map, video, pitch | 4 |
| Slack | 3 |

**Highest-value actions, in order:** honest precision-at-k against the last-season baseline; naming the prior art then the difference; a replayed cold-snap event loop with measured latency; a map on the public IP shown in the video with `uname -m` returning `s390x`; the Bronx community-impact narrative tied to the Oct 1 rule; a public documented repo.
