"""T4 - forecast-triggered alerts: one email per registered building per cold spell.

Run hourly (cron) from the repo root:
    python web/alerts.py                 # real run: send (SMTP env) or log
    python web/alerts.py --dry-run       # list who WOULD be alerted, send nothing
    python web/alerts.py --force-spell 2026-10-20   # pretend a spell starts then

SMTP via env: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM.
Without SMTP_HOST, emails are printed to stdout and web/alerts.log - fine for
the demo. Thresholds and copy per docs/tasks/T4-alerts.md.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.append(str(Path(__file__).resolve().parent))
from mailer import log, make_msg, send, unsubscribe_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = Path(__file__).resolve().parent / "heatahead.db"
FORECAST_URL = ("https://api.open-meteo.com/v1/forecast?latitude=40.7789"
                "&longitude=-73.9692&daily=temperature_2m_min"
                "&temperature_unit=fahrenheit&timezone=America%2FNew_York"
                "&forecast_days=7")
P_SEASON_MIN, P_COLDDAY_MIN = 0.35, 0.20


def conformal_tiers():
    """T8: alert thresholds with a conformal FNR guarantee (model/16_conformal.py).
    Returns the tiers dict when the json is present and sane, else None - the
    hand-picked P_COLDDAY_MIN and the old copy line are the fallback."""
    try:
        tiers = json.loads(
            (ROOT / "model/out/conformal_thresholds.json").read_text())["tiers"]
        return tiers if "broad" in tiers and "p_threshold" in tiers["broad"] else None
    except (OSError, KeyError, ValueError):
        return None


def quality_line(tiers, p_cold):
    if not tiers:
        return ("among buildings at our alert threshold, at least 1 in 4 "
                "fails within 48 hours of each cold day - probabilities are "
                "calibrated on last winter.")
    t = (tiers["strict"] if "strict" in tiers
         and p_cold >= tiers["strict"]["p_threshold"] else tiers["broad"])
    return (f"this alert level is calibrated to miss fewer than "
            f"{t['alpha']:.0%} of heat failures (a conformal guarantee, "
            f"verified on last winter's held-out cold days).")


def find_spell(force=None):
    """First day of a run of >=2 consecutive forecast days with TMIN < 32F."""
    if force:
        return force, [force]
    r = requests.get(FORECAST_URL, timeout=10).json()["daily"]
    days = list(zip(r["time"], r["temperature_2m_min"]))
    run = []
    for d, tmin in days:
        if tmin is not None and tmin < 32:
            run.append(d)
            if len(run) >= 2:
                return run[0], [d for d, t in days if t is not None and t < 32]
        else:
            run = []
    return None, []


def risk_table():
    season = pd.read_csv(ROOT / "model/out/season_risk_2026.csv",
                         usecols=["bbl", "p_season", "rank"]).set_index("bbl")
    cold = pd.read_csv(ROOT / "model/out/ranked_inspection_list.csv",
                       usecols=["bbl", "p_calibrated"]).set_index("bbl")
    return season.join(cold, how="left")


def band(p):
    if p >= 0.5:
        return f"very high (roughly {round(p * 20) * 5}%)"
    if p >= 0.2:
        return f"high (roughly {round(p * 20) * 5}%)"
    return f"{p * 100:.0f}%"


def compose(email, bbl, row, spell_start, cold_days, quality):
    p = float(row.p_season)
    return make_msg(
        email,
        f"HeatAhead: cold snap from {spell_start} - your building is at risk",
        f"A freezing stretch is forecast to start {spell_start}"
        f" (sub-freezing days ahead: {', '.join(cold_days)}).\n\n"
        f"Your building (BBL {bbl}) has a {band(p)} modeled chance of losing "
        f"heat this winter (citywide rank {int(row['rank']):,}).\n\n"
        f"If your heat fails: call 311 and give your apartment number - since "
        f"Oct 1, 2026, HPD must attempt an inspection for every non-anonymous "
        f"heat complaint. Landlords must keep apartments at 68F daytime / 62F "
        f"overnight through May 31.\n\n"
        f"Alert quality: {quality}\n\n"
        f"One alert per cold spell, never more. Unsubscribe: reply STOP or "
        f"visit {unsubscribe_url(email, bbl)}\n")
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-spell", metavar="YYYY-MM-DD")
    args = ap.parse_args()

    spell_start, cold_days = find_spell(args.force_spell)
    if not spell_start:
        log("no freezing run in the 7-day forecast - nothing to do")
        return 0
    log(f"freezing run detected, spell_start={spell_start}")

    tiers = conformal_tiers()
    p_cold_min = tiers["broad"]["p_threshold"] if tiers else P_COLDDAY_MIN
    log(f"cold-day threshold {p_cold_min}"
        + (" (conformal, alpha=%s)" % tiers["broad"]["alpha"] if tiers
           else " (hand-picked fallback)"))

    risks = risk_table()
    con = sqlite3.connect(DB)
    # the account page's "pause all alert emails" switch (profiles.alerts_paused);
    # the table may predate this script run on a fresh database
    con.execute("CREATE TABLE IF NOT EXISTS profiles (email TEXT PRIMARY KEY, "
                "name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', "
                "borough TEXT NOT NULL DEFAULT '', zip TEXT NOT NULL DEFAULT '', "
                "alerts_paused INTEGER NOT NULL DEFAULT 0, "
                "updated TEXT DEFAULT CURRENT_TIMESTAMP)")
    users = con.execute(
        "SELECT email, bbl FROM users WHERE bbl IS NOT NULL "
        "AND role IN ('tenant','landlord') AND email NOT IN "
        "(SELECT email FROM profiles WHERE alerts_paused=1)").fetchall()
    log(f"{len(users)} registered building subscriptions (paused accounts excluded)")

    sent = skipped = 0
    for email, bbl in users:
        bbl = int(bbl)
        if bbl not in risks.index:
            continue
        row = risks.loc[bbl]
        p_cold = row.p_calibrated if pd.notna(row.p_calibrated) else 0.0
        if row.p_season < P_SEASON_MIN and p_cold < p_cold_min:
            continue
        dup = con.execute("SELECT 1 FROM alerts_sent WHERE bbl=? AND email=? "
                          "AND spell_start=?", (bbl, email, spell_start)).fetchone()
        if dup:
            skipped += 1
            continue
        if send(compose(email, bbl, row, spell_start, cold_days,
                        quality_line(tiers, p_cold)), args.dry_run):
            sent += 1
            if not args.dry_run:
                con.execute("INSERT INTO alerts_sent(bbl, email, spell_start) "
                            "VALUES (?,?,?)", (bbl, email, spell_start))
                con.commit()
    log(f"done: {sent} alert(s) {'listed' if args.dry_run else 'sent'}, "
        f"{skipped} deduped (already alerted for this spell)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
