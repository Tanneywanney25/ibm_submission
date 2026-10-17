# Team split — IBM Z Datathon, Oct 17, 2026

Five workstreams, one per person. Data lives in `Data_IBMZ/`:
- `Data_IBMZ/HeatAhead_weather_2017_onward/` — `days.csv`, `buildings.csv` (the two EDA master tables)
- `Data_IBMZ/raw/` — raw files: `ygpa-z7cr.csv` (complaints), `wvxf-dwi5.csv` (violations), `pluto_res3plus.csv`, `hpd_registrations.csv`, `noaa_daily_centralpark.csv`

---

## 1. Analysis — days + buildings (suggested: Emerson)

Work from `days.csv` and `buildings.csv` in `HeatAhead_weather_2017_onward/`.

- Weather bands on `days` (Frigid <20 / Freezing 20-31 / Cold 32-44 / Mild 45+ on TMIN); count days per band, widen Frigid to <25 if thin
- Reaction rates by building type × weather band (size, era, altered) — the heatmap
- Cold-sensitivity multipliers (rate vs mild-day rate) → chronic vs cold-triggered table
- Per-building history rates by band (how often this building complained on past frigid days)

Needs the raw complaints file too (`raw/ygpa-z7cr.csv`) for which building complained on which day. Deliverables: heatmap figure, chronic-vs-cold-triggered table, `bldg_history` table for the model.

## 2. Analysis — second thread

A parallel analysis stream from the raw files, in rough priority:

- Violation tier: which complaint clusters became verified heat violations (orders 666/966/674) within 7 days — the credibility check for the label
- Geography: complaints per building by community district / council; the Bronx CD 7/4/5 community-impact numbers for the pitch
- The "forecast-only" group: buildings with zero mild-weather complaints that react in frigid weather
- If time: pull a second-tier dataset (boiler defects `52dp-yji6` or fuel type `f4rp-2kvy`) and join on BIN

Deliverables: violation-confirmation rate, CD-level map data, one or two pitch numbers.

## 3. Website / frontend

- Folium (or Leaflet) map of the ranked inspection list, served by Flask on the LinuxONE public IP
- Build early against `buildings.csv` with placeholder scores; swap in real model scores when ready
- Two views: most likely to fail, most tenants at risk (probability × apartments)
- Replay panel: Feb 7-9, 2026 cold snap beside the live Open-Meteo 16-day forecast
- Building-level only — never show apartment numbers
- Also owns LinuxONE setup: docker container, change Jupyter token, open ports, persist iptables, screenshot `uname -m` and the `nnpa` check

## 4. Slideshow / video

- Slide deck following the pitch order: problem (344k complaints, Oct 1 inspect-every-unit rule) → prior art named → our difference (forecast-triggered ranking) → type × weather findings → precision@k vs baselines → LinuxONE demo → limitations
- 3-minute video: must show the LinuxONE instance and the model running
- GitHub repo: team number in title, README, data source + open-source library links (required), the four project md files as `/docs`
- Confirm the submission deadline on Hack2skill/Discord first thing
- Submit with a 2-hour buffer

## 5. Model — P(heat failure | building, weather)

The core deliverable: given the day's weather, the probability each building loses heat.

- Build the label from `raw/ygpa-z7cr.csv`: 2+ distinct `complaint_id` at a building within 48 hours (heat-only: `NO HEAT`, `NO HEAT AND NO HOT WATER`)
- Panel: all positives + 2× sampled negatives; join building features and day weather
- Features: prior-season complaint/violation history, per-band history rates (from stream 1), `unitsres`, `yearbuilt`, `altered`, `numfloors`, `cd`, same-day TMIN, TMAX, tmin_lag1, 3-day rolling min, day-over-day drop, SNOW, AWND, wday
- Train 2018-19 → 2024-25, test 2025-26 only
- XGBoost / HistGradientBoostingClassifier on LinuxONE; import into Snap ML, measure events/sec and p99 latency
- Evaluate precision/recall@k (100/500/1000/2500) vs three baselines: last season's complaints, last-14-day complaints, last season's violations

## Traps (everyone)

- Cast `bbl`/`bin` to int64 before every join — they read as floats
- History features from prior seasons only; never use `currentstatus`, `problem_status_date`, or anything post-event
- Drop violation `inspectiondate` before 2010; the six holiday bad days are already out of `days.csv`
- Never pickle a model on x86 and load on s390x — train on the instance
- Don't let pip upgrade numpy/pandas/scikit-learn/xgboost on LinuxONE

## Sync points

- Hour 1: agree the panel CSV schema (streams 1 and 5)
- Hour 7: history tables handed from stream 1 → stream 5
- Hour 12: precision@k review, whole team — set the pitch framing
- Hour 17: feature freeze; everything after is video and docs
