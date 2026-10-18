"""Public project-update signup, separate from accounts and building alerts.

Vercel forwards anonymous requests to the existing durable instance. Confirmation
and unsubscribe tokens contain an opaque subscriber id, never an email address.
There is no campaign sender or public subscriber-list endpoint.
"""
from collections import deque
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import requests

import mailer

bp = Blueprint("newsletter", __name__)
CONTACT_EMAIL = "heataheadnyc@gmail.com"
CONSENT_VERSION = "project-updates-2026-10"
CONFIRM_TTL = 24 * 60 * 60
RESEND_DELAY = 10 * 60
ACCEPTED = ("If this address isn't already subscribed, we'll send a confirmation link. "
            "Check your inbox and spam folder to finish signing up.")
UNAVAILABLE = "Newsletter signup is being set up. Please try again later or contact heataheadnyc@gmail.com."
DELIVERY_FAILED = "We couldn't send the confirmation email. Please try again shortly."
EMAIL = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,63}$", re.I)


class Budget:
    """A bounded warm-worker send budget, not a distributed global quota."""
    def __init__(self):
        self.lock, self.calls = threading.Lock(), deque()

    def take(self):
        now = time.monotonic()
        with self.lock:
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= 20:
                return False
            self.calls.append(now)
            return True


def _state():
    return current_app.extensions["heatahead_newsletter"]


def _site_url():
    return mailer.SITE_URL.rstrip("/")


