# T21 — fairness & equity audit

## Goal

Answer the question a government judge will ask first: *does this tool serve
all of New York equally?* Slice the frozen model's performance and
calibration by borough, community district, building size, NYCHA vs private,
and (via PLUTO/ACS join) neighborhood income band — and publish the table.
Pure analysis: no model change, no new product surface beyond a short
Methods section addition (T16).

## Why it matters

An inspection-ranking tool that under-serves the Bronx or over-flags small
buildings would do real harm deployed. Showing we *checked* — and either
found parity or named the gaps honestly — is a differentiator no other team
will have, and it's one person for about a day.

## Method

1. Join the scored universe to PLUTO borough/CD and an ACS median-income
   table by CD (public, small — fine to keep the mapping CSV in the repo,
   it's not building data).
2. Per slice: precision@k share vs complaint-base share, calibration curve
   (the T7 Wilson-CI machinery reruns per slice), and rank distribution.
3. The key comparison: does the model's top-2500 allocate inspections
   *more* or *less* proportionally to where verified violations actually
   occur than the 14-day baseline does?
4. Bootstrap CIs on every gap (reuse T7's cluster bootstrap).
5. Write `docs/fairness-audit.md`; one paragraph + one table go into the
   About/Methods copy (T16) and a slide.

## Contracts

- Building-level only; income is CD-level context, never a per-building
  label shown on the site.
- Frozen numbers untouched; this reads `model/out/` scores, writes docs.
- Findings are reported as measured, favorable or not — no cherry-picking;
  if a gap shows up, the doc says so and proposes the follow-up.

## Acceptance

- [ ] `docs/fairness-audit.md` with per-borough/CD/income-band precision,
      calibration and allocation tables, all with CIs.
- [ ] Model-vs-baseline allocation comparison answered explicitly.
- [ ] One honest paragraph ready for About/Methods and the deck.
