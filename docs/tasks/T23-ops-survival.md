# T23 — ops survival: backups, CI, service monitoring

## Goal

Three cheap guards against losing the demo. The guest has **no backups and
the account expires 2026-11-15**; a push to `main` deploys the public site
with **no checks**; and the three systemd services plus the alerts cron have
**no monitoring**. Any one of these can erase a weekend of work or kill the
live demo; together they're about a day of work.

## 23a — backups (do this first)

Nightly cron on the guest that dumps everything that exists *only* there:
the users/accounts DB, `data/live/` high-water files (once T15 lands), any
model outputs not yet pushed. Tar + date-stamp, then push to a private
GitHub repo (not this one — data stays out of this repo) or rclone to the
team Drive. Secrets stay in the env file, never in the archive.

- [ ] Two consecutive nightly archives exist off-box; a restore of the
      users DB from one is demonstrated once.
- [ ] `docs/VERCEL.md` §8 gains a one-paragraph "what lives only on the
      instance and where its backup goes" note.

## 23b — CI on GitHub Actions

`main` deploys the site, so `main` must stay deployable.

- Workflow on push/PR: install pinned deps, run the T11c leakage/pytest
  suite, byte-compile `web/` + `api/`, and build the LITE app enough to
  catch import/route errors (no Vercel token needed for a smoke import).
- Keep it under ~2 minutes so nobody is tempted to skip it.

- [ ] A deliberately broken import on a branch fails the check; `main`
      shows green.
- [ ] Leakage suite runs on every push to `main`.

## 23c — service monitoring

- Guest-side watchdog cron (every 10 min): check `heatahead-web` health
  endpoint, `heatahead-realtime`, and the public Vercel URL; on failure,
  email via the existing T4 SMTP path (dedupe so a dead service sends one
  mail, not 144/day).
- `systemd` `Restart=on-failure` on all three services if not already set.

- [ ] Killing `heatahead-web` by hand produces exactly one alert email and
      the service self-restarts.
- [ ] The watchdog's own cron line is documented in VERCEL.md §8.

## Contracts

- Secrets never enter the repo or the backup archive metadata.
- Backup repo/Drive is private; it may contain user emails, so it is
  treated as sensitive and named in the docs, not in public copy.
- No new ports opened; the watchdog reads, it does not listen.
