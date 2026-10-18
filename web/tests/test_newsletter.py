"""Opt-in and storage boundaries. Every email and upstream call is mocked."""
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from test_accounts import application, ORIGIN
import newsletter

SMTP = dict(SMTP_HOST="smtp.example.test", SMTP_USER="test-user",
            SMTP_PASS="test-only-not-a-password", SMTP_FROM="updates@example.test")


class NewsletterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module = application(Path(self.directory.name) / "newsletter.db", google=False)
        self.client = self.module.app.test_client()
        self.smtp = patch.dict(os.environ, SMTP)
        self.smtp.start()
        self.addCleanup(self.smtp.stop)
        self.site = patch("mailer.SITE_URL", ORIGIN)
        self.site.start()
        self.addCleanup(self.site.stop)
        self.sender = patch("mailer.send", return_value=True)
        self.send = self.sender.start()
        self.addCleanup(self.sender.stop)
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected live network request in newsletter test"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def post(self, path="subscribe", body=None, client=None, origin=ORIGIN):
        return (client or self.client).post("/api/newsletter/" + path, base_url=ORIGIN,
                                            json=body or dict(name="Emerson", email="person@example.test", consent=True),
                                            headers={"Origin": origin} if origin else {})

    def row(self):
        with sqlite3.connect(self.module.DB) as con:
            con.row_factory = sqlite3.Row
            return dict(con.execute("SELECT * FROM newsletter_subscribers").fetchone())

    def links(self):
        body = self.send.call_args.args[0].get_content()
        return {purpose: parse_qs(urlsplit(re.search(r"https://[^\s]+/newsletter/" + purpose + r"\?[^\s]+", body)[0]).query)["token"][0]
                for purpose in ("confirm", "unsubscribe")}

    def wait_for_resend(self):
        with sqlite3.connect(self.module.DB) as con:
            con.execute("UPDATE newsletter_subscribers SET last_requested=?", (int(time.time()) - 601,))

    def test_public_pages_assets_and_embed(self):
        for route in ("/", "/contact", "/privacy", "/building", "/map", "/learn-more", "/monitor"):
            result = self.client.get(route, base_url=ORIGIN, follow_redirects=True)
            self.assertEqual(result.status_code, 200, route)
            self.assertIn(b"mailto:heataheadnyc@gmail.com", result.data)
            self.assertIn(b'id="privacy-banner"', result.data)
            ids = re.findall(rb'\bid="([^"\s]+)"', result.data)
            self.assertEqual(len(ids), len(set(ids)), route)
        embedded = self.client.get("/map?embed=1", base_url=ORIGIN)
        self.assertNotIn(b'id="privacy-banner"', embedded.data)
        self.assertNotIn(b'/static/privacy.js', embedded.data)
        self.assertFalse(self.module.DB.exists())
        for filename in ("privacy.js", "privacy.css", "newsletter.js"):
            with self.client.get("/static/" + filename) as result:
                self.assertEqual(result.status_code, 200)
        self.send.assert_not_called()

    def test_health_checks_settings_and_backend_version_without_sending_mail(self):
        ready = self.client.get("/api/health", base_url=ORIGIN).json
        self.assertEqual(ready["newsletter_protocol"], 1)
        self.assertTrue(ready["newsletter_delivery_ready"])
        with patch.dict(os.environ, dict(SMTP_HOST="")):
            self.assertFalse(self.client.get("/api/health", base_url=ORIGIN).json["newsletter_delivery_ready"])
        frontend = application(Path(self.directory.name) / "frontend.db", forward="https://instance.test", vercel=True, google=False)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(ready).encode()
        with patch("requests.get", return_value=response), patch("requests.request", return_value=response):
            self.assertTrue(frontend.app.test_client().get("/api/health").json["newsletter_delivery_ready"])
        response._content = b'{"ok":true,"email_sign_in":true}'
        with patch("requests.get", return_value=response), patch("requests.request", return_value=response):
            self.assertFalse(frontend.app.test_client().get("/api/health").json["newsletter_delivery_ready"])
        self.assertFalse(frontend.DB.exists())
        self.send.assert_not_called()

    def test_only_confirmed_email_becomes_subscribed_and_get_is_read_only(self):
        result = self.post(body=dict(email=" Person@Example.Test ", consent=True))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.row()["status"], "pending")
        self.assertEqual(self.row()["email"], "person@example.test")
        self.assertEqual(self.row()["name"], "")
        self.assertEqual(self.row()["consent_version"], newsletter.CONSENT_VERSION)
        tokens = self.links()
        for purpose, token in tokens.items():
            page = self.client.get("/newsletter/" + purpose, query_string=dict(token=token), base_url=ORIGIN)
            self.assertEqual(page.status_code, 200)
            self.assertIn("no-store", page.headers["Cache-Control"])
            self.assertEqual(page.headers["Referrer-Policy"], "no-referrer")
            self.assertNotIn("Set-Cookie", page.headers)
            self.assertEqual(self.row()["status"], "pending")
        confirmed = self.post("confirm", dict(token=tokens["confirm"]))
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.row()["status"], "subscribed")
        self.assertIsNotNone(self.row()["confirmed"])
        again = self.post("confirm", dict(token=tokens["confirm"]))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.send.call_count, 1)
        self.assertNotIn("Set-Cookie", confirmed.headers)
        session = self.client.get("/api/auth/session", base_url=ORIGIN).json
        self.assertIsNone(session["user"])

    def test_tokens_are_purpose_bound_and_contain_no_email(self):
        self.post()
        tokens = self.links()
        with self.module.app.app_context():
            content = newsletter._read_token(tokens["confirm"], "confirm")
            self.assertEqual(set(content), {"id", "generation"})
            self.assertNotIn("person@example.test", str(content))
            self.assertIsNone(newsletter._read_token(tokens["unsubscribe"], "confirm"))
            self.assertIsNone(newsletter._read_token(tokens["confirm"] + "x", "confirm"))
        self.assertEqual(self.post("confirm", dict(token=tokens["unsubscribe"])).status_code, 410)

    def test_confirm_expires_after_24_hours_unsubscribe_does_not(self):
        self.post()
        tokens = self.links()
        future = time.time() + newsletter.CONFIRM_TTL + 5
        with patch("time.time", return_value=future):
            self.assertEqual(self.post("confirm", dict(token=tokens["confirm"])).status_code, 410)
            self.assertEqual(self.post("unsubscribe", dict(token=tokens["unsubscribe"])).status_code, 200)

    def test_unsubscribe_is_separate_and_old_confirmation_cannot_reactivate(self):
        self.post()
        first = self.links()
        self.post("confirm", dict(token=first["confirm"]))
        with sqlite3.connect(self.module.DB) as con:
            con.execute("INSERT INTO users(role,email,bbl) VALUES (?,?,?)", ("tenant", "person@example.test", 3000410007))
        self.assertEqual(self.post("unsubscribe", dict(token=first["unsubscribe"])).status_code, 200)
        self.assertEqual(self.row()["status"], "unsubscribed")
        self.assertEqual(self.post("confirm", dict(token=first["confirm"])).status_code, 410)
        self.post()
        second = self.links()
        self.assertNotEqual(first["confirm"], second["confirm"])
        self.assertEqual(self.row()["status"], "pending")
        self.assertIsNone(self.row()["confirmed"])
        self.assertEqual(self.post("confirm", dict(token=second["confirm"])).status_code, 200)
        # Unsubscribe links in older messages remain usable after rejoining.
        self.assertEqual(self.post("unsubscribe", dict(token=first["unsubscribe"])).status_code, 200)
        self.assertEqual(self.row()["status"], "unsubscribed")
        with sqlite3.connect(self.module.DB) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_dedupe_cooldown_and_existing_subscriber_details(self):
        first = self.post()
        token = self.links()["confirm"]
        self.post(body=dict(name="Changed", email="person@example.test", consent=True))
        self.assertEqual(self.send.call_count, 1)
        # Cooldown is in SQLite, including after a new app worker is created.
        other = application(self.module.DB, google=False)
        self.assertEqual(self.post(client=other.app.test_client()).json, first.json)
        self.assertEqual(self.send.call_count, 1)
        self.post("confirm", dict(token=token))
        self.wait_for_resend()
        duplicate = self.post(body=dict(name="Changed", email="PERSON@example.test", consent=True))
        self.assertEqual(duplicate.json, first.json)
        self.assertEqual(self.row()["name"], "Emerson")
        self.assertEqual(self.send.call_count, 1)

    def test_invalid_origin_invalid_input_and_honeypot_do_not_send(self):
        for origin in (None, "https://other.test"):
            self.assertEqual(self.post(origin=origin).status_code, 403)
        for body in ([1], dict(email="bad", consent=True),
                     dict(email="a..b@example.test", consent=True),
                     dict(email="person@example.test", name="x"*81, consent=True),
                     dict(email="person@example.test", name="A\nB", consent=True),
                     dict(email="person@example.test", consent=1),
                     dict(email="person@example.test"),
                     dict(email=["person@example.test"], consent=True)):
            with self.subTest(body=body):
                self.assertEqual(self.post(body=body).status_code, 400)
        trap = self.post(body=dict(email="person@example.test", consent=True, website="spam"))
        self.assertEqual(trap.status_code, 200)
        self.assertFalse(self.module.DB.exists())
        self.send.assert_not_called()

    def test_native_form_and_script_strings_stay_escaped(self):
        result = self.client.post("/api/newsletter/subscribe", base_url=ORIGIN,
                                  data=dict(email="person@example.test", name='<script>alert("x")</script>', consent="yes"),
                                  headers={"Origin": ORIGIN})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(b'<script>alert("x")</script>', result.data)
        self.assertIn(b"confirmation link", result.data)
        token = self.links()["confirm"]
        confirmed = self.client.post("/api/newsletter/confirm", base_url=ORIGIN,
                                     data=dict(token=token), headers={"Origin": ORIGIN})
        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("You're subscribed", html.unescape(confirmed.data.decode()))

    def test_unconfigured_and_failed_delivery_never_claim_success(self):
        with patch.dict(os.environ, dict(SMTP_HOST="")):
            self.assertEqual(self.post().status_code, 503)
            self.assertFalse(self.module.DB.exists())
        self.send.return_value = False
        result = self.post()
        self.assertEqual(result.status_code, 503)
        self.assertIn("couldn't send", result.json["error"])
        self.assertEqual(self.row()["status"], "pending")
        self.assertIsNone(self.row()["confirmed"])
        again = self.post()
        self.assertEqual(again.status_code, 503)
        self.assertEqual(again.json, result.json)
        self.assertEqual(self.send.call_count, 1)

    def test_worker_send_budget_and_database_failures(self):
        for i in range(20):
            self.assertEqual(self.post(body=dict(email=f"person{i}@example.test", consent=True)).status_code, 200)
        self.assertEqual(self.post(body=dict(email="over@example.test", consent=True)).status_code, 429)
        self.assertEqual(self.send.call_count, 20)
        with patch.object(self.module, "db", side_effect=sqlite3.OperationalError):
            with self.assertLogs(self.module.app.logger, level="WARNING"):
                failed = self.post(body=dict(email="another@example.test", consent=True))
            self.assertEqual(failed.status_code, 503)

    def test_vercel_never_uses_ephemeral_subscriber_storage(self):
        preview = application(Path(self.directory.name) / "must-not-exist.db", vercel=True, google=False)
        result = self.post(client=preview.app.test_client())
        self.assertEqual(result.status_code, 503)
        self.assertFalse(preview.DB.exists())
        self.send.assert_not_called()

    def test_forwarding_runs_opt_in_and_unsubscribe_on_durable_backend(self):
        frontend = application(Path(self.directory.name) / "no-frontend-db", forward="https://instance.test", vercel=True, google=False)
        client = frontend.app.test_client()
        calls = []

        def forward(url, **kwargs):
            calls.append((url, kwargs))
            result = self.client.post(urlsplit(url).path, base_url="https://instance.test",
                                      json=kwargs["json"], headers=kwargs["headers"])
            response = requests.Response()
            response.status_code = result.status_code
            response._content = result.data
            return response

        with patch("newsletter.requests.post", side_effect=forward):
            self.assertEqual(self.post(client=client).status_code, 200)
            tokens = self.links()
            self.assertEqual(self.post("confirm", dict(token=tokens["confirm"]), client=client).status_code, 200)
            self.assertEqual(self.row()["status"], "subscribed")
            self.assertEqual(self.post("unsubscribe", dict(token=tokens["unsubscribe"]), client=client).status_code, 200)
        self.assertFalse(frontend.DB.exists())
        self.assertEqual(self.row()["status"], "unsubscribed")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(not kw["allow_redirects"] for _, kw in calls))
        self.assertTrue(all("X-HeatAhead-Identity" not in kw["headers"] for _, kw in calls))

    def test_old_backend_bad_response_and_timeout_fail_closed(self):
        self.module.FORWARD_URL = "https://instance.test"
        for status, body in ((404, {}), (200, []), (200, dict(unexpected="value")),
                             (200, dict(ok=True)), (200, dict(ok=False, message="Not saved"))):
            response = requests.Response()
            response.status_code = status
            response._content = json.dumps(body).encode()
            with patch("newsletter.requests.post", return_value=response):
                self.assertEqual(self.post().status_code, 503)
        with patch("newsletter.requests.post", side_effect=requests.Timeout):
            self.assertEqual(self.post().status_code, 503)
        self.assertFalse(self.module.DB.exists())
        self.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