def delivery_ready():
    return (not _state()["on_vercel"]() and len(current_app.secret_key or "") >= 32
            and all(os.environ.get(key) for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM")))


def _database():
    # A Vercel function must never silently save subscribers in /tmp.
    if _state()["on_vercel"]():
        return None
    con = _state()["database"]()
    con.execute("""CREATE TABLE IF NOT EXISTS newsletter_subscribers (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','subscribed','unsubscribed')),
        generation INTEGER NOT NULL, created INTEGER NOT NULL,
        last_requested INTEGER NOT NULL, confirmed INTEGER,
        consent_version TEXT NOT NULL, delivery_failed INTEGER NOT NULL DEFAULT 0)""")
    con.commit()
    return con


def _serializer(purpose):
    return URLSafeTimedSerializer(current_app.secret_key,
                                  salt="heatahead-newsletter-" + purpose,
                                  signer_kwargs={"digest_method": hashlib.sha256})


def _token(identifier, purpose, generation=None):
    data = dict(id=identifier)
    if generation is not None:
        data["generation"] = generation
    return _serializer(purpose).dumps(data)


def _read_token(token, purpose):
    if not isinstance(token, str) or len(token) > 1024 or len(current_app.secret_key or "") < 32:
        return None
    try:
        data = _serializer(purpose).loads(token, max_age=CONFIRM_TTL if purpose == "confirm" else None)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(data.get("id", ""))):
        return None
    if purpose == "confirm" and (type(data.get("generation")) is not int or data["generation"] < 1):
        return None
    return data


def _reply(body, status=200):
    if request.is_json:
        return jsonify(body), status
    return render_template("newsletter_message.html", title="Project updates",
                           message=body.get("message") or body.get("error"), action=None), status


def _origin_allowed():
    return request.headers.get("Origin") in {request.host_url.rstrip("/"), _site_url()}


def _forward(body):
    target = _state()["forward_url"]()
    if not target:
        return None
    try:
        # These are public opt-in actions, not a claim of a verified account.
        response = requests.post(target + request.path, json=body,
                                 headers={"Origin": _site_url()}, timeout=(2, 6), allow_redirects=False)
        result = response.json()
        if response.status_code not in {200, 400, 403, 410, 429, 503} or not isinstance(result, dict):
            return _reply(dict(error=UNAVAILABLE), 503)
        # Require the public contract, rather than treating an arbitrary 200 as saved.
        if response.status_code == 200 and result.get("ok") is True and isinstance(result.get("message"), str):
            clean = dict(ok=True, message=result["message"])
        elif response.status_code != 200 and isinstance(result.get("error"), str):
            clean = dict(error=result["error"])
        else:
            return _reply(dict(error=UNAVAILABLE), 503)
        return _reply(clean, response.status_code)
    except (requests.RequestException, ValueError):
        return _reply(dict(error=UNAVAILABLE), 503)


def _subscribe(data):
    if not delivery_ready():
        return _reply(dict(error=UNAVAILABLE), 503)
    email, name = data["email"], data["name"]
    now = int(time.time())
    con = _database()
    if con is None:
        return _reply(dict(error=UNAVAILABLE), 503)
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT id,status,generation,last_requested,delivery_failed FROM newsletter_subscribers WHERE email=?",
                      (email,)).fetchone()
    if row and (row[1] == "subscribed" or (row[1] == "pending" and row[3] > now - RESEND_DELAY)):
        con.commit()
        if row[1] != "subscribed" and row[4]:
            return _reply(dict(error=DELIVERY_FAILED), 503)
        return _reply(dict(ok=True, message=ACCEPTED))
    if not _state()["budget"].take():
        con.rollback()
        return _reply(dict(error="Too many signup requests. Please try again in a minute."), 429)
    identifier, generation = (row[0], row[2] + 1) if row else (secrets.token_hex(16), 1)
    if row:
        con.execute("""UPDATE newsletter_subscribers SET name=?,status='pending',generation=?,
                       last_requested=?,consent_version=?,delivery_failed=0,confirmed=NULL WHERE id=?""",
                    (name, generation, now, CONSENT_VERSION, identifier))
    else:
        con.execute("""INSERT INTO newsletter_subscribers
                       (id,email,name,status,generation,created,last_requested,confirmed,consent_version)
                       VALUES (?,?,?,'pending',?,?,?,NULL,?)""",
                    (identifier, email, name, generation, now, now, CONSENT_VERSION))
    con.commit()
    confirm = _site_url() + "/newsletter/confirm?" + urlencode(dict(token=_token(identifier, "confirm", generation)))
    unsubscribe = _site_url() + "/newsletter/unsubscribe?" + urlencode(dict(token=_token(identifier, "unsubscribe")))
    msg = mailer.make_msg(email, "Confirm your HeatAhead project updates", "\n".join([
        "You asked to receive HeatAhead project updates.", "",
        "Confirm your email using this link, then choose Confirm subscription:", confirm, "",
        "This confirmation link expires in 24 hours. Newsletter updates are separate from building heat alerts.",
        "If you didn't request this, ignore this email; you won't be subscribed.", "",
        "Stop project updates: " + unsubscribe, "Questions? " + CONTACT_EMAIL,
    ]))
    msg["Reply-To"] = CONTACT_EMAIL
    if not mailer.send(msg):
        # Keep pending, never active; allow a retry after one minute, without a send loop.
        con.execute("UPDATE newsletter_subscribers SET delivery_failed=1,last_requested=? WHERE id=? AND generation=?",
                    (now - RESEND_DELAY + 60, identifier, generation))
        con.commit()
        return _reply(dict(error=DELIVERY_FAILED), 503)
    return _reply(dict(ok=True, message=ACCEPTED))


@bp.get("/contact")
def contact():
    return render_template("contact.html", page="contact", contact_email=CONTACT_EMAIL)


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html", page="privacy", contact_email=CONTACT_EMAIL)


@bp.post("/api/newsletter/subscribe")
def subscribe():
    if not _origin_allowed():
        return _reply(dict(error="Please submit the form from HeatAhead."), 403)
    if request.content_length and request.content_length > 2048:
        return _reply(dict(error="Please use just your name and email address."), 400)
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data, dict):
        return _reply(dict(error="Enter your email address to subscribe."), 400)
    if data.get("website"):
        return _reply(dict(ok=True, message=ACCEPTED))
    email, name = data.get("email", ""), data.get("name", "")
    if (not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email.strip())
            or ".." in email or not isinstance(name, str) or len(name) > 80
            or any(ord(c) < 32 for c in name)):
        return _reply(dict(error="Enter a valid email address and a name of 80 characters or fewer."), 400)
    if data.get("consent") is not True and data.get("consent") != "yes":
        return _reply(dict(error="Choose Subscribe to request project updates."), 400)
    cleaned = dict(email=email.strip().lower(), name=name.strip(), consent=True)
    forwarded = _forward(cleaned)
    if forwarded is not None:
        return forwarded
    try:
        return _subscribe(cleaned)
    except sqlite3.Error:
        current_app.logger.warning("Newsletter storage is unavailable")
        return _reply(dict(error=UNAVAILABLE), 503)


