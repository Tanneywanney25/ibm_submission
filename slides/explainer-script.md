# HeatAhead — the spoken explainer

Read-aloud script. ~2 minutes at talking pace. Use it to brief a teammate, answer
"so what does it actually do?", or as the narration spine for the video. The
bracketed asides are for the speaker, not to be read out.

---

## The script

Every winter, New York tenants file over 300,000 no-heat complaints to 311. The
city now has to attempt an inspection for every single one — with about 350
inspectors. Nobody tells them where to go *first*.

That's what we built. HeatAhead gives every residential building in the city a
risk score: the probability it loses heat when the cold arrives. The score comes
from three things — what the building *is* (its age, size, boiler record, even
how its landlord's other buildings behave), what it has *done* (seven winters of
complaint and violation history, and whether it's flaring up right now), and
what's *coming* (the temperature forecast for the next two days).

When the forecast shows a freezing stretch coming, the system re-scores all
67,000 buildings — that takes under half a second on the IBM LinuxONE — and hands
inspectors a ranked list before the first tenant calls.

Does it work? We tested it the only honest way: we locked away the most recent
winter, 2025 to '26, trained the model only on the seven winters before it, and
then replayed every one of the 71 freezing days of that held-out winter, checking
whether the buildings we flagged actually failed.

One list, three clocks. Of our top one hundred buildings: sixty-nine fail within
the exact next 48 hours. Eighty-seven fail during that cold snap. Ninety-nine fail
at some point that winter. [Pause — let that land.] For comparison, the best
spreadsheet method — ranking by recent complaints — gets seventy-seven percent on
the cold-snap clock. And random inspection gets one.

Two more things make this more than a leaderboard. First, the probabilities are
*calibrated*: when we tell a building fifteen percent, fifteen percent of such
buildings really fail — we verified that nine different ways on held-out data.
Second, we repeated the whole experiment for six separate winters, each time
training only on the past — and the model wins every single one. This isn't a
lucky winter; it's a pattern.

And because the heaviest-risk buildings cluster in the Bronx — the same community
districts where heat complaints run highest per household — the first hundred
doors this model knocks on are in the neighborhoods that need it most.

---

## If someone asks "are you overfitting?" (30-second answer)

No — the headline numbers come from a winter the model never saw. We also
re-ran the test on six different winters, training only on earlier years each
time, and won all six. We report every number next to the strongest baseline, not
in a vacuum. And our probabilities match reality — when we say 15%, 15% fail —
which an overfit model can't do on held-out data.

[If pressed on limits, concede these without flinching:]
- Our label is "tenants called 311", not "the boiler died" — quiet suffering is
  undercounted, and we say so.
- Backtests use observed temperature as the stand-in forecast; measured archived
  forecasts are within ~2°F at 48 hours, so live performance should be close.
- The 99% season number is partly easy — chronic buildings stay chronic — which
  is exactly why we show the baseline (96%) beside it and measure our edge on the
  buildings recency *misses*: those are 97% on the 30-day clock.

## The numbers behind each sentence (for whoever makes slides)

| claim in the script | source |
|---|---|
| 300k+ complaints, ~350 inspectors, inspect-every-complaint rule | docs/heat-project-brief.md §8 |
| 69 / 87 / 99 of top-100 on the three clocks | model/out: results_precision_at_k.csv, spell_results.csv |
| baseline 77% per spell, random ~1% | spell_results.csv; cold-day base rate 1.2% |
| re-scores 67k buildings in <0.5s on LinuxONE | model/04 benchmark: 434-487k buildings/sec (Snap ML) |
| calibration "15% means 15%", 9 splits | docs/model-iterations.md reliability section |
| six winters, wins all six | model/out/backtest_by_season.csv |
| Bronx clustering | EDA: Bronx CDs 207/204/205 highest complaints per unit |
