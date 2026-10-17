# T4 — Real-time alerts (forecast-triggered emails)

**Goal:** registered tenants/landlords get ONE email per cold spell, 1–2 days
before it lands, when their building crosses the risk threshold. This is the
"HeatAhead told me before my heat died" story.

## Design (already specced in docs/webapp-spec.md §alerts — this is the build card)

- **Worker script** `web/alerts.py`, run by cron/loop on the instance (hourly):
  1. Pull the Open-Meteo 16-day forecast (daily TMIN):
     `https://api.open-meteo.com/v1/forecast?latitude=40.7789&longitude=-73.9692&daily=temperature_2m_min&temperature_unit=fahrenheit&timezone=America%2FNew_York&forecast_days=7`
  2. Detect a freezing run: ≥2 consecutive days with TMIN < 32 inside the next
     7 days → that run's first day is `spell_start`
  3. For each registered bbl (`users` where role in tenant/landlord and bbl set):
     alert if `season_risk_2026.p_season ≥ 0.35` OR
     `ranked_inspection_list.p_calibrated ≥ 0.20`
  4. Dedupe via `alerts_sent(bbl, email, spell_start)` — one email per
     (user, spell); a spell that extends does not re-fire
- **Email**: SMTP creds via env (`SMTP_HOST/PORT/USER/PASS/FROM`); if unset,
  print the full email to stdout/log — **that's fine for the demo video**
- **Copy** (keep this wording): risk band, citywide rank, spell dates, then the
  action line: "If your heat fails, call 311 and give your apartment number —
  since Oct 1, 2026 HPD must attempt an inspection for every non-anonymous heat
  complaint." Unsubscribe line at the bottom (delete the users row).

## Threshold honesty

Because probabilities are calibrated, we can state alert precision in advance:
at the 0.20 cold-day threshold, ≥1 in 4 alerted buildings fails within 48h of
each cold day, and the large majority within the spell. Put that sentence in
the email footer and the slides.

## Steps

1. `web/alerts.py` per the loop above (~80 lines; reuse `web/app.py`'s loads)
2. `--dry-run` flag: print would-send list, send nothing
3. Fire a test with a fake forecast (`--force-spell 2026-10-20`) for the video
4. Cron it on the instance (`*/60`), log to `web/alerts.log`

## Acceptance

- [ ] Dry-run lists the right registered users with correct risk numbers
- [ ] Forced spell produces exactly one email per user; second run sends none
- [ ] Unsubscribe removes the row
- [ ] Screen capture of the triggered email/log for the video

**Depends on:** T1 (users table). **Feeds:** the Respond beat of detect-decide-respond.
