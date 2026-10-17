# T14 — a clean account platform: sign-in, profile, customizable dashboard

## Goal

Two moves that simplify the product:

1. **A clean sign-in/sign-up experience** — one calm screen each, Opendoor
   quality (T13 styles), instant inline validation, the welcome email flow
   (T4) unchanged underneath.
2. **Kill the role split.** Tenant / landlord / government / viewer accounts
   presented different UIs; that complicated everything and had no real
   application. One account type. What *was* role-specific becomes **profile
   customization**: in your profile you toggle which panels appear on your
   dashboard (my buildings & alerts · landlord self-audit tools · the
   enforcement/inspection queue · city-wide stats).

## What already exists

- `web/app.py`: register/login, roles stored at signup, `my_buildings`,
  welcome email via `web/mailer.py`, sign-ups stored on the instance (FULL
  mode); LITE mode ships without accounts.
- Role-conditional template blocks scattered across `web/templates/`.

## Contracts

- URL paths in VERCEL.md §3 unchanged; existing accounts keep working — a
  migration maps each old role to a default panel set (tenant → buildings +
  alerts; landlord → + self-audit; gov → + queue; viewer → stats only).
- No passwords or secrets in the repo or logs (CLAUDE.md). Sessions and
  storage stay on the instance; LITE keeps degrading gracefully to no-auth.
- Building-level only everywhere, as always.

## Steps

1. Inventory every `role ==` conditional in templates and app code.
2. Replace with `panels` (a set stored on the user; profile page edits it);
   default-on panels chosen by the migration map.
3. Rebuild the auth screens and the profile page on T13 components.
4. Dashboard renders exactly the enabled panels, in a fixed sensible order.
5. Test: old account logs in and sees the same content as before; new
   account gets the default set; toggles persist.

## Acceptance

- [ ] No `role` conditionals left in templates; one account type in code.
      *(Open: the dashboard no longer branches on role — panels only — but the
      registration form still records a role, because `/api/register` and the
      instance's `users` table keep it (VERCEL.md §3) and it feeds alerts and
      the panel defaults. Removing it is a contract + instance-schema change.)*
- [x] Profile page toggles panels; choice persists across sessions.
      *(Customize on the dashboard; stored per account via `/api/account/panels`
      — forwarded to the instance from Vercel like registrations. While the
      instance is unreachable the choice falls back to this-device storage and
      the page says so.)*
- [x] Existing accounts see equivalent dashboards post-migration.
      *(No data migration needed: an account that never customized gets the
      panel set derived from its registration roles by the map above.)*
- [ ] Sign-up still sends the welcome email; unsubscribe still works.
- [x] VERCEL.md §6 smoke test green in LITE (no-auth path unbroken).

## Status (October 17, 2026)

Sign-in shipped earlier (Google + passwordless email links; awaiting env vars in
Vercel). The dashboard-panels half is now built: four panels (my buildings &
alerts · landlord self-audit tools · inspection queue · city-wide stats),
defaults from the role→panels map, Customize toggles stored per account at
`/api/account/panels` (new VERCEL.md §3 row). The instance stores panel choices
once it pulls this commit and `heatahead-web` restarts; until then the site
degrades to role defaults + per-device storage, as designed.
