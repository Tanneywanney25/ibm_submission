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

- [x] No `role` conditionals left in templates; one account type in code.
      *(The home page has no role picker and nothing in any template branches
      on an account role. "Save a building" sends no role; `/api/register`
      stores `tenant` in the legacy `users.role` column, which `web/alerts.py`
      and the instance schema key on, and still accepts a legacy role from
      older clients. The building page's `as=tenant|landlord` picks which
      draft letter to write, not an account type. Dropping the column itself
      would be an instance-schema change; nothing needs it now.)*
- [x] Profile page toggles panels; choice persists across sessions.
      *("Your profile" on the home page (`/#profile`): panel toggles save as you
      click, per account via `/api/account/panels`, forwarded to the instance
      from Vercel like registrations. While the instance is unreachable the
      choice falls back to this-device storage and the page says so.)*
- [x] Existing accounts see equivalent dashboards post-migration.
      *(No data migration needed: an account that never customized gets the
      panel set derived from its registration roles by the map above. A new
      account starts on buildings + city-wide stats, and saving its first
      building keeps that view (it is stored, so the building row's legacy
      role cannot narrow it).)*
- [x] Sign-up still sends the welcome email; unsubscribe still works.
      *(Tests: one welcome email per newly saved building, none on a repeat
      save, text has no role; unsubscribe needs sign-in, confirms by POST.)*
- [x] VERCEL.md §6 smoke test green in LITE (no-auth path unbroken).

## Status (October 17, 2026, evening)

The code is complete. Sign-in: Google and passwordless email links on one screen
with instant inline validation (email format; building address/BBL; phone), and
first sign-in creates the account. Profile: who you are and how you signed in,
dashboard panel toggles, a role-free "Save a building" form, and a stop-all-alerts
link. Dashboard: four panels (my buildings & alerts · landlord self-audit tools ·
inspection queue · city-wide stats).

**Not code; what makes it live on production:**
1. Vercel Production env vars: `FLASK_SECRET_KEY` (32+ chars, the same value as
   the instance), and for Google `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `AUTH_BASE_URL=https://ibmsubmission.vercel.app` (docs/GOOGLE_LOGIN.md), then
   redeploy.
2. The instance: `cd ~/heatahead/site && git pull --rebase origin main && sudo
   systemctl restart heatahead-web`, with the same `FLASK_SECRET_KEY` and `SMTP_*`
   in its environment. This also makes panel choices durable there; until then they
   fall back to per-device storage.
3. Styling the auth and profile screens to Opendoor quality belongs to T13 (the
   reskin), which has not started; T14 used the current theme.
