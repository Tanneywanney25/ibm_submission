# The judges' presentation — full run of show

Three artifacts in one: the 3-minute video script (timed beats, what's on screen),
the slide order, and the Q&A bank. Numbers are final (LinuxONE ensemble run,
Oct 18). The shorter spoken explainer is `explainer-script.md`; the master source
for every claim is `docs/SUBMISSION.md`.

---

## The 3-minute video (rubric: must show the LinuxONE instance AND the model)

**0:00–0:25 — The problem.** [B-roll: winter NYC, then the 311 complaint map.]
"Last winter New Yorkers filed over three hundred thousand no-heat complaints.
On February 8th alone: five thousand seven hundred. As of this October, the city
must attempt an inspection for every single one — with about three hundred fifty
inspectors. Nobody tells them where to go first."

**0:25–0:45 — Prior art, named.** [Slide: four prior efforts.]
"Predicting bad buildings isn't new — Columbia tried in 2015, NYU in 2017, IBM's
own course capstone does it. All of them rank last year's bad buildings. None of
them watch the forecast. HeatAhead is forecast-triggered: when cold is coming, we
re-rank the whole city before the first tenant calls."

**0:45–1:20 — How it works.** [Diagram: forecast + live complaints + building
history → model → ranked queue.] "Every building's risk comes from what it is —
age, size, boiler record, even its landlord's other buildings — what it's done
across seven winters, and what's coming in the next 48 hours. We trained on seven
winters and tested on the eighth, which the model never saw: all seventy-one
freezing days of last winter, replayed."

**1:20–1:50 — The numbers.** [Slide: the ladder.] "Of our top one hundred
buildings: sixty-nine fail within forty-eight hours. Eighty-six fail during that
cold snap. Ninety-nine fail that winter. The best spreadsheet method gets
seventy-seven on the snap clock. And these probabilities are calibrated — when we
say fifteen percent, fifteen percent fail. We validated the whole idea six
winters over, training only on the past each time: six wins out of six."

**1:50–2:25 — IBM Z, live.** [SCREEN RECORDING of the instance: `uname -m` →
s390x; `grep nnpa /proc/cpuinfo`; the replay running; the latency ticker.]
"This is our IBM z17 LinuxONE guest. Here's the Feb 7th cold snap replaying as a
live event stream — thirteen thousand complaints — and the queue re-sorting in
real time. Snap ML re-scores all one hundred seventy-two thousand buildings in a
third of a second: four hundred eighty thousand buildings per second, measured on
this guest." [Point at numbers on screen.]

**2:25–2:50 — Who it's for.** [Map zooming to the Bronx; then the tenant page.]
"Three Bronx community districts — four percent of the city's homes, fifteen
percent of its heat complaints, four hundred thousand tenants. They're where our
top hundred concentrates. And any tenant can type their address and see their
building's chance of losing heat this winter — with its full complaint history —
and register for an alert before the next cold snap."

**2:50–3:00 — Close.** "Same inspectors. Same budget. Knock before they freeze.
HeatAhead, on IBM Z." [Repo URL + team number on screen.]

## Slide order (if presenting live)

1. Title + team `[ONLXXX]` · 2. 300k complaints / 350 inspectors / Oct 1 rule ·
3. Prior art named → our difference · 4. How it works (one diagram) ·
5. Stream 1 heatmap (building type × cold band) · 6. The ladder (69→86→97→99) +
6-of-6 CV table · 7. Calibration table ("15% means 15%") · 8. Stream 2: saturation
proof + Bronx geography (`fig_bronx_cd_impact.png`) · 9. LinuxONE: measured
throughput + replay screenshot · 10. Tenant lookup + alerts · 11. Limitations
(all five, unprompted) · 12. Close.

## Q&A bank (the answers, 15 seconds each)

- **"Is 69% good?"** On a day when 1.2% of buildings fail, random gets 1 of 100;
  we get 69, and 99 of the same hundred fail that winter. The 48-hour number is
  strict because whether tenants call Tuesday or Thursday is noise — our building
  selection is ~95%+ right (autopsy: 1–7 truly clean per 100).
- **"Overfitting?"** Held-out winter, never trained on. Repeated across six
  winters, forward-chaining, 6 wins. Reported against the strongest baseline.
  Calibration matches reality on held-out data — overfit models can't do that.
- **"Why not deep learning?"** 760k rows of counts and temperatures: gradient
  boosting is the tabular state of the art; every credible prior effort used the
  same family. Our gains came from features and target design.
- **"Don't you just find the chronic buildings?"** That's the baseline we beat.
  The new-to-list cut — our picks that recency misses — still fails at 60% in 48h,
  96% in 30 days. And stream 2 found 18,814 Forecast-Only buildings that *only* a
  weather-triggered system ever sees.
- **"Could HPD use this tomorrow?"** The list regenerates in a third of a second
  from public data on one small guest; the law requiring inspections took effect
  Oct 1; the Comptroller's open recommendation is exactly this prioritization.
- **"What breaks it?"** Reporting bias (we rank among buildings with history; the
  quiet ones need sensors), ownership changes (snapshot tables), and anything past
  ~7 days of forecast horizon — which is why it triggers at 1–2 days.

## Submission checklist (stream 4 — do not skip)

- [ ] Confirm the deadline on Hack2skill/Discord (two readings differ ~10.5h!)
- [ ] Team number `[ONLXXX]` in the project title AND README
- [ ] Video ≤3 min, shows the instance + the model (screenshots: `uname -m`,
      nnpa, replay ticker, throughput numbers)
- [ ] Repo public; data source links + open-source library links in README (rule)
- [ ] Six-member roster only if Sid got written confirmation
- [ ] Submit with a 2-hour buffer
