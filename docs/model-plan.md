# Stream 5 — Model plan: P(heat failure | building, weather)

Owner: Emerson. Everything in Python/pandas so the same code runs on the laptop and on LinuxONE. Work in order; each phase has a checkpoint and a fallback.

Data paths:
- `Data_IBMZ/raw/ygpa-z7cr.csv` — complaints (361 MB, read in chunks)
- `Data_IBMZ/raw/wvxf-dwi5.csv` — violations
- `Data_IBMZ/raw/pluto_res3plus.csv` — building features
- `Data_IBMZ/HeatAhead_weather_2017_onward/days.csv` — day-level weather (holidays already dropped)
- `Data_IBMZ/HeatAhead_weather_2017_onward/buildings.csv` — building master table

---

## Phase 0 — Load and clean (30 min)

```python
import pandas as pd
import numpy as np

usecols = ["received_date", "complaint_id", "bbl", "problem_code",
           "problem_duplicate_flag"]
heat = pd.concat(
    pd.read_csv("Data_IBMZ/raw/ygpa-z7cr.csv", usecols=usecols,
                chunksize=500_000, low_memory=False),
    ignore_index=True)

heat = heat[heat.problem_code.isin(["NO HEAT", "NO HEAT AND NO HOT WATER"])]
heat["bbl"] = heat["bbl"].astype(float).astype("int64")   # floats kill joins
heat["day"] = pd.to_datetime(heat["received_date"]).dt.normalize()

days = pd.read_csv(".../days.csv", parse_dates=["day"])
buildings = pd.read_csv(".../buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")

viol = pd.read_csv("Data_IBMZ/raw/wvxf-dwi5.csv", low_memory=False)
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])]  # heat only
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])
viol = viol[viol.inspectiondate >= "2010-01-01"]          # 1968 garbage out
```

**Checkpoint:** row counts match the inventory (~1.89M heat rows after filter, 172,485 buildings). Restrict `heat` to `bbl.isin(buildings.bbl)`.

Define heat seasons once:

```python
def season(d):
    # Oct-May season named by its starting year: Dec 2022 and Feb 2023 -> 2022
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)
```

---

## Phase 1 — Label (1 hr)

Primary label: **2+ distinct complaints at a building within 48h** (day d + day d+1).

```python
bd = (heat.groupby(["bbl", "day"])["complaint_id"]
          .nunique().rename("n").reset_index())

nxt = bd.copy(); nxt["day"] -= pd.Timedelta(days=1); nxt = nxt.rename(columns={"n": "n_next"})
lab = bd.merge(nxt, on=["bbl", "day"], how="outer").fillna(0)
lab["failed48"] = (lab.n + lab.n_next) >= 2
```

**Check the positive rate immediately.** Expect roughly 100-200k positives over 9 seasons. If under ~50k, fall back to `n >= 1` (single complaint that day) — decide now, not at hour 15.

Verified tier (report alongside, never train on): heat violation within 7 days of the label day.

```python
v = viol[["bbl", "inspectiondate"]].sort_values("inspectiondate")
pos = lab[lab.failed48].sort_values("day")
pos = pd.merge_asof(pos, v.rename(columns={"inspectiondate": "vdate"}),
                    left_on="day", right_on="vdate", by="bbl",
                    direction="forward", tolerance=pd.Timedelta(days=7))
pos["verified"] = pos.vdate.notna()
```

---

## Phase 2 — Panel (1.5 hr)

All positives + 2× sampled negatives, heat-season days only.

```python
rng = np.random.default_rng(42)
hd = days[days.heat_season]["day"]
neg = pd.DataFrame({
    "bbl": rng.choice(buildings.bbl, size=len(pos)*2),
    "day": rng.choice(hd, size=len(pos)*2),
}).drop_duplicates()
neg = neg.merge(pos[["bbl", "day"]], on=["bbl", "day"],
                how="left", indicator=True)
neg = neg[neg._merge == "left_only"].drop(columns="_merge")
neg["failed48"] = False; pos["failed48"] = True

panel = pd.concat([pos[["bbl", "day", "failed48"]], neg], ignore_index=True)
panel["season"] = season(panel.day)
```

Caveat to keep in the README: sampled negatives inflate the apparent base rate — fine for ranking, never quote panel percentages as real-world rates.

---

## Phase 3 — Features (2.5 hr, the fiddly part)

**The one rule: every history feature uses data from seasons strictly before the row's season.** Nothing from the row's own season, ever.

```python
heat["season"] = season(heat.day)
sc = (heat.groupby(["bbl", "season"])["complaint_id"]
          .nunique().rename("c").reset_index())

# complaints last season / last two seasons
sc1 = sc.assign(season=sc.season + 1).rename(columns={"c": "c_last1"})
sc2 = sc.assign(season=sc.season + 2).rename(columns={"c": "c_last2_part"})
panel = panel.merge(sc1, on=["bbl", "season"], how="left")
panel = panel.merge(sc2, on=["bbl", "season"], how="left")
panel["c_last2"] = panel.c_last1.fillna(0) + panel.c_last2_part.fillna(0)

# same pattern for violations (use inspectiondate's season)
# chronic flag: c >= 5 in each of the two prior seasons
```

