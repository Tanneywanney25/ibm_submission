# T1 — Website core: signup with roles (tenant / landlord / government / viewer)

**Goal:** one Flask site where anyone enters an address + email (phone optional),
picks a role, and is registered for what their role gets. This is the shell every
other task plugs into.

**Starter code exists:** `web/app.py` + `web/templates/` already implement the
skeleton — pages, `/api/register` with role validation, SQLite schema
(`users`, `alerts_sent`), address→BBL via NYC GeoSearch, and data loading from
`model/out/`. Start there; don't rebuild.

## Contract

- `POST /api/register` `{role, email, phone?, address?, bbl?}` → `{ok, bbl, p_season?}`
  - roles: `tenant` | `landlord` | `government` | `viewer`
  - tenant/landlord: address resolved to BBL via `/api/lookup` (GeoSearch)
  - UNIQUE(email, bbl) — re-registering is idempotent
- `GET /api/lookup?address=` → `{bbl, normalized}` (502 if geocoder down — allow raw BBL entry)
- SQLite at `web/heatahead.db` (gitignored); no passwords, no auth for the demo —
  say so on the page ("demo: no login")

## Role behaviors (what each sees after signup)

| role | gets |
|---|---|
| tenant | their building page + cold-snap alerts (T4) |
| landlord | all THEIR buildings (join email→bbl now; portfolio via `bbl_landlord.csv` later) + inspection nudges |
| government | the ranked queue (`/monitor`, T3) + CSV download of top-k |
| viewer | the public map (T2), no building-level alerts |

## Steps

1. Run the starter: `python web/app.py` (needs `model/out/` populated — see model/README)
2. Wire the three remaining pages' nav + role-aware landing after signup
3. Landlord flow: after signup, list buildings where `bbl_landlord.landlord`
   matches any of their registered BBLs' landlord
4. Gov flow: `/monitor` + a `GET /api/queue.csv?k=500` export

## Acceptance

- [x] Register each of the four roles end to end; rows visible in SQLite
- [x] Tenant with a Bronx address sees their p_season immediately after signup
- [x] Bad email / unknown role / garbage address all return clean errors
- [x] Runs on the LinuxONE instance behind the opened port (after token change)

## Built (October 17, 2026)

The signup page at `/` is the landing page of https://ibmsubmission.vercel.app. The site
runs on Vercel in LITE mode and forwards every registration to the LinuxONE instance, which
geocodes the address, stores the row in `~/heatahead/site/web/heatahead.db` on the s390x
guest and answers with the building's winter risk. How the two halves fit is in
`docs/VERCEL.md` sections 2, 3 and 8.

- Role-aware landing after signup: a tenant sees the building's winter risk (banded above
  20%, capped at 99%) and a link to the building page; a landlord sees every registered
  building plus the registered owner's portfolio, riskiest first (Parkchester South,
  BBL 2039437501, lists its sister buildings); government gets the live queue and the
  top-500 CSV; a viewer gets the map.
- Address matching is strict on purpose: GeoSearch always returns its nearest guess, so
  "1600 Pennsylvania Ave" used to resolve to 218 Pennsylvania Avenue in Brooklyn. A match
  now has to share the house number, a street word and, when the address names one, the
  borough; anything else is a clean 400 that suggests the 10-digit BBL. Only GeoSearch's
  normalized building address is stored, so an apartment number typed into the box never
  reaches the database.
- Re-registering is idempotent for every role (government and viewer rows have no BBL, so
  `UNIQUE(email, bbl)` alone did not catch them) and says so on the page.
- Practice signups verified through the whole chain (local LITE mode forwarding to the
  instance, and the browser UI): four roles stored on the s390x guest, a second tenant
  signup returned `already_registered`, and bad email, unknown role, a phone with two
  digits, a nine-digit BBL, "123 Fake Street" and "1600 Pennsylvania Ave" each returned a
  400 with a readable message.

**Depends on:** model outputs (done). **Feeds:** T2, T3, T4, T5.