def _landing(purpose):
    token = request.args.get("token", "")
    if not _read_token(token, purpose):
        message = ("The link is invalid or has expired. You can request a new signup link below."
                   if purpose == "confirm" else
                   "This unsubscribe link isn't valid. Contact heataheadnyc@gmail.com for help stopping project updates.")
        return render_template("newsletter_message.html", title="This link isn't available",
                               message=message, action=None), 410
    title = "Confirm your subscription" if purpose == "confirm" else "Stop project updates?"
    message = ("Choose Confirm subscription to receive HeatAhead project updates."
               if purpose == "confirm" else "You can stop newsletter emails here. Your building heat alerts will stay as you set them.")
    return render_template("newsletter_message.html", title=title, message=message,
                           action=purpose, token=token)


@bp.get("/newsletter/confirm")
def confirmation_page():
    return _landing("confirm")


@bp.get("/newsletter/unsubscribe")
def unsubscribe_page():
    return _landing("unsubscribe")


def _change(purpose):
    if not _origin_allowed():
        return _reply(dict(error="Please use the confirmation page on HeatAhead."), 403)
    body = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    token = body.get("token") if isinstance(body, dict) else None
    data = _read_token(token, purpose)
    if not data:
        message = ("The link is invalid or has expired. Please request a new signup link."
                   if purpose == "confirm" else
                   "This unsubscribe link isn't valid. Contact heataheadnyc@gmail.com for help stopping project updates.")
        return _reply(dict(error=message), 410)
    forwarded = _forward(dict(token=token))
    if forwarded is not None:
        return forwarded
    con = _database()
    if con is None:
        return _reply(dict(error="The newsletter service is unavailable. Please try this link again later."), 503)
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT status,generation FROM newsletter_subscribers WHERE id=?", (data["id"],)).fetchone()
    if not row:
        con.rollback()
        return _reply(dict(error="This subscription link is no longer available."), 410)
    if purpose == "confirm":
        if row[1] != data["generation"] or row[0] == "unsubscribed":
            con.rollback()
            return _reply(dict(error="This confirmation link has been replaced. Please use the newest email."), 410)
        con.execute("""UPDATE newsletter_subscribers SET status='subscribed',confirmed=?
                       WHERE id=? AND status='pending' AND generation=?""",
                    (int(time.time()), data["id"], data["generation"]))
        message = "You're subscribed. Thanks for following HeatAhead."
    else:
        con.execute("""UPDATE newsletter_subscribers SET status='unsubscribed',generation=generation+1
                       WHERE id=? AND status!='unsubscribed'""", (data["id"],))
        message = "You've stopped project updates. Your building heat-alert settings haven't changed."
    con.commit()
    return _reply(dict(ok=True, message=message))


@bp.post("/api/newsletter/confirm")
def confirm():
    return _change_safely("confirm")


@bp.post("/api/newsletter/unsubscribe")
def unsubscribe():
    return _change_safely("unsubscribe")


def _change_safely(purpose):
    try:
        return _change(purpose)
    except sqlite3.Error:
        current_app.logger.warning("Newsletter storage is unavailable")
        return _reply(dict(error="The newsletter service is unavailable. Please try this link again later."), 503)


def init_app(app, database, forward_url, on_vercel):
    app.extensions["heatahead_newsletter"] = dict(database=database, forward_url=forward_url,
                                                 on_vercel=on_vercel, budget=Budget())
    app.register_blueprint(bp)

    @app.after_request
    def newsletter_headers(response):
        if request.path.startswith(("/newsletter/", "/api/newsletter/")):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response