Per-band history rates (hand-off from stream 1, or compute here): for each building, share of prior-season frigid/freezing/cold/mild days with a complaint. To keep it leak-free per row, compute cumulative counts by season and shift by one season — same trick as above. If this runs long, ship with season-count features only and add band rates in v2.

Days-since-last-complaint (as of the row's day, prior seasons only — simplest honest version: days since end of the last prior season with a complaint; or skip it in v1).

Building features: merge `buildings[["bbl","unitsres","yearbuilt","altered","numfloors","bldgarea","cd"]]`; `yearbuilt` 0 → NaN.

Weather features from `days`:

```python
days = days.sort_values("day")
days["tmin_roll3"] = days.TMIN.rolling(3).min()
days["tmin_drop"]  = days.TMIN.diff()
panel = panel.merge(days[["day","TMIN","TMAX","tmin_lag1","tmin_roll3",
                          "tmin_drop","SNOW","AWND","wday"]], on="day")
```

**Banned columns (leakage):** `currentstatus`, `problem_status_date`, `n`/`n_next` from the label, anything dated after the row's day, any count that includes the row's own season.

**Checkpoint:** write `panel.csv`. Sanity scan: a 2025 row must have `c_last1` = its 2024-25 count, and zero contribution from 2025-26.

---

## Phase 4 — Train (1 hr, on LinuxONE)

```python
from xgboost import XGBClassifier

feats = ["c_last1","c_last2","v_last1","chronic","unitsres","yearbuilt",
         "altered","numfloors","bldgarea","cd","TMIN","TMAX","tmin_lag1",
         "tmin_roll3","tmin_drop","SNOW","AWND","wday_num"]

train = panel[(panel.season >= 2018) & (panel.season <= 2024)]
test  = panel[panel.season == 2025]

m = XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                  subsample=0.8, colsample_bytree=0.8,
                  eval_metric="aucpr", tree_method="hist", n_jobs=-1)
m.fit(train[feats], train.failed48)
```

No tuning beyond one or two depth/learning-rate tries — feature quality beats hyperparameters here. Fallback if XGBoost misbehaves on s390x: `sklearn.ensemble.HistGradientBoostingClassifier`, same interface, preinstalled.

Save with `m.save_model("heat_model.json")` (portable), never pickle.

---

## Phase 5 — Evaluation (2 hr) — the number that wins or loses

Precision@k is scored on the **full building universe**, not the panel. For each test cold day (say every heat-season day with TMIN < 32 in 2025-26):

```python
# score matrix: 172,485 buildings x that day's weather
X = buildings_feats.copy()              # history feats as of end of 2024-25
for c in ["TMIN","TMAX","tmin_lag1","tmin_roll3","tmin_drop","SNOW","AWND","wday_num"]:
    X[c] = day_weather[c]
X["score"] = m.predict_proba(X[feats])[:, 1]
```

For each day and each k in (100, 500, 1000, 2500): take top-k by score, measure
- precision: share of the k that had `failed48` true that day
- recall/coverage: share of that day's failures caught
- same two numbers on the verified-violation tier

Baselines, identical protocol:
1. rank by 2024-25 complaint count
2. rank by complaints in the trailing 14 days (rolling — recompute per day)
3. rank by 2024-25 heat violations

Also report the **new-to-list** cut: precision among top-k buildings *not* in the baseline's top-k. This is where the model has to win; if headline numbers only tie the baseline, this is the pitch.

Output: one tidy CSV `results_precision_at_k.csv` (day, k, method, precision, recall, verified_precision) — feeds the slides and the site directly.

---

## Phase 6 — Snap ML + latency (1 hr, LinuxONE)

```python
from snapml import BoostingMachineClassifier  # or snapml's import-from-xgboost path
# import the trained model with tree_format="auto", verbose=True
# -> logs whether the on-chip accelerator (nnpa/zdnn) was detected
```

Measure on the guest: batch scoring of all 172,485 buildings (events/sec) and single-row p99 latency over ~10k calls (`time.perf_counter`). Record alongside `grep -o nnpa /proc/cpuinfo` and `uname -m` screenshots. If snapml won't install or import, measure the same numbers with plain XGBoost and say so honestly — measured numbers at all are the differentiator.

Hand-offs out: `heat_model.json` + per-building scores CSV → frontend (stream 3); `results_precision_at_k.csv` + feature importances → slides (stream 4).

---

## Time budget and cut lines

| Phase | Hours | Cut if slipping |
|---|---|---|
| 0 Load/clean | 0.5 | — |
| 1 Label | 1 | verified tier → report-only, compute late |
| 2 Panel | 1.5 | — |
| 3 Features | 2.5 | band-rate features; days-since-last |
| 4 Train | 1 | hyperparameter tries |
| 5 Eval | 2 | k=100/2500 (keep 500 and 1000); fewer test days (every cold day → 10 coldest) |
| 6 Snap ML | 1 | accelerator story → plain CPU numbers |

Total ~9.5 hr. Absolute floor for a submittable project: phases 0-5 with k=500 only vs baseline 1.
