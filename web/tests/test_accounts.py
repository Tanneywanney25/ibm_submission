"""Authentication and account-boundary tests; no live Google users or emails.

Run: python -m unittest discover -s web/tests -v
Google's real OAuth and signature-validation libraries run against an in-process
provider fixture. Registration forwarding uses two real Flask apps and SQLite.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import uuid

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
import account_auth as auth

ORIGIN = "https://heatahead.test"
CLIENT_ID = "test.apps.googleusercontent.com"
SECRET = "test-only-session-key-" + "x" * 48


def application(database, forward="", secret=SECRET, google=True, vercel=False):
    env = dict(APP_MODE="lite", REGISTER_FORWARD_URL=forward, FLASK_SECRET_KEY=secret,
               GOOGLE_CLIENT_ID=CLIENT_ID if google else "",
               GOOGLE_CLIENT_SECRET="test-only-google-secret" if google else "",
               AUTH_BASE_URL=ORIGIN, AUTH_HTTP_DEVELOPMENT="0")
    with patch.dict(os.environ, env):
        previous = os.environ.pop("VERCEL", None)
        if vercel:
            os.environ["VERCEL"] = "1"
        try:
            name = "test_web_" + uuid.uuid4().hex
            spec = importlib.util.spec_from_file_location(name, ROOT / "web/app.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        finally:
            os.environ.pop("VERCEL", None)
            if previous is not None:
                os.environ["VERCEL"] = previous
    module.DB = Path(database)
    module.app.testing = True
    return module


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption())
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "accounts.db"
        self.module = application(self.db)
        self.client = self.module.app.test_client()
        self.mail_patch = patch("mailer.send", return_value=True)
        self.mail_patch.start()
        self.addCleanup(self.mail_patch.stop)
        auth._EMAIL_SENDS.clear()
        auth._PASSWORD_TRIES.clear()

    def get(self, path, client=None, **kw):
        return (client or self.client).get(path, base_url=ORIGIN, **kw)

    def actor(self, client=None, email="person@example.test", sub="google-user-1"):
        client = client or self.client
        with client.session_transaction(base_url=ORIGIN) as session:
            session["auth_user"] = dict(sub=sub, email=email, name="Example Person")
            session["auth_expires"] = time.time() + 86400
            session["auth_csrf"] = "csrf-for-tests"
            session.permanent = True

    def post(self, path, body, client=None, csrf="csrf-for-tests", **kw):
        return (client or self.client).post(path, base_url=ORIGIN, json=body,
                                            headers={"X-CSRF-Token": csrf}, **kw)

    def login(self, remember=True, changes=None, provider_error=False):
        response = self.get("/api/auth/google?next=/building?bbl=3000410007&remember=" + str(int(remember)))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        with self.client.session_transaction(base_url=ORIGIN) as session:
            pending = dict(session["google_pending"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [challenge])
        now = int(time.time())
        claims = dict(iss="https://accounts.google.com", aud=CLIENT_ID, sub="google-user-1",
                      email="person@example.test", email_verified=True, name="Example Person",
                      iat=now, exp=now + 3600, nonce=pending["nonce"])
        claims.update(changes or {})
        token = jwt.encode(crypt.RSASigner.from_string(self.private), claims, key_id="test-key").decode()
        calls = []

        def provider(session, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if provider_error:
                raise requests.Timeout("provider timeout")
            response = requests.Response()
            response.status_code = 200
            response.url = url
            response.request = requests.Request(method, url).prepare()
            response.headers["Content-Type"] = "application/json"
            if url == "https://oauth2.googleapis.com/token":
                body = dict(access_token="test-access-token", token_type="Bearer", expires_in=3600,
                            id_token=token, scope=" ".join(auth.SCOPES))
            elif url == "https://www.googleapis.com/oauth2/v1/certs":
                body = {"test-key": self.public}
            else:
                raise AssertionError("Unexpected provider URL: " + url)
            response._content = json.dumps(body).encode()
            return response

        with patch("requests.sessions.Session.request", new=provider):
            result = self.get("/api/auth/callback?state=" + pending["state"] + "&code=test-code")
        return result, pending, calls

    def test_google_pkce_signature_and_remembered_session(self):
        response, pending, calls = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/building?bbl=3000410007")
        token_call = next(c for c in calls if c[1].endswith("/token"))
        data = token_call[2]["data"]
        body = {k: [v] for k, v in data.items()} if isinstance(data, dict) else parse_qs(data)
        self.assertEqual(body["code_verifier"], [pending["verifier"]])
        self.assertEqual(body["code"], ["test-code"])
        cookie = response.headers["Set-Cookie"]
        for flag in ["Secure", "HttpOnly", "SameSite=Lax", "Expires="]:
            self.assertIn(flag, cookie)
        with self.client.session_transaction(base_url=ORIGIN) as session:
            self.assertEqual(session["auth_user"]["email"], "person@example.test")
            self.assertNotIn("google_pending", session)
            for value in ["test-access-token", token_call[2].get("client_secret", "not-in-session")]:
                self.assertNotIn(value, json.dumps(dict(session)))
            self.assertGreater(session["auth_expires"], time.time() + 29 * 86400)
        state = self.get("/api/auth/session")
        self.assertEqual(state.json["user"]["sub"], "google-user-1")
        self.assertIn("no-store", state.headers["Cache-Control"])
        replay = self.get("/api/auth/callback?state=" + pending["state"] + "&code=test-code")
        self.assertEqual(replay.status_code, 400)

    def test_no_remember_has_no_persistent_cookie(self):
        response, _, _ = self.login(remember=False)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("Expires=", response.headers["Set-Cookie"])

    def test_google_claims_are_verified(self):
        cases = [dict(aud="another-client"), dict(iss="https://attacker.test"),
                 dict(exp=int(time.time()) - 60), dict(nonce="wrong"),
                 dict(email_verified=False), dict(azp="another-client")]
        for changes in cases:
            with self.subTest(changes=changes):
                self.client = self.module.app.test_client()
                response, _, _ = self.login(changes=changes)
                self.assertIn(response.status_code, (400, 503))
                self.assertIsNone(self.get("/api/auth/session").json["user"])

    def test_state_expiry_cancellation_and_provider_failure(self):
        self.get("/api/auth/google")
        wrong = self.get("/api/auth/callback?state=wrong&code=x")
        self.assertEqual(wrong.status_code, 400)
        with self.client.session_transaction(base_url=ORIGIN) as session:
            state = session["google_pending"]["state"]
        cancelled = self.get("/api/auth/callback?state=" + state + "&error=access_denied")
        self.assertEqual(cancelled.status_code, 400)
        self.assertIn(b"cancelled", cancelled.data)
        self.get("/api/auth/google")
        with self.client.session_transaction(base_url=ORIGIN) as session:
            pending = dict(session["google_pending"])
            pending["started"] = time.time() - 601
            session["google_pending"] = pending
        expired = self.get("/api/auth/callback?state=" + pending["state"] + "&code=x")
        self.assertEqual(expired.status_code, 400)
        result, _, _ = self.login(provider_error=True)
        self.assertEqual(result.status_code, 503)
        self.assertIsNone(self.get("/api/auth/session").json["user"])

    def test_open_redirects_and_origin_binding(self):
        with self.module.app.app_context():
            for value in ["https://evil.test", "//evil.test", "//[", "/\\evil.test", "/unknown", "/\nfoo"]:
                self.assertEqual(auth.safe_next(value), "/")
        response = self.client.get("/api/auth/google", base_url="https://preview.test")
        self.assertTrue(response.location.startswith(ORIGIN + "/api/auth/google?"))

    def test_account_identity_csrf_and_malformed_requests(self):
        self.assertEqual(self.get("/api/my_buildings").status_code, 401)
        self.actor()
        self.assertEqual(self.post("/api/register", {}, csrf="wrong").status_code, 403)
        wrong_email = self.post("/api/register", dict(role="viewer", email="another@example.test"))
        self.assertEqual(wrong_email.status_code, 403)
        self.assertEqual(self.get("/api/my_buildings?email=another@example.test").status_code, 403)
        self.assertEqual(self.post("/api/register", [1]).status_code, 400)
        self.assertEqual(self.post("/api/account/remove", [1]).status_code, 400)
        self.assertEqual(self.client.post("/api/register", base_url=ORIGIN,
                         json={}, headers={"X-CSRF-Token":"wrong-☃"}).status_code, 403)

    def test_accounts_cannot_list_or_remove_each_others_buildings(self):
        self.actor()
        self.post("/api/register", dict(role="tenant", bbl="3000410007"))
        another = self.module.app.test_client()
        self.actor(another, email="another@example.test", sub="google-user-2")
        self.assertEqual(self.get("/api/my_buildings", client=another).json["total"], 0)
        removed = self.post("/api/account/remove", dict(bbl="3000410007"), client=another)
        self.assertEqual(removed.json["removed"], 0)
        self.assertEqual(self.get("/api/my_buildings").json["total"], 1)

    def test_one_account_type_saves_buildings_without_a_role(self):
        self.actor()
        page = self.get("/")
        self.assertIn(b"Your profile", page.data)
        self.assertNotIn(b'name="role"', page.data)
        missing = self.post("/api/register", dict(phone=""))
        self.assertEqual(missing.status_code, 400)
        with patch("mailer.welcome_email", return_value=object()) as welcome:
            saved = self.post("/api/register", dict(bbl="3000410007"))
            self.assertEqual(saved.status_code, 200)
            self.assertFalse(saved.json["already_registered"])
            again = self.post("/api/register", dict(bbl="3000410007"))
            self.assertTrue(again.json["already_registered"])
        self.assertEqual(welcome.call_count, 1, "welcome email once per new building, never on a repeat")
        self.assertEqual(welcome.call_args.args[0], "person@example.test")
        self.assertEqual(welcome.call_args.kwargs["bbl"], 3000410007)
        registrations = self.get("/api/my_buildings").json["registrations"]
        self.assertEqual(registrations, [dict(role="tenant", bbl=3000410007)])
        legacy = self.post("/api/register", dict(role="landlord", bbl="3000410007"))
        self.assertEqual(legacy.status_code, 200, "older clients that still send a role keep working")

    def test_welcome_email_text_has_no_role(self):
        import mailer
        with patch.object(mailer, "make_msg", side_effect=lambda to, subject, body: body):
            body = mailer.welcome_email("person@example.test", bbl=3000410007, p_season=0.42)
        self.assertNotIn(" as a ", body)
        self.assertIn("unsubscribe", body.lower())

    def test_panels_validate_round_trip_and_stay_per_account(self):
        self.assertEqual(self.get("/api/account/panels").status_code, 401)
        self.actor()
        self.assertEqual(self.post("/api/account/panels", dict(panels=["queue"]),
                                   csrf="wrong").status_code, 403)
        for bad in [dict(panels=["nope"]), dict(panels="queue"), dict(panels=["queue", "queue"]),
                    dict(), [1]]:
            self.assertEqual(self.post("/api/account/panels", bad).status_code, 400, bad)
        self.assertIsNone(self.get("/api/account/panels").json["panels"])
        saved = self.post("/api/account/panels", dict(panels=["stats", "buildings"]))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json["panels"], ["buildings", "stats"])  # fixed display order
        self.assertEqual(self.get("/api/account/panels").json["panels"], ["buildings", "stats"])
        self.assertEqual(self.post("/api/account/panels", dict(panels=[])).json["panels"], [])
        another = self.module.app.test_client()
        self.actor(another, email="another@example.test", sub="google-user-2")
        self.assertIsNone(self.get("/api/account/panels", client=another).json["panels"])
        page = self.get("/")
        for marker in [b"Your dashboard", b"panel-buildings", b"panel-audit",
                       b"panel-queue", b"panel-stats"]:
            self.assertIn(marker, page.data)

    def test_panels_forward_to_backend_and_fail_closed_on_vercel(self):
        backend = self.module.app.test_client()
        website = application(Path(self.directory.name) / "ephemeral.db",
                              forward="https://backend.test", vercel=True)
        client = website.app.test_client()
        self.actor(client)

        def transport(method, url, **kwargs):
            parts = urlsplit(url)
            result = backend.open(parts.path + ("?" + parts.query if parts.query else ""),
                                  method=method, base_url="https://backend.test",
                                  data=kwargs.get("data"), headers=kwargs.get("headers"))
            response = requests.Response()
            response.status_code = result.status_code
            response._content = result.data
            response.headers.update(result.headers)
            return response

        with patch.object(website.requests, "request", side_effect=transport):
            saved = self.post("/api/account/panels", dict(panels=["audit", "buildings"]), client=client)
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(self.get("/api/account/panels", client=client).json["panels"],
                             ["buildings", "audit"])
        with patch.object(website.requests, "request", side_effect=requests.Timeout):
            self.assertEqual(self.get("/api/account/panels", client=client).status_code, 503)
            self.assertEqual(self.post("/api/account/panels", dict(panels=["stats"]),
                                       client=client).status_code, 503)
        self.assertFalse(website.DB.exists(), "Vercel must not keep panel choices in /tmp")

    def test_registered_building_returns_after_restart_and_logout(self):
        self.actor()
        result = self.post("/api/register", dict(role="tenant", bbl="3000410007"))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["durable"])
        saved = self.get("/api/my_buildings")
        self.assertEqual(saved.json["registrations"][0], dict(role="tenant", bbl=3000410007))
        self.assertTrue(any(b["bbl"] == 3000410007 for b in saved.json["buildings"]))
        cookie = self.client.get_cookie("heatahead_account", domain="heatahead.test")
        restarted = application(self.db)
        second = restarted.app.test_client()
        second.set_cookie("heatahead_account", cookie.value, domain="heatahead.test")
        self.assertEqual(self.get("/api/my_buildings", client=second).json["total"], 1)
        page = self.get("/", client=second)
        self.assertIn(b"Your saved buildings", page.data)
        self.assertIn(b"person@example.test", page.data)
        self.assertNotIn(b"Demo: no login", page.data)
        self.assertEqual(second.post("/api/auth/logout", base_url=ORIGIN,
                                    data={"csrf_token": "wrong"}).status_code, 403)
        logout = second.post("/api/auth/logout", base_url=ORIGIN,
                             data={"csrf_token": "csrf-for-tests"})
        self.assertEqual(logout.status_code, 302)
        self.assertIsNone(self.get("/api/auth/session", client=second).json["user"])

    def test_expired_or_tampered_cookie_is_not_logged_in(self):
        self.actor()
        with self.client.session_transaction(base_url=ORIGIN) as session:
            session["auth_expires"] = time.time() - 1
        self.assertEqual(self.get("/api/my_buildings").status_code, 401)
        self.actor()
        cookie = self.client.get_cookie("heatahead_account", domain="heatahead.test")
        self.client.set_cookie("heatahead_account", cookie.value[:-3] + "bad", domain="heatahead.test")
        self.assertEqual(self.get("/api/my_buildings").status_code, 401)

    def test_unsubscribe_requires_identity_and_post_confirmation(self):
        before = self.get("/unsubscribe?email=person@example.test&bbl=3000410007")
        self.assertEqual(before.status_code, 302)
        self.actor()
        self.post("/api/register", dict(role="tenant", bbl="3000410007"))
        confirmation = self.get("/unsubscribe?email=person@example.test&bbl=3000410007")
        self.assertIn(b"Confirm unsubscribe", confirmation.data)
        self.assertEqual(self.get("/api/my_buildings").json["total"], 1)
        self.assertEqual(self.get("/unsubscribe?email=another@example.test").status_code, 403)
        removed = self.post("/api/account/remove", dict(bbl="3000410007"))
        self.assertEqual(removed.json["removed"], 1)
        self.assertEqual(self.get("/api/my_buildings").json["total"], 0)

    def test_unconfigured_signin_does_not_break_public_pages(self):
        missing = application(self.db, secret="", google=False)
        client = missing.app.test_client()
        for path in ["/", "/map", "/building", "/monitor", "/api/reliability", "/api/building/3000410007"]:
            self.assertEqual(self.get(path, client=client).status_code, 200)
        self.assertEqual(self.get("/api/auth/google", client=client).status_code, 503)
        self.assertEqual(self.get("/api/my_buildings", client=client).status_code, 503)

    def request_email_link(self, client=None, email="link@example.test", remember=1):
        """POST /api/auth/email and return (response, same-origin link path or None)."""
        captured = {}

        def record(to, link):
            captured.update(to=to, link=link)
            return object()

        with patch("mailer.sign_in_email", side_effect=record):
            response = self.post("/api/auth/email", dict(email=email, remember=remember),
                                 client=client)
        link = captured.get("link")
        if link:
            self.assertTrue(link.startswith(ORIGIN + "/api/auth/email/callback?token="))
            self.assertEqual(captured["to"], email)
            link = link[len(ORIGIN):]
        return response, link

    def test_email_link_signs_in_once_and_registers(self):
        self.assertEqual(self.post("/api/auth/email", dict(email="not-an-email")).status_code, 400)
        response, link = self.request_email_link()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        signed_in = self.get(link)
        self.assertEqual(signed_in.status_code, 302)
        self.assertEqual(signed_in.location, "/#dashboard")
        with self.client.session_transaction(base_url=ORIGIN) as session:
            self.assertEqual(session["auth_user"]["email"], "link@example.test")
            self.assertTrue(session["auth_user"]["sub"].startswith("email:"))
            self.assertGreater(session["auth_expires"], time.time() + 29 * 86400)
            csrf = session["auth_csrf"]
        state = self.get("/api/auth/session")
        self.assertEqual(state.json["user"]["email"], "link@example.test")
        self.assertTrue(state.json["email_ready"])
        replay = self.get(link)
        self.assertEqual(replay.status_code, 400)
        self.assertIn(b"already used", replay.data)
        saved = self.post("/api/register", dict(role="tenant", bbl="3000410007"), csrf=csrf)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.get("/api/my_buildings").json["total"], 1)
        tampered = self.get(link[:-4] + "zzzz")
        self.assertEqual(tampered.status_code, 400)
        self.assertIn(b"expired or is not valid", tampered.data)

    def test_email_link_short_session_and_rate_limit(self):
        response, link = self.request_email_link(remember=0)
        self.assertEqual(response.status_code, 200)
        signed_in = self.get(link)
        self.assertEqual(signed_in.status_code, 302)
        self.assertNotIn("Expires=", signed_in.headers["Set-Cookie"])
        with self.client.session_transaction(base_url=ORIGIN) as session:
            self.assertLess(session["auth_expires"], time.time() + 13 * 3600)
        for _ in range(2):
            self.assertEqual(self.request_email_link()[0].status_code, 200)
        self.assertEqual(self.request_email_link()[0].status_code, 429)

    def test_email_link_unconfigured_fails_closed(self):
        missing = application(self.db, secret="", google=False)
        client = missing.app.test_client()
        self.assertEqual(self.post("/api/auth/email", dict(email="a@example.test"),
                                   client=client).status_code, 503)
        self.assertEqual(self.get("/api/auth/email/callback?token=x", client=client).status_code, 503)
        lone = application(self.db, vercel=True)
        client = lone.app.test_client()
        self.assertEqual(self.post("/api/auth/email", dict(email="a@example.test"),
                                   client=client).status_code, 503)
        page = self.get("/signin", client=client)
        self.assertIn(b"Password sign-in is unavailable", page.data)

    def test_email_link_needs_smtp_on_the_instance(self):
        self.module.HOST = "linuxone"
        with patch.dict(os.environ, {"SMTP_HOST": ""}):
            self.assertFalse(self.get("/api/auth/session").json["email_ready"])
            self.assertEqual(self.post("/api/auth/email", dict(email="a@example.test")).status_code, 503)
            self.assertFalse(self.get("/api/health").json["email_sign_in"])
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.test"}):
            self.assertTrue(self.get("/api/auth/session").json["email_ready"])
            self.assertEqual(self.request_email_link()[0].status_code, 200)

    def test_email_link_forwards_send_and_consume_to_backend(self):
        backend = self.module.app.test_client()
        website = application(Path(self.directory.name) / "ephemeral.db",
                              forward="https://backend.test", vercel=True)
        client = website.app.test_client()

        def transport(method, url, **kwargs):
            parts = urlsplit(url)
            result = backend.open(parts.path + ("?" + parts.query if parts.query else ""),
                                  method=method, base_url="https://backend.test",
                                  data=kwargs.get("data"), headers=kwargs.get("headers"))
            response = requests.Response()
            response.status_code = result.status_code
            response._content = result.data
            response.headers.update(result.headers)
            return response

        captured = {}

        def record(to, link):
            captured.update(to=to, link=link)
            return object()

        with patch.object(website.requests, "request", side_effect=transport), \
             patch("mailer.sign_in_email", side_effect=record), \
             patch("mailer.SITE_URL", ORIGIN):
            response = self.post("/api/auth/email", dict(email="far@example.test"), client=client)
            self.assertEqual(response.status_code, 200)
            link = captured["link"][len(ORIGIN):]
            with patch.object(website.requests, "request", side_effect=requests.Timeout):
                closed = self.get(link, client=client)
            self.assertEqual(closed.status_code, 503)
            signed_in = self.get(link, client=client)
            self.assertEqual(signed_in.status_code, 302)
            with client.session_transaction(base_url=ORIGIN) as session:
                self.assertEqual(session["auth_user"]["email"], "far@example.test")
            replay = self.get(link, client=client)
            self.assertEqual(replay.status_code, 400)
            self.assertIn(b"already used", replay.data)
        self.assertFalse(website.DB.exists(), "the website side must stay stateless")

    # ---- password accounts: sign up / log in (no email at sign-up)
    def password(self, path, email="pw@example.test", password="correct horse 1", client=None, **extra):
        return (client or self.client).post(path, base_url=ORIGIN,
                                            json=dict(email=email, password=password, **extra))

    def logout(self, client=None):
        with (client or self.client).session_transaction(base_url=ORIGIN) as session:
            session.clear()

    def test_signin_page_has_google_and_both_tabs(self):
        page = self.get("/signin?mode=signup")
        self.assertEqual(page.status_code, 200)
        for text in (b"Continue with Google", b"Log in", b"Sign up", b"Create account",
                     b"Signing up sends no"):
            self.assertIn(text, page.data)
        home = self.get("/").data
        self.assertIn(b'href="/signin">Sign in</a>', home)
        self.assertIn(b'href="/signin?mode=signup"', home)
        self.assertNotIn(b"email_signin_form", home)
        self.actor()
        self.assertEqual(self.get("/signin").location, "/#dashboard")

    def test_password_signup_login_and_saved_buildings_return(self):
        with patch("mailer.send") as sent:
            created = self.password("/api/auth/signup", remember=1)
            self.assertEqual(created.status_code, 200)
            sent.assert_not_called()
        with self.client.session_transaction(base_url=ORIGIN) as session:
            self.assertEqual(session["auth_user"]["email"], "pw@example.test")
            self.assertEqual(session["auth_user"]["sub"], auth.email_identity("pw@example.test")["sub"])
            self.assertEqual(session["auth_method"], "password")
            self.assertGreater(session["auth_expires"], time.time() + 29 * 86400)
            csrf = session["auth_csrf"]
        self.assertIn(b"with your password", self.get("/").data)
        self.assertEqual(self.post("/api/register", dict(bbl="3000410007"), csrf=csrf).status_code, 200)
        self.logout()
        self.assertEqual(self.password("/api/auth/login", password="wrong password").status_code, 401)
        self.assertEqual(self.password("/api/auth/login", email="nobody@example.test").status_code, 401)
        self.assertEqual(self.password("/api/auth/signup").status_code, 409)
        self.assertEqual(self.password("/api/auth/login", remember=0).status_code, 200)
        with self.client.session_transaction(base_url=ORIGIN) as session:
            self.assertLess(session["auth_expires"], time.time() + 13 * 3600)
        self.assertEqual(self.get("/api/my_buildings").json["total"], 1)
        con = self.module.sqlite3.connect(self.db)
        stored = con.execute("SELECT hash FROM passwords").fetchone()[0]
        con.close()
        self.assertNotIn("correct horse", stored)

    def test_password_input_validation_and_rate_limit(self):
        self.assertEqual(self.password("/api/auth/signup", password="short").status_code, 400)
        self.assertEqual(self.password("/api/auth/signup", email="not-an-email").status_code, 400)
        form = self.client.post("/api/auth/signup", base_url=ORIGIN,
                                data=dict(email="pw@example.test", password="correct horse 1"))
        self.assertEqual(form.status_code, 400)
        self.assertEqual(self.password("/api/auth/signup").status_code, 200)
        self.logout()
        codes = [self.password("/api/auth/login", password="wrong password").status_code
                 for _ in range(9)]
        self.assertEqual(codes[:7], [401] * 7)
        self.assertEqual(codes[-1], 429)

    def test_signup_cannot_take_over_an_existing_or_later_proven_address(self):
        # an address that already signed in with Google cannot be claimed by sign-up
        result, _, _ = self.login()
        self.assertEqual(result.status_code, 302)
        self.logout()
        self.assertEqual(self.password("/api/auth/signup", email="person@example.test").status_code, 409)
        # a password set by sign-up (unproven) is dropped once the owner proves the address
        self.assertEqual(self.password("/api/auth/signup", email="link@example.test").status_code, 200)
        self.logout()
        _, link = self.request_email_link()
        self.assertEqual(self.get(link).status_code, 302)
        self.logout()
        self.assertEqual(self.password("/api/auth/login", email="link@example.test").status_code, 401)

    def test_profile_sets_a_password_only_after_a_proven_sign_in(self):
        self.assertEqual(self.password("/api/auth/signup").status_code, 200)
        with self.client.session_transaction(base_url=ORIGIN) as session:
            csrf = session["auth_csrf"]
        refused = self.post("/api/auth/password", dict(password="another pass 2"), csrf=csrf)
        self.assertEqual(refused.status_code, 403)
        self.logout()
        self.actor(email="person@example.test")
        with self.client.session_transaction(base_url=ORIGIN) as session:
            session["auth_method"] = "google"
        self.assertIn(b"Save password", self.get("/").data)
        self.assertEqual(self.post("/api/auth/password", dict(password="another pass 2"),
                                   csrf="wrong").status_code, 403)
        self.assertEqual(self.post("/api/auth/password", dict(password="another pass 2")).status_code, 200)
        self.logout()
        self.assertEqual(self.password("/api/auth/login", email="person@example.test",
                                       password="another pass 2").status_code, 200)
        # the hash store is reachable only through the signed website protocol
        self.assertEqual(self.post("/api/account/password", dict(op="lookup")).status_code, 403)

    def test_password_accounts_forward_to_backend_and_fail_closed(self):
        backend = self.module.app.test_client()
        website = application(Path(self.directory.name) / "ephemeral.db",
                              forward="https://backend.test", vercel=True)
        client = website.app.test_client()

        def transport(method, url, **kwargs):
            parts = urlsplit(url)
            self.assertNotIn(b"correct horse", kwargs.get("data") or b"")
            result = backend.open(parts.path + ("?" + parts.query if parts.query else ""),
                                  method=method, base_url="https://backend.test",
                                  data=kwargs.get("data"), headers=kwargs.get("headers"))
            response = requests.Response()
            response.status_code = result.status_code
            response._content = result.data
            response.headers.update(result.headers)
            return response

        with patch.object(website.requests, "request", side_effect=transport):
            self.assertEqual(self.password("/api/auth/signup", client=client).status_code, 200)
            self.logout(client)
            self.assertEqual(self.password("/api/auth/login", client=client).status_code, 200)
            self.assertTrue(self.get("/api/health", client=client).json["password_sign_in"])
        with patch.object(website.requests, "request", side_effect=requests.Timeout):
            self.logout(client)
            self.assertEqual(self.password("/api/auth/login", client=client).status_code, 503)
        self.assertFalse(website.DB.exists(), "the website side must stay stateless")
        lone = application(Path(self.directory.name) / "lone.db", vercel=True).app.test_client()
        self.assertEqual(self.password("/api/auth/signup", client=lone).status_code, 503)

    def test_forwarded_requests_are_bound_signed_and_one_use(self):
        self.actor()
        actor = dict(sub="google-user-1", email="person@example.test", name="Example")
        body = json.dumps(dict(role="tenant", bbl=3000410007)).encode()
        with self.module.app.app_context():
            target, headers, nonce = auth.signed_forward("POST", "/api/register", actor, body)
        server = self.module.app.test_client()
        response = server.post(target, base_url=ORIGIN, data=body,
                               headers={**headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 200)
        proxy_response = requests.Response()
        proxy_response.status_code = response.status_code
        proxy_response._content = response.data
        proxy_response.headers.update(response.headers)
        with self.module.app.app_context():
            self.assertTrue(auth.verify_reply(proxy_response, nonce))
            proxy_response._content += b"tampered"
            self.assertFalse(auth.verify_reply(proxy_response, nonce))
        self.assertEqual(server.post(target, base_url=ORIGIN, data=body,
                                     headers={**headers, "Content-Type": "application/json"}).status_code, 401)
        with self.module.app.app_context():
            target, headers, _ = auth.signed_forward("POST", "/api/register", actor, body)
        changed = server.post(target, base_url=ORIGIN, data=body+b" ",
                              headers={**headers, "Content-Type": "application/json"})
        self.assertEqual(changed.status_code, 401)

    def test_vercel_uses_durable_backend_and_fails_without_it(self):
        backend = self.module.app.test_client()
        website = application(Path(self.directory.name)/"ephemeral.db", forward="https://backend.test", vercel=True)
        client = website.app.test_client()
        self.actor(client)

        def transport(method, url, **kwargs):
            parts = urlsplit(url)
            result = backend.open(parts.path + ("?"+parts.query if parts.query else ""),
                                  method=method, base_url="https://backend.test",
                                  data=kwargs.get("data"), headers=kwargs.get("headers"))
            response = requests.Response()
            response.status_code = result.status_code
            response._content = result.data
            response.headers.update(result.headers)
            return response

        with patch.object(website.requests, "request", side_effect=transport):
            saved = self.post("/api/register", dict(role="tenant", bbl=3000410007), client=client)
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json["durable"])
            self.assertEqual(self.get("/api/my_buildings", client=client).json["total"], 1)
            self.assertEqual(self.post("/api/account/remove", dict(bbl=3000410007), client=client).json["removed"], 1)
        with patch.object(website.requests, "request", side_effect=requests.Timeout):
            self.assertEqual(self.post("/api/register", dict(role="viewer"), client=client).status_code, 503)
            self.assertEqual(self.get("/api/my_buildings", client=client).status_code, 503)
        self.assertFalse(website.DB.exists(), "Vercel must not claim an ephemeral registration is saved")

    def test_vercel_never_saves_to_ephemeral_database(self):
        website = application(Path(self.directory.name)/"ephemeral.db", vercel=True)
        client = website.app.test_client()
        self.actor(client)
        self.assertEqual(self.post("/api/register", dict(role="viewer"), client=client).status_code, 503)
        self.assertEqual(self.get("/api/my_buildings", client=client).status_code, 503)
        self.assertFalse(website.DB.exists())


if __name__ == "__main__":
    unittest.main()
