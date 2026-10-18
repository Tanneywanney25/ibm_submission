"""Navigation to the research assistant and the complaint monitor; no external calls.

/monitor (no mode) is the research assistant ("Ask the data"); the published
complaint monitor is /monitor?mode=current (docs/VERCEL.md, research assistant).
"""
from pathlib import Path
import re
import tempfile
import unittest

from test_accounts import ORIGIN, application


class AskLinkTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.client = application(Path(directory.name) / "ask.db").app.test_client()

    def page(self, path):
        response = self.client.get(path, base_url=ORIGIN)
        self.assertEqual(response.status_code, 200, path)
        return response.data.decode()

    def test_header_tab_and_home_question_card(self):
        home = self.page("/")
        self.assertIn('href="/monitor" class="">Ask the data</a>', home)
        self.assertNotIn(">Live monitor</a>", home)
        self.assertIn("Have a specific question?", home)
        self.assertIn('<form class="ask-box" action="/monitor" method="get"', home)
        chips = re.findall(r'class="ask-chip" href="(/monitor\?q=[^"]+)"', home)
        self.assertEqual(len(chips), 3)
        for href in chips:
            self.assertIn("ask-question", self.page(href))

    def test_complaint_monitor_links_skip_the_assistant(self):
        for path in ("/learn-more", "/monitor?mode=replay"):
            self.assertIn('href="/monitor?mode=current"', self.page(path))
        for path in ("/learn-more", "/monitor?mode=replay", "/"):
            self.assertNotIn('<a href="/monitor">See published complaints', self.page(path))
            self.assertNotIn('<a href="/monitor" aria-current', self.page(path))


if __name__ == "__main__":
    unittest.main()
