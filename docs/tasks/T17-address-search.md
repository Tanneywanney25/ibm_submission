# T17 — address search with autocomplete, no map required

## Goal

Everything the risk map can tell you about a building, reachable by just
typing an address: a prominent search box (landing page + nav) with
autocomplete, which resolves straight to the building page — same data,
same risk presentation as clicking the map, minus the map.

## What already exists

- The risk map (T2 spec) and `/api/map_data`; building pages render risk,
  history, owner contact (T5) per building.
- Buildings keyed by int64 `bbl`; `public/data/` carries the LITE snapshot.

## Design

- Autocomplete via **NYC Planning GeoSearch** (`geosearch.planninglabs.nyc`
  `/v2/autocomplete`, free, no key): queried from the browser as the user
  types (debounced ~250ms), returns candidates with BBL attached.
- Selecting a suggestion → resolve BBL → straight to that building's page.
- Fallbacks: GeoSearch down → server-side prefix match over our own address
  list; address resolves to a BBL we don't score (non-residential, outside
  universe) → an honest "not in our universe, here's why" page, never a 404.
- Keyboard complete: arrows + enter, visible focus, works on mobile widths.
- **The map comes to the search, too**: resolving an address also pulls up
  the risk heat map (T2) as part of the result UI — centered and zoomed on
  the searched building, its hex/marker highlighted, surrounding block risk
  visible for context. On the building page this is an embedded map panel;
  from the search box it deep-links as `/map?bbl=…` so the map opens already
  focused. Search without the map still works (the map panel lazy-loads and
  LITE/slow connections get the building page first, map after).

## Contracts

- Search leads to the **same** building page the map uses — one presentation
  of risk (calibrated, capped 99%, banded), never a second code path.
- Building-level only: suggestions and results never show apartment units.
- Nothing typed is logged with identifying info; GeoSearch gets the query
  string only (it's a public city service; no other third parties).
- New endpoint (e.g. `/api/resolve?bbl=`) → update VERCEL.md §3 same commit.
- Must work in LITE mode: client-side GeoSearch + the snapshot's BBL set.

## Steps

1. Search component (T13-styled) with debounce, keyboard nav, loading state.
2. BBL resolution endpoint + the out-of-universe page.
3. Place on landing hero and nav; wire the map's building page as target.
4. Map integration: `/map?bbl=` focus param on the T2 map + the embedded,
   lazy-loaded map panel on the building page, searched building highlighted.
5. Test the fallbacks (throttle GeoSearch, unknown BBL, map unavailable)
   and mobile.

## Acceptance

- [ ] Typing 5 characters of a real address surfaces it; enter lands on the
      same building page the map opens.
- [ ] Out-of-universe address gets the explainer page, not a 404.
- [ ] Search result shows the heat map centered on the searched building,
      highlighted, with neighborhood risk visible; page still usable if the
      map fails to load.
- [ ] Works in LITE mode on the Vercel deploy; mobile keyboard flow works.
- [ ] No apartment-level text anywhere in suggestions or results.
- [ ] VERCEL.md §3 updated with any new endpoint in the same commit.
