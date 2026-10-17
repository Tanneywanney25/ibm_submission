# T16 — the Info section: what this is, how it works, open-sourced

## Goal

A public "About / Methods" section that treats visitors like adults: what
HeatAhead is, that the code is open source, and an honest plain-language tour
of the methods — **key features and how we train**, not an exhaustive dump of
everything we ever trained.

## Pages (one nav entry "About", three tabs or anchors)

1. **What is HeatAhead** — the one-paragraph story, who it's for, what a
   ranked inspection list buys the city (the T12 numbers), team + datathon.
2. **Methods** — in plain language with the real numbers:
   - the prediction task (cold spell starts → probability of whole-building
     heat failure during the spell);
   - key feature families only: complaint history windows, prior-season
     record, building attributes, landlord portfolio, block contagion,
     forecast context;
   - how we train: forward-chaining across six winters, validation-winter
     selection, the untouched 2025-26 holdout, calibration before display;
   - **uncertainty, prominently**: bootstrap confidence intervals and ranges
     on every headline, the permutation tests, why probabilities are capped
     at 99% and banded — teach that ranges are honest, not weakness.
3. **Open source** — link to the GitHub repo, license, how to reproduce
   (pointing at `model/README.md`), what's deliberately *not* published
   (raw data, secrets, anything apartment-level).

## Contracts

- Making the repo public is a **team decision** — confirm with the team and
  add a LICENSE before the link goes live; until then the page says
  "source available on request".
- Numbers on the page come from the frozen docs (`model-final-comparison.md`,
  `experiments-report.md`) — no new claims, nothing recomputed.
- Building-level only; no apartment mentions; plain language over jargon.
- New URLs (`/about`) are additions, so update VERCEL.md §3 in the same commit.

## Steps

1. Draft copy from the existing docs (they already contain every claim).
2. Build the pages on T13 components; works fully in LITE (static content).
3. Team sign-off on the open-source link + LICENSE; wire or placeholder it.
4. Smoke test, push.

## Acceptance

- [ ] Every number on the page traces to a frozen doc/CSV.
- [ ] CIs/ranges shown next to the headline numbers, with one-line
      explanations of bootstrapping and calibration a layperson can follow.
- [ ] Open-source link live only after team sign-off + LICENSE committed.
- [ ] Page renders in LITE mode; VERCEL.md §3 updated in the same commit.
