# HeatAhead — the complete submission story

Everything the team built, consolidated: one section per workstream, every headline
number with its source file. This is the master document — slides, video and Q&A all
draw from here. Written Oct 18, 2026.

---

## 1. The problem and the claim

NYC heat season law: 68°F daytime when it's below 55°F outside, Oct 1 – May 31.
Last winter tenants filed **300k+ heat complaints**; the peak day (Feb 8, 2026) alone
had 5,751. Since **Oct 1, 2026** HPD must attempt an inspection for every
non-anonymous heat complaint — with 321–369 inspectors. The Comptroller's #1
recommendation, still unimplemented: data-driven prioritization.

**Claim:** a short-horizon, weather-forecast-triggered, building-level ranked
inspection list, scored on failures caught per fixed inspection budget. Prior work
(GotHeat 2015; Kontokosta et al. 2017; IBM's own edX capstone; Localize.city) built
building-level classifiers — none is forecast-triggered, none scores per inspection
budget, none ships calibrated probabilities. That's the novelty, and we name the
prior art first (brief §9).

## 2. Data (all public, all linked in README)

2.2M HPD complaint rows (2017–2026) · 223k violations · PLUTO (172,485 lots with 3+
units) · registrations + registration contacts (landlords) · DOB boiler inspections
+ fuel · NOAA daily + Open-Meteo hourly weather · **archived 24/48-hour forecasts**
(the honesty ingredient: backtests can use what was actually forecast, measured at
~2°F error at 48h).

Traps found and handled: BBLs read as floats (silently break joins); `TAVG` all-NaN;
`yearbuilt=1900` is a placeholder; `currentstatus` is leakage; violations before 2010
are data-entry noise; 45% duplicate-flagged and 50% anonymous complaints → count
distinct `complaint_id` only.

## 3. Stream 1 — weather bands and building reactions (`analysis/`)

Defined the four TMIN bands used everywhere: **Frigid <20°F, Freezing 20–31, Cold
32–44, Mild ≥45**. Produced per-era, per-size and per-alteration reaction-rate
heatmaps and the chronic vs cold-triggered split (complaint-day rates per band, zero
days included in denominators). Outputs: `analysis/analysis_outputs/` (heatmaps,
`group_cold_sensitivity.csv`, band-day tables). These band definitions became model
features (`rate_frigid2/freezing2/cold2`) — stream 1's hand-off landed inside the
model as designed.

## 4. Stream 2 — label credibility, geography, Forecast-Only group (`task 2/`)

Run end-to-end on the z17 guest (hardware log included). Highlights from
`task 2/deliverables/02_stream2_report.md`:

- **The label means something:** 2+ complaint clusters are confirmed by a heat
  violation within 7 days at **8.9%** vs 4.8% for single complaints — a 1.87×
  multiplier, stable across training (1.88×) and holdout (1.83×). On frigid days
  confirmation hits 10–15%; on mild days 3.8%.
- **Inspector saturation, measured:** on the worst days (4,000+ complaints),
  violations inspected per 100 complaints fall by a third (36.8 → 25.1) and lag grows
  from 3 to 4 days — the system saturates exactly when prioritization matters most.
- **Community impact:** Bronx CDs 7, 4, 5 = 4.6% of the city's units, **14.6% of its
  2025-26 heat complaints**, 3.9× the rest-of-city rate, ~438,000 tenants.
  Map-ready: `cd_level_map_data.csv`, `fig_bronx_cd_impact.png`.
- **The Forecast-Only group:** 18,814 buildings that in seven winters never
  complained on a mild or cold day but did on freezing/frigid days — 11.2× frigid-vs-
  mild reaction ratio. These are the buildings only a weather-triggered system sees.

## 5. Stream 5 — the model (`model/`, full arc in `docs/model-iterations.md`)

One row = one building on the eve of a cold day. Label: 2+ distinct complaints in
48h. 31 features in four families: building (PLUTO + boiler + landlord portfolio),
history (two prior seasons + band reaction rates + days-since), live activity
(trailing 2/7/14/30-day counts, whole-building outages, same-block neighbor
complaints), weather (TMIN/TMAX, rolling min, drop, snow, wind, days into season).
Every feature strictly pre-dates the ranking moment; the build asserts it.

Five iterations: 65.7% → 67.8% → 67.7% → 68.7% → **69.1%** precision@100 (exact 48h,
71 held-out cold days) vs 61.7% baseline. XGBoost + sklearn ensemble on LinuxONE.

**The ladder (top-100):** 69.1% exact 48h → **86.1% during the spell** → 96.6%
within 30 days → **99% that winter** (preseason list; 95.4% @1000). Autopsy: only
1–7 of any spell's top-100 are truly clean at 30 days — building selection is ~95%+
right; the 48h clock is strict because call-timing is noise.

**Validation: 6-fold forward-chaining CV** — for each winter 2020-21…2025-26, train
only on earlier winters, test, roll forward. **6 of 6 won** (mean 0.673 vs 0.634).
No per-fold tuning. (Classic leave-one-out would train on the future — invalid for
time series; we say so.)

**Calibration:** isotonic, fit and verified on disjoint held-out halves, nine
splits including mild→coldest. When the model says 15%, 15.2% fail. Displayed
probabilities cap at 99%.

**Per-building winter risk (`09`):** P(loses heat at least once this winter) for
all 63,727 ranked buildings, verified bin-by-bin on 2025-26 (predicted 89% → actual
89.8%). For 2026-27: **3,801 buildings at ≥80%**, 8,932 at ≥50%. The city's Heat
Sensors Program watches ~250 buildings; this names thousands, with receipts.

## 6. IBM Z (the 15-point row) — measured, not claimed

IBM z17 LinuxONE guest, s390x, 3 cores, `nnpa` (Telum accelerator) present.
IBM's JupyterLab container (pandas 3.0.6, XGBoost 3.4.1); Snap ML via its cp312
s390x wheel. Full pipeline runs on the instance end to end.

| engine | batch (172,485 buildings) | p99 single row |
|---|---|---|
| XGBoost 3.4.1 | 358,629 /sec | 0.71 ms |
| **Snap ML 1.17** | **481,356 /sec (1.34×)** | **0.51 ms** |

The whole city re-ranks in ~0.36 s. Stream 2 independently logged the z17 hardware
(`task 2/deliverables/z17_hardware_log.md`). Honest caveat: the gain is Snap ML's
CPU tree engine; that original benchmark does not establish accelerator offload. No documented past winner has
shown measured s390x performance at all.

**Supplementary accelerator comparison, October 18:** the exported daily XGBoost
model was imported into separate Snap ML CPU (`compress_trees`) and IBM zDNN
(`zdnn_tensors`) objects on a machine-type 9175 s390x guest. Both paths closely
matched XGBoost across 62,487 complete building rows. Median batch time was
97.624 ms for CPU and 459.850 ms for zDNN, a 4.71× CPU advantage in this run.
This is inference-only timing of a different input matrix from the frozen table
above. The [benchmark appendix](benchmarks/2026-10-18-emerson/README.md) contains
all 2,040 timing records, selected formats, versions, hashes, latency distribution,
execution diagram and reproduction instructions.

## 7. Streams 3 & 6 — the product (`web/`, `realtime/`, `docs/webapp-spec.md`)

- **Real-time loop (`realtime/app.py`):** replays the Feb 7–9, 2026 snap (13,222
  heat complaints, 6,382 buildings) as a live event stream — detect (complaint
  arrives) → decide (rolling features update, model re-scores that building) →
  respond (inspector queue re-sorts). Flask: `/queue`, `/stats`, `/replay/start`.
- **Inspector map:** Folium on the instance's public IP; two sorts (most likely to
  fail / most tenants at risk, via calibrated probability × units).
