"""Google identity, signed browser sessions, and authenticated backend requests.

Google SDKs are loaded only on the web sign-in path. The LinuxONE registration
service only needs Flask/itsdangerous to verify the website's short-lived requests.
No Google access, refresh, or ID token is kept in the browser session.
"""

import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template,
                   request, session, url_for)
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature, URLSafeTimedSerializer

bp = Blueprint("accounts", __name__)
PRIVATE_ENDPOINTS = {"api_register", "api_my_buildings", "api_remove_registration",
                     "api_account_email_link", "api_account_email_consume",
                     "api_panels_get", "api_panels_set"}
FORWARD_PATHS = {"/api/register", "/api/my_buildings", "/api/account/remove",
                 "/api/account/email_link", "/api/account/email_consume",
                 "/api/account/panels"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# T14: passwordless email sign-in. The link token is signed with the shared
# secret, lives EMAIL_LINK_MAX_AGE seconds and is consumed one-use on the
# durable backend; no password is ever stored or accepted.
EMAIL_LINK_SALT = "heatahead-email-link-v1"
EMAIL_LINK_MAX_AGE = 900
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email",
          "https://www.googleapis.com/auth/userinfo.profile"]


class AuthSessionInterface(SecureCookieSessionInterface):
    digest_method = staticmethod(hashlib.sha256)


def _key_ready():
    return len(current_app.secret_key or "") >= 32


def configured():
    return bool(_key_ready() and current_app.config.get("GOOGLE_CLIENT_ID") and
                current_app.config.get("GOOGLE_CLIENT_SECRET") and
                current_app.config.get("AUTH_BASE_URL") and
                importlib.util.find_spec("google_auth_oauthlib"))


def email_configured():
    backend = current_app.config.get("ACCOUNT_EMAIL_BACKEND")
    return bool(_key_ready() and current_app.config.get("AUTH_BASE_URL") and
                backend and backend["ready"]())


def email_identity(email):
    """A stable non-Google subject for an email account; the email is the identity."""
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]
    return dict(sub="email:" + digest, email=email, name="")


def _profile(value):
    if not isinstance(value, dict):
        return None
    sub, email = value.get("sub"), value.get("email")
    if not isinstance(sub, str) or not 1 <= len(sub) <= 255:
        return None
    if not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email):
        return None
    return dict(sub=sub, email=email.lower(), name=str(value.get("name") or "")[:100])


def _browser_user():
    user = _profile(session.get("auth_user"))
    if user and session.get("auth_expires", 0) > time.time():
        return user
    if user:
        session.clear()
    return None


def user():
    return getattr(g, "account_user", None)


def _equal(left, right):
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except UnicodeError:
        return False


def csrf_token():
    if not _key_ready():
        return ""
    if "auth_csrf" not in session:
        session["auth_csrf"] = secrets.token_urlsafe(32)
    return session["auth_csrf"]


def _csrf_ok():
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else request.form
    supplied = request.headers.get("X-CSRF-Token") or body.get("csrf_token") or ""
    expected = session.get("auth_csrf") or ""
    return bool(expected) and _equal(supplied, expected)


def safe_next(value):
    if not isinstance(value, str) or len(value) > 1200 or "\\" in value or any(ord(c) < 32 for c in value):
        return "/"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "/"
    if parts.scheme or parts.netloc or parts.path not in {"/", "/map", "/building", "/monitor", "/unsubscribe", "/learn-more", "/faq", "/about"}:
        return "/"
    return value


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt,
                                  signer_kwargs={"digest_method": hashlib.sha256})


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def signed_forward(method, path, actor, body=b"", params=None):
    """Bind a one-use identity assertion to the exact request, not a bearer login."""
    if not _key_ready() or path not in FORWARD_PATHS or not _profile(actor):
        raise ValueError("account forwarding is not configured")
    pairs = sorted((str(k), str(v)) for k, v in (params or {}).items() if v is not None)
    target = path + ("?" + urlencode(pairs) if pairs else "")
    nonce = secrets.token_urlsafe(24)
    claims = dict(user=_profile(actor), method=method.upper(), target=target,
                  digest=_digest(body), nonce=nonce)
    token = _serializer("heatahead-request-v1").dumps(claims)
    return target, {"X-HeatAhead-Identity": token}, nonce


def verify_reply(response, nonce):
    token = response.headers.get("X-HeatAhead-Reply", "")
    try:
        claims = _serializer("heatahead-reply-v1").loads(token, max_age=60)
        return (claims.get("nonce") == nonce and claims.get("status") == response.status_code and
                hmac.compare_digest(claims.get("digest", ""), _digest(response.content)))
    except (BadSignature, ValueError, TypeError, AttributeError):
        return False


