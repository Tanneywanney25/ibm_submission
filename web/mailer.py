"""Shared email sending for the signup welcome and the cold-snap alerts.

SMTP via env: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM.
Without SMTP_HOST every message is printed and appended to web/alerts.log -
the demo-friendly mode. Secrets live in the instance environment, never here.
"""

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

LOG = Path(__file__).resolve().parent / "alerts.log"


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass                     # read-only filesystem (Vercel) - stdout only


def make_msg(to, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM", "alerts@heatahead.local")
    msg["To"] = to
    msg.set_content(body)
    return msg


def send(msg, dry=False):
    """Send (SMTP env) or log the full message. Returns True on success."""
    if dry:
        log(f"DRY-RUN would send: {msg['To']} | {msg['Subject']}")
        return True
    host = os.environ.get("SMTP_HOST")
    if not host:
        log(f"(no SMTP configured) EMAIL -> {msg['To']} | {msg['Subject']}\n"
            f"{msg.get_content()}")
        return True
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=15) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)
        log(f"sent: {msg['To']} | {msg['Subject']}")
        return True
    except Exception as e:
        log(f"SMTP error for {msg['To']}: {e}")
        return False


def welcome_email(email, role, bbl=None, p_season=None):
    lines = [f"You're signed up for HeatAhead alerts as a {role}.", ""]
    if bbl and p_season is not None:
        pct = f"{p_season * 100:.0f}%"
        lines += [f"Your building (BBL {bbl}) has a {pct} modeled chance of at "
                  f"least one heat outage this winter.", ""]
    lines += [
        "What to expect: when the 7-day forecast shows a freezing stretch and "
        "your building is at elevated risk, you'll get ONE email per cold "
        "spell - never more.",
        "",
        "If your heat ever fails: call 311 and give your apartment number - "
        "since Oct 1, 2026, HPD must attempt an inspection for every "
        "non-anonymous heat complaint.",
        "",
        f"Unsubscribe any time: /unsubscribe?email={email}" +
        (f"&bbl={bbl}" if bbl else ""),
    ]
    return make_msg(email, "HeatAhead: you're signed up for heat-risk alerts",
                    "\n".join(lines))
