# About section — draft copy (T16)

Draft of the site's public About / Methods / Open source pages. Every number
below is taken from the frozen docs (`model-final-comparison.md`,
`experiments-report.md`, `model-iterations.md`) — nothing recomputed. Review,
trim, then lift into templates when T16 is built. Status: DRAFT, not yet on
the site.

---

## Tab 1 — What is HeatAhead

### Heat should never be a surprise.

Every winter, thousands of New York City buildings lose heat during cold
snaps — and the city finds out one 311 call at a time. HeatAhead flips that
order. We predict **which buildings are likely to lose heat before the cold
arrives**, so inspectors, tenants and owners can act early instead of react
late.

**How it works, in one breath:** when a cold spell approaches, our model
scores every residential building in the city and produces a ranked
inspection list. In the top 100 buildings we flag at the start of a spell,
about **90 will actually experience a whole-building heat failure** during
that spell.

**What that buys the city:** we replayed the real 2025-26 winter — every one
of its 183,384 complaint-days — under the city's actual inspection capacity.
With the *same inspectors on the same days*, dispatching by HeatAhead's
ranking instead of first-come-first-served confirmed **7.8% more violations**,
reached failing buildings in **2.0 days instead of 3.1**, and cut
**cold-household-days in half (−50%)**.

Built by **NYU Tingineers** at the IBM Z Datathon (October 2026). Everything
heavy — training, scoring, the simulation — runs on an IBM z17 LinuxONE
mainframe, which scores **481,356 buildings per second**: the whole city in
under a second.

We work at the **building level only**. We never display, store or publish
apartment-level information.

---

## Tab 2 — Methods (how the predictions are made)

### The question we train on

"A cold spell is starting now — will this building have a whole-building heat
failure at some point during the spell?" One probability per building,
refreshed as conditions change. We also score three other horizons: the next
48 hours, the next 30 days, and the full season.

### What the model looks at

All inputs are public data, and all of them are dated strictly *before* the
moment of prediction:

- **Complaint history** — heat complaints at the building over several
  trailing windows, from the last 2 days to past seasons.
- **Track record** — whether the building failed in previous winters, and its
  verified-violation history.
- **The building itself** — age, size, residential units, building class,
  boiler records.
- **The landlord's portfolio** — trouble at the same owner's *other*
  buildings is an early warning for this one.
- **The block** — heat complaints next door in the last 48 hours travel;
  outages cluster.
- **The forecast** — how cold it is about to get, and for how long.

### How we train — and how we keep ourselves honest

- **Time discipline.** The model only ever sees the past. Features are built
  from data before the prediction moment; the entire 2025-26 winter was held
  out untouched until final evaluation.
- **Forward-chaining validation.** We train on early winters and test on the
  next unseen one, rolling forward across six winters. Our model beat the
  strongest recency baseline in **6 of 6 winters**.
- **Honest headline numbers.** Precision@100 of **69.1%** at 48 hours,
  **86.1%** per cold spell, **96.6%** at 30 days, **99%** for the season.
  Our newest spell-level model reaches **90.1%** per spell — evaluated on
  held-out data it was allowed to see exactly once.
- **A leakage test suite.** Nine automated tests run against the codebase
  itself: no forbidden columns, no same-day information, no future dates,
  no apartment-level data in anything we ship.

### Why we show ranges, not just numbers

A single number can be lucky. Every headline above carries a **bootstrap
confidence interval**: we resample the evaluation data thousands of times
(including in blocks of consecutive days, because days inside one cold snap
rise and fall together) and report the range, not just the point. The model's
edge over the best baseline survives at **p ≈ 0.00001** on daily rankings,
and it won **all 8 of 8** held-out cold spells (exact p = 1/256). When you
see a range on this site, that's not uncertainty we failed to remove — it's
uncertainty we measured and chose to show you.

### Why probabilities are capped and banded

Every probability shown on this site is **calibrated** — checked bin-by-bin
so that "60%" means failure really happens about 60% of the time — then
**capped at 99%** (nothing is certain) and **shown as a band above 20%**,
because "61.3%" implies a precision no forecast honestly has.

---

## Tab 3 — Open source

### The code is open. The data stays safe.

HeatAhead's full codebase — the feature pipeline, model training, evaluation
protocol, the statistical test suite and this website — is open source.

<!-- TEAM DECISION PENDING: repo link + LICENSE. Until sign-off, ship the
     line below instead of the link. -->
**Source available on request** while the team finalizes the license.

**What's published:** every line of code, the full method documentation, the
evaluation protocol, and the model files themselves (portable JSON).

**What's deliberately not published:** raw complaint extracts (available from
NYC Open Data directly), anything apartment-level, and operational secrets.

**Reproduce it:** the data is public — NYC 311, HPD violations, PLUTO, and
weather archives. The pipeline README walks through every step from raw
download to the ranked list.

Built on: Python, XGBoost, scikit-learn, Snap ML, Flask, deck.gl —
running on IBM LinuxONE (s390x) and Vercel.

---

## Notes for the builder (not site copy)

- Tone: plain language, verbs first, no jargon above the fold (T13 rules).
- Numbers trace to: frozen M1 (69.1/86.1/96.6/99, 6/6, 481,356/s), M13
  (90.1, one test look), T7 (p≈1e-5, 8/8 spells p=1/256, Wilson bins),
  T12 (+7.8%, 2.0 vs 3.1 days, −50.2%, 183,384 cases, capacity 700/day).
- The T12 sentence says "confirmed violations" deliberately — do not soften
  to "prevented"; the simulator measures confirmation, not prevention.
- Open-source link goes live only after team sign-off + LICENSE (T16 contract).