- **Tenant lookup:** address → BBL (NYC GeoSearch) → "**your building has an N%
  chance of losing heat this winter**" + complaint/violation history per season,
  landlord portfolio, boiler record — with the reliability table one tap away.
- **Alerts:** register a building + email; when the 7-day forecast shows a freezing
  run, buildings crossing the calibrated threshold get one email per spell with the
  311 action line.
- **Live site:** https://ibmsubmission.vercel.app, first good production deploy
  October 17, 2026 at about 18:03 UTC (commit `fa541b1`), redeployed at about 18:08 UTC
  with the LinuxONE link. The page is served by Vercel; every sign-up is forwarded to the
  s390x guest, geocoded and stored there, and the live monitor reads the replay service
  running on the guest. Layout and rules: `docs/VERCEL.md`. The replay the live monitor
  runs is keyed by BBL, so it holds 13,186 of the 13,222 complaints above (36 have no
  BBL) at 6,133 tax lots.

## 8. Honest limitations (say them before the judges ask)

1. The label is "tenants called 311 twice in 48h," not "the boiler died" — quiet
   suffering is undercounted (documented building-level under-reporting, NYU 2025).
   The violation tier (stream 2's 1.87× confirmation lift) is the check.
2. Backtests use observed temperature as the forecast stand-in; measured archived
   forecasts are ~2°F off at 48h, so live performance should be close. The spell
   *timing* also comes from observed weather in backtests.
3. Landlord/boiler tables are current snapshots applied to past seasons.
4. Buildings with no history aren't individually ranked (by team decision) — the
   Heat Sensors Program and physical-risk screening complement them.
5. Cold spells are knowable ~7 days out; we trigger 1–2 days ahead, never a month.

## 9. Where every number lives

| number | file |
|---|---|
| 69.1 / 96.6 @100 (48h / 30d) | `model/out/results_precision_at_k.csv` |
| 86.1 spell, 99 preseason, autopsy | `model/out/spell_results.csv`, pipeline4 log |
| 6-fold CV table | `model/out/backtest_by_season.csv` |
| reliability bins | `model/out/season_reliability.csv`, `calibration.csv` |
| per-building winter risk | `model/out/season_risk_2026.csv` |
| ranked cold-snap list | `model/out/ranked_inspection_list.csv` |
| throughput | pipeline4 log (04 section) |
| supplementary CPU vs zDNN comparison | `docs/benchmarks/2026-10-18-emerson/` |
| violation confirmation, saturation, geography | `task 2/deliverables/` |
| band heatmaps, cold sensitivity | `analysis/analysis_outputs/` |
