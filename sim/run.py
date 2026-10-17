"""T12 - the inspector dispatch simulator: prediction -> policy.

Replays the real 2025-26 complaint stream day by day under a fixed inspection
capacity and three dispatch policies, and measures what the city cares about:
confirmed violations, time-to-inspection, cold-household-days.

Grounding (every parameter measured from this repo's own data):
- Demand: actual building-day complaints (model/out/building_day_counts.csv).
- Outcome: P(violation | inspected) proportional to stream 2's measured 7-day
  confirmation rates by cluster tier (1 / 2+ / 3+ complaints in 48h) - NEVER
  from our model (circularity guard). The proportionality constant and the
  daily capacity are calibrated so FCFS reproduces the REAL season total
  (10,886 heat violations) - calibration is the simulator's validation.
- Because outcomes do not feed back into the queue, waits are deterministic
  per policy and total violations are a Poisson-binomial sum: we report exact
  expectations with analytic 95% CIs (no Monte Carlo noise).

Policies: FCFS (status quo) | last-season complaint count | HeatAhead
(frozen M13 per-spell scores during spells; last-season before the first).

Run (instance container):  python sim/run.py
Writes: sim/out/policy_results.csv, sim/out/cumulative_violations.csv
"""

import glob
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from common import OUT  # noqa: E402

SIM = ROOT / "sim/out"
SIM.mkdir(parents=True, exist_ok=True)
SEASON_START, SEASON_END = pd.Timestamp("2025-10-01"), pd.Timestamp("2026-05-31")
REAL_VIOLATIONS = 10886            # measured: 2025-26 heat violations (docs)
TIER_RATE = {1: 0.0478, 2: 0.0893, 3: 0.1061}   # stream 2 7-day confirmation
EXPIRE = 14                        # uninspected cases lapse (sensitivity below)

# ---------------- demand: real building-day complaints, with 48h tier
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
bd = bd[(bd.day >= SEASON_START) & (bd.day <= SEASON_END)]
nxt = bd.rename(columns={"n": "n_next"}).copy()
nxt["day"] -= pd.Timedelta(days=1)
cases = bd.merge(nxt[["bbl", "day", "n_next"]], on=["bbl", "day"], how="left").fillna(0)
cases["c48"] = cases.n + cases.n_next
cases["tier"] = np.where(cases.c48 >= 3, 3, np.where(cases.c48 >= 2, 2, 1))
cases["p_rel"] = cases.tier.map(TIER_RATE)
cases = cases.sort_values("day").reset_index(drop=True)
print(f"{len(cases):,} complaint-day cases in the 2025-26 heat season")

units = pd.read_csv(ROOT / "data/buildings.csv", usecols=["bbl", "unitsres"])
units["bbl"] = units.bbl.astype(float).astype("int64")
UNITS = dict(zip(units.bbl, units.unitsres.clip(lower=1)))

# ---------------- policy priorities
# last season complaint count (policy b, and HeatAhead's pre-first-spell fallback)
prev = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
prev = prev[(prev.day >= "2024-10-01") & (prev.day <= "2025-05-31")]
LAST = prev.groupby("bbl")["n"].sum().to_dict()

# M13 per-spell scores (frozen members over the 8 test snapshots)
import xgboost as xgb  # noqa: E402
nodes = np.load(OUT / "graph/nodes.npz")
BBLS = nodes["bbls"]
members = [xgb.XGBClassifier() for _ in range(5)]
for i, m in enumerate(members):
    m.load_model(OUT / f"heat_model_spell_s{i}.json")
SPELLS = []                        # (start, scores dict bbl->score)
for p in sorted(glob.glob(str(OUT / "graph/spell_2025-*.npz")) +
                glob.glob(str(OUT / "graph/spell_2026-*.npz"))):
    z = np.load(p)
    if int(z["season"]) != 2025:
        continue
    X = z["X"]
    sc = np.mean([m.predict_proba(X)[:, 1] for m in members], axis=0)
    start = pd.Timestamp(Path(p).stem.split("_")[1])
    SPELLS.append((start, dict(zip(BBLS, sc))))
SPELLS.sort()
print(f"{len(SPELLS)} spell score snapshots for the HeatAhead policy")


def heat_priority(day):
    """Most recent spell snapshot at or before `day`; last-season before any."""
    live = [s for s in SPELLS if s[0] <= day]
    return live[-1][1] if live else None


