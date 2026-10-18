# T18 — location accuracy: mega-lots, centroids, and honest pins

## The report

A lookup of BBL `1009720001` shows the aerial photo ring in the middle of a
grass field, labelled "very high" — looks like the geocode picked a random
park. Investigated 2026-10-17: **it is not a geocode bug.** That BBL is
Stuyvesant Town (owner `BPP St Owner LLC` = Blackstone, 8,764 units, Manhattan
CD 6): one ~80-acre tax lot covering ~90 apartment buildings, and the pin is
the lot *centroid*, which lands on the central Oval lawn. The data is real;
the presentation is misleading. Other campus lots (Peter Cooper Village,
Co-op City, Penn South, NYCHA campuses, Parkchester) will look the same.

Two distinct problems fall out of it:

1. **The pin**: for any large or irregular lot, the centroid can land on
   grass, a courtyard, water, or even outside the lot. The page presents it
   as "the building".
2. **The semantics**: p = 0.99 / rank 112 for "this building" is really a
   probability for a 90-building campus. Raw complaint counts (193) scale with
   size; per-unit that is a *low* rate. Our "building-level" claim is strained
   exactly on these lots.

## What already exists

- `web/app.py` serves `coords` = PLUTO lot centroid (`latitude`/`longitude`
  from `ranked_inspection_list.csv`); `web/templates/building.html` draws the
  ArcGIS aerial + ring and the Street View link from it, with a NYC
  bounding-box sanity check already in place (building.html ~line 177).
- `public/data/b/*.json` ships `lon`/`lat` per BBL for LITE mode.
- `units` is already in every record, so mega-lots are detectable client-side.

## Contracts

- Building-level only, as always — this task *improves* that story, it never
  adds unit-level data.
- Frozen numbers untouched: no rescoring, no model change. This is a
  presentation + data-audit task.
- `bbl`/`bin` int64 before every join; PLUTO attaches on `bbl` only.
- Anything that changes `public/data/` layout follows VERCEL.md §3/§6 and
  updates that doc in the same commit.

## Steps

1. **Audit** (on the guest, `~/datathon-env/bin/python`): for all 63,727
   ranked BBLs, join PLUTO `lotarea`, `numbldgs`, `unitsres`; count lots with
   `numbldgs > 1` or `lotarea` above ~40,000 sq ft; check centroid-inside-lot
   where geometry is available. Write the findings table to
   `docs/location-audit.md` (counts only, no new shipped data yet).
2. **Honest pin UI**: when `units` is large or the lot is flagged multi-
   building, the imagery caption changes from "the property's mapped
   location" to "this is a multi-building complex of N units; the ring marks
   the center of the lot, not a single building", and the page shows a
   "complex" chip next to the chronic/CD chips.
3. **Better anchor where cheap**: for flagged lots, prefer an address-point
   anchor (GeoSearch — already integrated for T17) or PLUTO's building
   footprint centroid if we pull it in the audit; fall back to the lot
   centroid. Keep the NYC bbox guard.
4. **Rate context**: on the This-winter card for flagged lots, add one line
   of per-unit context ("193 complaints across 8,764 units") so a big campus
   isn't read as 193 complaints in one lobby.
5. Spot-check the top-200 ranked list by hand against the aerial (fast pass,
   screenshot the misfits into the audit doc).

## Acceptance

- [ ] `docs/location-audit.md` says how many lots are multi-building/mega,
      with the top offenders named by BBL.
- [ ] BBL 1009720001 shows the complex caption + chip and per-unit context;
      screenshot in the PR.
- [ ] No pin for any top-200 building lands outside NYC or on water; misfits
      either re-anchored or captioned.
- [ ] Frozen numbers, model outputs and the ranking unchanged; leakage suite
      still green.
