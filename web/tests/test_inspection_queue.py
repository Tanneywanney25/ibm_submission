"""Old inspection-page links remain usable after the page is retired."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_accounts import application, ORIGIN


class RetiredInspectionQueueTests(unittest.TestCase):
    def test_old_page_redirects_without_reading_ranking_or_creating_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            module = application(Path(directory) / "unused.db", secret="", google=False)
            client = module.app.test_client()
            with patch.object(module, "queue_csv", side_effect=OSError("snapshot unavailable")):
                response = client.get("/inspection-queue", base_url=ORIGIN)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/monitor")
                monitor = client.get("/inspection-queue", base_url=ORIGIN, follow_redirects=True)
                self.assertEqual(monitor.status_code, 200)
                self.assertNotIn(b'href="/inspection-queue', monitor.data)
            self.assertFalse(module.DB.exists())


if __name__ == "__main__":
    unittest.main()