def _proxy_user(nonce_guard):
    token = request.headers.get("X-HeatAhead-Identity", "")
    try:
        claims = _serializer("heatahead-request-v1").loads(token, max_age=60)
        actor = _profile(claims.get("user"))
        query = request.query_string.decode("ascii")
        target = request.path + ("?" + query if query else "")
        nonce = claims.get("nonce")
        if (not actor or request.path not in FORWARD_PATHS or
                claims.get("method") != request.method or claims.get("target") != target or
                not hmac.compare_digest(claims.get("digest", ""), _digest(request.get_data())) or
                not isinstance(nonce, str) or not 20 <= len(nonce) <= 100):
            return None
        if not nonce_guard(nonce):
            return None
        g.account_proxy_nonce = nonce
        return actor
    except (BadSignature, ValueError, TypeError, AttributeError, UnicodeError):
        return None


def _error(message, status=400):
    return render_template("auth_message.html", title="Sign-in", message=message), status


def _flow(state=None, verifier=None):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config({"web": {
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token"}}, scopes=SCOPES, state=state,
        redirect_uri=current_app.config["AUTH_BASE_URL"] + "/api/auth/callback",
        code_verifier=verifier, autogenerate_code_verifier=verifier is None)


def _verify_id_token(token):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token

    class BoundedRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs["timeout"] = 3
            return super().__call__(*args, **kwargs)

    return verify_oauth2_token(token, BoundedRequest(), current_app.config["GOOGLE_CLIENT_ID"])


@bp.get("/api/auth/google")
def google_start():
    if not configured():
        return _error("Google sign-in is being set up. You can still explore the map and building records.", 503)
    destination = safe_next(request.args.get("next", "/"))
    remember = (request.args.getlist("remember") or ["1"])[-1] == "1"
    origin = current_app.config["AUTH_BASE_URL"]
    if request.host_url.rstrip("/") != origin:
        return redirect(origin + "/api/auth/google?" + urlencode({"next": destination, "remember": int(remember)}))
    if user():
        return redirect(destination)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    flow = _flow(state=state)
    location, state = flow.authorization_url(access_type="online", prompt="select_account", nonce=nonce)
    session["google_pending"] = dict(state=state, nonce=nonce, verifier=flow.code_verifier,
                                     started=time.time(), next=destination, remember=remember)
    return redirect(location)


@bp.get("/api/auth/callback")
def google_callback():
    if not configured():
        return _error("Google sign-in is being set up. Please try again shortly.", 503)
    pending = session.get("google_pending")
    state = request.args.get("state", "")
    if (request.host_url.rstrip("/") != current_app.config["AUTH_BASE_URL"] or
            not isinstance(pending, dict) or not isinstance(pending.get("state"), str) or
            not _equal(state, pending["state"]) or
            not 0 <= time.time() - pending.get("started", 0) <= 600):
        return _error("That sign-in link expired or could not be verified. Please start Google sign-in again.")
    session.pop("google_pending", None)
    if request.args.get("error"):
        return _error("Sign-in was cancelled. You can try again whenever you are ready.")
    code = request.args.get("code")
    if not code or len(code) > 4096:
        return _error("Google did not complete sign-in. Please try again.")
    try:
        flow = _flow(state=pending["state"], verifier=pending["verifier"])
        tokens = flow.fetch_token(code=code, timeout=4)
        claims = _verify_id_token(tokens["id_token"])
        profile = _profile(claims)
        if (not profile or claims.get("email_verified") is not True or
                claims.get("azp", current_app.config["GOOGLE_CLIENT_ID"]) != current_app.config["GOOGLE_CLIENT_ID"] or
                not isinstance(claims.get("nonce"), str) or
                not _equal(claims["nonce"], pending["nonce"])):
            return _error("Google could not verify this account. Please try signing in again.")
    except Exception:
        # Token responses and authorization codes must never enter a log or error page.
        return _error("Google sign-in could not finish. Please try again in a moment.", 503)
    session.clear()
    session["auth_user"] = profile
    session["auth_expires"] = time.time() + (30 * 86400 if pending["remember"] else 12 * 3600)
    session.permanent = bool(pending["remember"])
    csrf_token()
    return redirect(safe_next(pending.get("next")))


# per-warm-worker budget for sign-in emails, like the guide AI budget: not a
# distributed quota, just a brake on one worker being used as a mail cannon.
_EMAIL_SENDS = []


def _email_budget_ok(email, now):
    _EMAIL_SENDS[:] = [(t, e) for t, e in _EMAIL_SENDS if t > now - 600]
    recent = [(t, e) for t, e in _EMAIL_SENDS if t > now - 60]
    return sum(1 for _, e in recent if e == email) < 3 and len(recent) < 20


@bp.post("/api/auth/email")
def email_start():
    if not email_configured():
        return jsonify(error="Email sign-in is being set up. You can still explore "
                             "the map and building records.", code="email_not_configured"), 503
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else request.form
    email = str(body.get("email") or "").strip().lower()
    remember = str(body.get("remember", "1")).lower() in ("1", "true")
    if len(email) > 254 or not EMAIL.fullmatch(email):
        return jsonify(error="That does not look like an email address."), 400
    now = time.time()
    if not _email_budget_ok(email, now):
        return jsonify(error="Too many sign-in emails just now. Please wait a minute "
                             "and try again."), 429
    nonce = secrets.token_urlsafe(24)
    token = _serializer(EMAIL_LINK_SALT).dumps(dict(email=email, remember=remember, nonce=nonce))
    link = (current_app.config["AUTH_BASE_URL"] + "/api/auth/email/callback?" +
            urlencode({"token": token}))
    if not current_app.config["ACCOUNT_EMAIL_BACKEND"]["send_link"](email, link):
        return jsonify(error="The sign-in email could not be sent right now. "
                             "Please try again shortly.", code="email_unavailable"), 503
    _EMAIL_SENDS.append((now, email))
    return jsonify(ok=True, message="Check your inbox - the sign-in link works once, "
                                    "for 15 minutes.")


@bp.get("/api/auth/email/callback")
def email_callback():
    if not email_configured():
        return _error("Email sign-in is being set up. Please try again shortly.", 503)
    token = request.args.get("token", "")
    if not token or len(token) > 2048:
        return _error("That sign-in link is not valid. Please request a new one from the home page.")
    try:
        claims = _serializer(EMAIL_LINK_SALT).loads(token, max_age=EMAIL_LINK_MAX_AGE)
    except (BadSignature, ValueError, TypeError):
        return _error("That sign-in link expired or is not valid. Sign-in links work "
                      "for 15 minutes; please request a new one from the home page.")
    email = str(claims.get("email") or "").lower() if isinstance(claims, dict) else ""
    nonce = claims.get("nonce") if isinstance(claims, dict) else None
    if (len(email) > 254 or not EMAIL.fullmatch(email) or
            not isinstance(nonce, str) or not 20 <= len(nonce) <= 100):
        return _error("That sign-in link is not valid. Please request a new one from the home page.")
    fresh = current_app.config["ACCOUNT_EMAIL_BACKEND"]["consume"](nonce, email)
    if fresh is None:
        return _error("Sign-in is temporarily unavailable. Please open your link "
                      "again in a moment.", 503)
    if not fresh:
        return _error("That sign-in link was already used. Please request a new one "
                      "from the home page.")
    remember = bool(claims.get("remember"))
    session.clear()
    session["auth_user"] = email_identity(email)
    session["auth_expires"] = time.time() + (30 * 86400 if remember else 12 * 3600)
    session.permanent = remember
    csrf_token()
    return redirect("/")


@bp.get("/api/auth/session")
def session_status():
    return jsonify(user=user(), google_ready=configured(), email_ready=email_configured(),
                   csrf_token=csrf_token() if user() else None)


@bp.post("/api/auth/logout")
def logout():
    if not _csrf_ok():
        return _error("Please refresh the page and try signing out again.", 403)
    session.clear()
    return redirect("/")


def init_app(app, nonce_guard, email_backend=None):
    key = os.environ.get("FLASK_SECRET_KEY", "")
    origin = os.environ.get("AUTH_BASE_URL", os.environ.get("SITE_URL", "https://ibmsubmission.vercel.app")).rstrip("/")
    allow_http = os.environ.get("AUTH_HTTP_DEVELOPMENT") == "1"
    try:
        parsed = urlsplit(origin)
        valid_origin = (parsed.scheme == "https" or (allow_http and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}))
        if not valid_origin or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            origin = ""
    except ValueError:
        origin = ""
    app.config.update(SECRET_KEY=key if len(key) >= 32 else None,
                      GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID", ""),
                      GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                      AUTH_BASE_URL=origin, SESSION_COOKIE_NAME="heatahead_account",
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=not allow_http,
                      SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_PATH="/",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=30), SESSION_REFRESH_EACH_REQUEST=False,
                      MAX_CONTENT_LENGTH=64 * 1024,
                      ACCOUNT_EMAIL_BACKEND=email_backend)
    app.session_interface = AuthSessionInterface()
    app.register_blueprint(bp)

    @app.before_request
    def account_identity():
        g.account_user = _browser_user()
        if request.endpoint not in PRIVATE_ENDPOINTS:
            return None
        if not _key_ready():
            return jsonify(error="Account sign-in is being set up. Please try again shortly.", code="auth_not_configured"), 503
        if request.headers.get("X-HeatAhead-Identity"):
            g.account_user = _proxy_user(nonce_guard)
            if not g.account_user:
                return jsonify(error="The account request could not be verified.", code="invalid_identity"), 401
        if not user():
            return jsonify(error="Sign in to manage your buildings.", code="sign_in_required"), 401
        if request.method == "POST" and not getattr(g, "account_proxy_nonce", None) and not _csrf_ok():
            return jsonify(error="Your session changed. Refresh the page and try again.", code="csrf_failed"), 403
        return None

    @app.after_request
    def account_response(response):
        if request.endpoint in PRIVATE_ENDPOINTS or request.path.startswith("/api/auth/") or response.mimetype == "text/html":
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.vary.add("Cookie")
        nonce = getattr(g, "account_proxy_nonce", None)
        if nonce:
            response.headers["X-HeatAhead-Reply"] = _serializer("heatahead-reply-v1").dumps(
                dict(nonce=nonce, status=response.status_code, digest=_digest(response.get_data())))
        return response

    @app.context_processor
    def account_context():
        return dict(account_user=user(), google_ready=configured(),
                    email_ready=email_configured(), account_csrf=csrf_token() if user() else "")