# ---------------- the engine (deterministic queue; analytic outcomes)
def simulate(policy, capacity, kscale, expire=EXPIRE):
    backlog = {}                   # bbl -> dict(arrival, tier, p_rel)
    arrivals = cases.groupby("day")
    days = pd.date_range(SEASON_START, SEASON_END)
    stats = dict(viol_mean=0.0, viol_var=0.0, waits=[], waits_fail=[],
                 expired_fail=0, cold_days=0.0, inspected=0,
                 expired=0, cum=[], daily=[])
    for day in days:
        if day in arrivals.groups:
            for r in arrivals.get_group(day).itertuples():
                b = backlog.get(r.bbl)
                if b is None or r.tier > b["tier"]:
                    backlog[r.bbl] = dict(arrival=b["arrival"] if b else day,
                                          tier=r.tier, p_rel=r.p_rel)
        # expire stale cases (they waited the full window, uninspected)
        for b in [k for k, v in backlog.items() if (day - v["arrival"]).days > expire]:
            v = backlog.pop(b)
            stats["expired"] += 1
            if v["tier"] >= 2:
                stats["cold_days"] += UNITS.get(b, 3) * expire
                stats["expired_fail"] += 1
                stats["waits_fail"].append(expire)   # expiry counts as a full wait
        # dispatch today's capacity
        if backlog:
            keys = list(backlog.keys())
            if policy == "fcfs":
                order = sorted(keys, key=lambda b: (backlog[b]["arrival"], b))
            elif policy == "last_season":
                order = sorted(keys, key=lambda b: (-LAST.get(b, 0), b))
            else:                   # heatahead
                pr = heat_priority(day)
                order = (sorted(keys, key=lambda b: (-pr.get(b, -1.0), b)) if pr else
                         sorted(keys, key=lambda b: (-LAST.get(b, 0), b)))
            day_viol = 0.0
            for b in order[:capacity]:
                v = backlog.pop(b)
                wait = (day - v["arrival"]).days
                p = min(1.0, kscale * v["p_rel"])
                stats["viol_mean"] += p
                day_viol += p
                stats["viol_var"] += p * (1 - p)
                stats["waits"].append(wait)
                stats["inspected"] += 1
                if v["tier"] >= 2:
                    stats["cold_days"] += UNITS.get(b, 3) * wait
                    stats["waits_fail"].append(wait)
        else:
            day_viol = 0.0
        ncompl = int(arrivals.get_group(day).n.sum()) if day in arrivals.groups else 0
        stats["daily"].append((day, ncompl, day_viol))
        stats["cum"].append((day, stats["viol_mean"]))
    w = np.array(stats["waits"])
    wf = np.array(stats["waits_fail"])     # failing buildings, expiries included
    return dict(policy=policy,
                violations=round(stats["viol_mean"], 1),
                viol_ci=round(1.96 * np.sqrt(stats["viol_var"]), 1),
                median_wait=float(np.median(w)) if len(w) else np.nan,
                mean_wait=round(float(w.mean()), 2) if len(w) else np.nan,
                fail_median_wait=float(np.median(wf)) if len(wf) else np.nan,
                fail_mean_wait=round(float(wf.mean()), 2) if len(wf) else np.nan,
                cold_household_days=int(stats["cold_days"]),
                inspected=stats["inspected"], expired=stats["expired"],
                expired_fail=stats["expired_fail"]), stats["cum"], stats["daily"]


# ---------------- calibrate (capacity, kscale) so FCFS reproduces reality:
# BOTH the season total AND the measured congestion (stream 2: median lag
# grows to ~3-4 days in the busy stretches; the system visibly saturates).
REAL_BUSY_LAG = 3.5                 # stream 2: median complaint->inspection lag
print("calibrating FCFS to the real total "
      f"({REAL_VIOLATIONS:,} violations) AND the measured ~{REAL_BUSY_LAG}-day lag...")
best = None
for capacity in (300, 400, 500, 600, 700, 800, 1000, 1200):
    r, _, _ = simulate("fcfs", capacity, 1.0)
    k = REAL_VIOLATIONS / r["violations"]       # linear in kscale by construction
    if k * TIER_RATE[3] > 1:                    # P(viol|insp) must stay a probability
        continue
    lag_err = abs(r["mean_wait"] - REAL_BUSY_LAG) / REAL_BUSY_LAG
    cand = (lag_err, abs(np.log(k)), capacity, k, r["mean_wait"])
    print(f"  capacity {capacity:4d}: mean wait {r['mean_wait']:.2f}d, k -> {k:.2f}")
    if best is None or cand < best:
        best = cand
