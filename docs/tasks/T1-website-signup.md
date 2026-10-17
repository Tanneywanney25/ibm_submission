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

- [ ] Register each of the four roles end to end; rows visible in SQLite
- [ ] Tenant with a Bronx address sees their p_season immediately after signup
- [ ] Bad email / unknown role / garbage address all return clean errors
- [ ] Runs on the LinuxONE instance behind the opened port (after token change)

**Depends on:** model outputs (done). **Feeds:** T2, T3, T4, T5.
