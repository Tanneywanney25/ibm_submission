"""The homepage quiz (web/templates/_quiz.html); no external calls.

The quiz only points at pages and APIs the site already serves, so every link it can put
in a plan must answer here, and every dashboard panel it can turn on must be a real one.
"""
from pathlib import Path
import re
import tempfile
import time
import unittest

from test_accounts import ORIGIN, application


class QuizTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.module = application(Path(directory.name) / "quiz.db")
        self.client = self.module.app.test_client()

    def home(self):
        response = self.client.get("/", base_url=ORIGIN)
        self.assertEqual(response.status_code, 200)
        page = response.data.decode()
        start = page.index('<section class="card quiz-card" id="quiz"')
        return page, page[start:page.index("</script>", start)]

    def test_quiz_is_on_the_homepage_for_everyone(self):
        page, quiz = self.home()
        self.assertIn("Not sure where to start?", quiz)
        self.assertIn("const SIGNED_IN = false;", quiz)
        self.assertLess(page.index('id="quiz"'), page.index('class="card ask-card"'))
        with self.client.session_transaction(base_url=ORIGIN) as session:
            session["auth_user"] = dict(sub="google-user-1", email="person@example.test", name="P")
            session["auth_expires"] = time.time() + 86400
            session["auth_csrf"] = "csrf-for-tests"
        _, quiz = self.home()
        self.assertIn("const SIGNED_IN = true;", quiz)
        self.assertIn('const CSRF = "csrf-for-tests";', quiz)

    def test_every_plan_link_resolves(self):
        _, quiz = self.home()
        hrefs = set(re.findall(r"link\('(/[^']*)'", quiz)) | set(re.findall(r'href="(/[^"]*)"', quiz))
        self.assertIn("/api/queue.csv?k=500", hrefs)
        self.assertIn("/monitor?mode=current", hrefs)
        for href in sorted(hrefs):
            response = self.client.get(href.split("#")[0], base_url=ORIGIN)
            if href == "/account":                       # signed out: the sign-in page first
                self.assertIn("/signin", response.location)
            else:
                self.assertEqual(response.status_code, 200, href)

    def test_panels_are_real_and_the_address_stays_building_level(self):
        _, quiz = self.home()
        panels = re.search(r"const PANELS_FOR = (\{.*?\});", quiz, re.S).group(1)
        for name in re.findall(r"'(\w+)'", panels):
            self.assertIn(name, self.module.PANELS)
        self.assertIsNone(re.search(r'<input[^>]*(?:name|id)="[^"]*(?:apt|unit)', quiz, re.I))
        self.assertIn("leave out the apartment number", quiz)


if __name__ == "__main__":
    unittest.main()