_, _, CAP, K, W = best
print(f"calibrated: capacity {CAP}/day (FCFS mean wait {W:.2f}d ~ measured "
      f"{REAL_BUSY_LAG}d), outcome scale k={K:.2f} "
      f"(tier P(viol|insp): {[round(K*v,3) for v in TIER_RATE.values()]})")

# ---------------- run the three policies under identical calibration
rows, cums, dailies = [], {}, {}
for pol in ("fcfs", "last_season", "heatahead"):
    r, cum, daily = simulate(pol, CAP, K)
    rows.append(r)
    cums[pol] = cum
    dailies[pol] = daily
    print(r)

res = pd.DataFrame(rows)
res.to_csv(SIM / "policy_results.csv", index=False)
cc = pd.DataFrame({p: pd.Series({d: v for d, v in cums[p]}) for p in cums})
cc.index.name = "day"
cc.to_csv(SIM / "cumulative_violations.csv")

f, l, h = [res[res.policy == p].iloc[0] for p in ("fcfs", "last_season", "heatahead")]
print("\n=== THE IMPACT NUMBER ===")
print(f"Same {CAP} inspections/day, same winter:")
print(f"  confirmed violations: FCFS {f.violations:,.0f} -> HeatAhead "
      f"{h.violations:,.0f}  ({(h.violations/f.violations-1)*100:+.1f}%)")
print(f"  median wait (days):   FCFS {f.median_wait:.0f} -> HeatAhead {h.median_wait:.0f}")
print(f"  cold-household-days:  FCFS {f.cold_household_days:,} -> HeatAhead "
      f"{h.cold_household_days:,}  ({(h.cold_household_days/f.cold_household_days-1)*100:+.1f}%)")
print(f"  (last-season policy: {l.violations:,.0f} violations, "
      f"median wait {l.median_wait:.0f})")
print(f"  waits for FAILING buildings, expiries counted as {EXPIRE}d: "
      f"median FCFS {f.fail_median_wait:.0f}d -> HeatAhead {h.fail_median_wait:.0f}d "
      f"(mean {f.fail_mean_wait:.2f} -> {h.fail_mean_wait:.2f})")
print(f"  expired uninspected cases: FCFS {f.expired:,} ({f.expired_fail:,} failing) -> "
      f"HeatAhead {h.expired:,} ({h.expired_fail:,} failing)")

# ---------------- verification 1: does FCFS reproduce the measured saturation SHAPE?
# Stream 2 measured yield per 100 complaints dropping roughly one-third on 4k+
# complaint days. The sim must show the same congestion, not just the total.
dd = pd.DataFrame(dailies["fcfs"], columns=["day", "complaints", "viol"])
heavy = dd[dd.complaints >= 4000]
mod = dd[(dd.complaints >= 500) & (dd.complaints < 2000)]
y_h = 100 * heavy.viol.sum() / max(heavy.complaints.sum(), 1)
y_m = 100 * mod.viol.sum() / max(mod.complaints.sum(), 1)
print(f"\nsaturation shape (FCFS): {y_m:.2f} violations/100 complaints on moderate "
      f"days -> {y_h:.2f} on 4k+ days ({(y_h / y_m - 1) * 100:+.0f}%; "
      f"stream 2 measured about -32%)")

# ---------------- verification 2: sensitivity grid (same outcome model K;
# capacity +/-15% and expiry window 7/14/28 - does the policy ranking hold?)
if "--sensitivity" in sys.argv:
    print("\n--- sensitivity: HeatAhead vs FCFS across capacity x expiry ---")
    sens = []
    for cap in (600, 700, 800):
        for exp in (7, 14, 28):
            rf, _, _ = simulate("fcfs", cap, K, expire=exp)
            rh, _, _ = simulate("heatahead", cap, K, expire=exp)
            dv = (rh["violations"] / rf["violations"] - 1) * 100
            dc = (rh["cold_household_days"] / max(rf["cold_household_days"], 1) - 1) * 100
            sens.append(dict(capacity=cap, expire=exp,
                             fcfs_viol=rf["violations"], ha_viol=rh["violations"],
                             d_viol_pct=round(dv, 1), d_cold_pct=round(dc, 1),
                             fcfs_cold=rf["cold_household_days"],
                             ha_cold=rh["cold_household_days"],
                             ha_expired=rh["expired"]))
            print(f"  cap {cap} expire {exp:2d}: violations {dv:+5.1f}%, "
                  f"cold-household-days {dc:+5.1f}%, HA expired {rh['expired']:,}")
    pd.DataFrame(sens).to_csv(SIM / "sensitivity.csv", index=False)
    print("wrote sim/out/sensitivity.csv")
