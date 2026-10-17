# T12 — The inspector policy simulator: from prediction to policy

**Goal:** the "so what" machine. A discrete-event simulation of HPD's
inspector capacity over the replayed 2025-26 winter under three dispatch
policies — today's first-come-first-served, last-season targeting, and our
ranked queue — measuring what the city actually cares about: verified
violations caught, time-to-inspection, and cold-household-days averted.
Operations research on top of the ML; produces the single most quotable
number of the project.

## Grounding (every parameter from our own measured data — cite in code)

- Capacity: 321–369 inspectors (brief §8); inspections/day calibrated so the
  SIMULATED baseline reproduces stream 2's measured reality (36.8 violations
  per 100 complaints on moderate days falling to 25.1 on 4k+ days, median lag
  3→4 days). Calibration IS the validation of the simulator.
- Demand: the real 2025-26 complaint stream (building_day_counts, 71 cold
  days); violation propensity per inspected building from its cluster tier
  (stream 2's confirmation table) — NOT from our model, to avoid circularity.
- Cold-household-days: units × days from first failure signal to inspection
  (state the proxy honestly: inspection ≈ intervention).

## Method

1. `sim/engine.py`: day-step simulation. Queue of candidate buildings per day;
   policy orders the queue; k = capacity × productivity inspected; outcomes
   drawn from measured confirmation rates by tier; backlog carries with decay
   (complaint abandonment after 14 days, sensitivity-checked).
2. Policies: (a) FCFS on complaint arrival (status quo), (b) rank by last
   season's complaints, (c) our calibrated queue (M2 scores, re-ranked per
   day), (d) stretch: M8 for the enforcement objective.
3. **Uncertainty:** 500 Monte Carlo reps per policy; report medians + 90%
   intervals (T7's bootstrap style).
4. Sensitivity: capacity ±15%, productivity ±20%, abandonment 7/14/28d —
   does the policy ranking ever flip? (That's the robustness claim.)

## Deliverables

- `sim/engine.py`, `sim/run.py` → `sim/out/policy_results.csv`
- Headline sentence template filled: "Same 350 inspectors, same winter:
  dispatching by HeatAhead finds X% more verified violations and cuts median
  time-to-inspection from A to B days (90% interval ...)"
- One figure: cumulative verified violations over the winter, three lines
- Method note in docs/experiments-report.md (incl. the circularity guard)

## Acceptance

- [ ] Baseline policy reproduces stream 2's measured saturation numbers ±10%
- [ ] Violation propensity comes from measured confirmation rates, not M1/M2
- [ ] Monte Carlo intervals on every reported number
- [ ] Policy ranking stable across the sensitivity grid (or flips reported)
- [ ] Every parameter's source cited in-code to a repo file

**Effort ~5h. Depends on:** stream 2 tables (done), M2 scores (done).
**Feeds:** the deck's closing number; the Comptroller framing.
