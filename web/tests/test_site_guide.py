"""Help works without keys; optional AI can only select a published topic."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import requests
from test_accounts import application, ORIGIN
import site_guide


class SiteGuideTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module = application(Path(self.directory.name) / "unused.db", secret="", google=False)
        self.module.app.config.update(GUIDE_AI_KEY="", GUIDE_AI_MODEL="")
        self.client = self.module.app.test_client()

    def post(self, body, origin=ORIGIN):
        return self.client.post("/api/guide/ask", base_url=ORIGIN, json=body,
                                headers={"Origin": origin})

    def provider(self, topic="heights", status="completed"):
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(dict(status=status, output=[dict(type="message", content=[
            dict(type="output_text", text=json.dumps(dict(topic=topic)))])])).encode()
        return response

    def enable(self):
        self.module.app.config.update(GUIDE_AI_KEY="test-only-not-a-real-api-key", GUIDE_AI_MODEL="test-model")

    def test_help_pages_and_widget_work_without_auth_or_provider(self):
        for route in ["/", "/?help=1", "/?help=guide", "/map", "/building", "/monitor", "/about"]:
            result = self.client.get(route, base_url=ORIGIN)
            self.assertEqual(result.status_code, 200)
            self.assertIn(b'id="hg-dialog"', result.data)
            self.assertIn(b'/static/guide.js', result.data)
            self.assertIn(b'"ai_enabled": false', result.data)
            self.assertIn("no-store", result.headers["Cache-Control"])
            ids = re.findall(rb'\bid="([^"\s]+)"', result.data)
            self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(self.module.DB.exists())
        for asset in ["guide.js", "guide.css", "help-pages.css", "guide-content.json"]:
            with self.client.get("/static/"+asset) as result:
                self.assertEqual(result.status_code, 200)

    def test_catalog_and_deep_links_are_complete(self):
        catalog = site_guide.CONTENT["items"]
        self.assertEqual(len(catalog), 29)
        self.assertEqual(len({i["id"] for i in catalog}), 29)
        learn = self.client.get("/").data.decode()
        for section in ["how-it-works", "reading-the-map", "understanding-risk", "taking-action", "data-and-privacy"]:
            self.assertIn('id="hg-guide-'+section+'"', learn)
            self.assertIn('id="hg-nojs-'+section+'"', learn)
        for item in catalog:
            self.assertIn('data-guide-question="'+item["id"]+'"', learn)
            self.assertIn('id="help-answer-'+item["id"]+'"', learn)
            self.assertTrue(item["answer"])
            self.assertTrue(all(id in site_guide.ITEMS for id in item["follow"]))
            for link in item["links"]:
                self.assertFalse(link["href"].startswith(("/faq", "/help", "/learn-more", "/inspection-queue")))
                if link["href"].startswith("/?help=guide#"):
                    self.assertIn('id="hg-guide-'+link["href"].split("#")[1]+'"', learn)

    def test_old_faq_is_a_redirect_and_navigation_opens_chat(self):
        result = self.client.get("/faq")
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.headers["Location"], "/?help=1")
        page = self.client.get("/faq", follow_redirects=True).data
        self.assertIn(b'id="hg-browser"', page)
        self.assertNotIn(b'Frequently asked questions</h1>', page)
        self.assertNotIn(b'href="/faq', page)
        self.assertIn(b'data-open-guide data-guide-browse>Ask HeatAhead</a>', page)
        self.assertNotIn(b'href="/inspection-queue', page)
        self.assertNotIn(b'href="/learn-more', page)

    def test_retired_pages_redirect_to_chat_or_existing_monitor(self):
        for source, destination in [
            ("/learn-more", "/?help=guide"), ("/help", "/?help=guide"),
            ("/learn-more?help=heights", "/?help=heights"),
            ("/help?help=1", "/?help=1"),
            ("/learn-more?help=unknown", "/?help=guide"),
            ("/inspection-queue", "/monitor"),
        ]:
            with self.subTest(source=source):
                response = self.client.get(source)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], destination)

    def test_unconfigured_guide_makes_no_provider_requests(self):
        with patch.object(site_guide.requests, "post") as provider:
            result = self.post(dict(question="Where should I start?"))
            self.assertEqual(result.json, dict(topic=None, mode="guide"))
            self.assertIn("no-store", result.headers["Cache-Control"])
            provider.assert_not_called()

    def test_cross_origin_and_personal_input_is_rejected(self):
        self.enable()
        with patch.object(site_guide.requests, "post") as provider:
            self.assertEqual(self.post(dict(question="test"), origin="https://other.test").status_code, 403)
            for body in [[], {}, dict(question=" "), dict(question="x"*401),
                         dict(question="email me at someone@example.test"),
                         dict(question="my number is 646-555-1234"),
                         dict(question="unit 12 heat issue"), dict(question="my password is xyz")]:
                with self.subTest(body=body):
                    self.assertEqual(self.post(body).status_code, 400)
            provider.assert_not_called()

    def test_ai_returns_only_an_allowed_topic_and_redacts_bbl(self):
        self.enable()
        with patch.object(site_guide.requests, "post", return_value=self.provider()) as provider:
            result = self.post(dict(question="Why that height for BBL 3000410007?", previous_topic="map"))
            self.assertEqual(result.json, dict(topic="heights", mode="ai"))
            body = provider.call_args.kwargs["json"]
            self.assertFalse(body["store"])
            self.assertNotIn("3000410007", body["input"])
            self.assertNotIn("auth_user", body["input"])
            self.assertEqual(body["text"]["format"]["type"], "json_schema")
            self.assertFalse(provider.call_args.kwargs["allow_redirects"])
        page = self.client.get("/").data
        self.assertNotIn(b"test-only-not-a-real-api-key", page)
        self.assertIn(b'"ai_enabled": true', page)

    def test_provider_injection_refusal_and_outage_fall_back(self):
        self.enable()
        for response in [self.provider("https://attacker.test"), self.provider("made-up-score"),
                         self.provider("heights", status="incomplete")]:
            with patch.object(site_guide.requests, "post", return_value=response):
                self.assertEqual(self.post(dict(question="Try this question")).json,
                                 dict(topic=None, mode="guide"))
        with patch.object(site_guide.requests, "post", side_effect=requests.Timeout):
            self.assertEqual(self.post(dict(question="Try again")).json["mode"], "guide")

    def test_warm_worker_bounds_external_calls(self):
        self.enable()
        with patch.object(site_guide.requests, "post", return_value=self.provider()) as provider:
            for _ in range(5):
                self.assertEqual(self.post(dict(question="Help with an unfamiliar phrase")).status_code, 200)
            sixth = self.post(dict(question="Another phrase"))
            self.assertEqual(sixth.status_code, 429)
            self.assertEqual(sixth.json["mode"], "guide")
            self.assertEqual(provider.call_count, 5)


if __name__ == "__main__":
    unittest.main()
