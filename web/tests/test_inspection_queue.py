"""The public shortlist uses the existing export, independently of sign-in/replay."""
import csv
import io
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

from test_accounts import application, ORIGIN


class InspectionQueueTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "unused.db"
        self.module = application(self.db, google=False)
        self.client = self.module.app.test_client()

    def get(self, path):
        return self.client.get(path, base_url=ORIGIN)

    def actor(self):
        with self.client.session_transaction(base_url=ORIGIN) as session:
            session['auth_user'] = dict(sub='fixture', email='fixture@example.test', name='Fixture User')
            session['auth_expires'] = time.time() + 3600
            session['auth_csrf'] = 'fixture-csrf'

    def test_public_shortlist_matches_export_and_valid_building_records(self):
        exported = self.get("/api/queue.csv?k=50")
        self.assertEqual(exported.status_code, 200)
        original = list(csv.DictReader(io.StringIO(exported.get_data(as_text=True))))
        rows = self.module.inspection_shortlist()
        self.assertEqual(len(rows), 50)
        self.assertEqual([row["bbl"] for row in rows], [row["bbl"] for row in original])
        self.assertEqual(len({row["bbl"] for row in rows}), 50)
        self.assertEqual([row["rank"] for row in rows], list(range(1, 51)))
        page = self.get("/inspection-queue")
        self.assertEqual(page.status_code, 200)
        self.assertIn("saved model snapshot", page.get_data(as_text=True).lower())
        self.assertIn(b'href="/api/queue.csv?k=50"', page.data)
        for row in rows:
            self.assertIn(('href="/building?bbl='+row["bbl"]+'"').encode(), page.data)
            self.assertIn(('href="/map?bbl='+row["bbl"]+'"').encode(), page.data)
            payload = self.get('/api/building/'+row['bbl']).json
            self.assertTrue(payload['ranked'])
        self.assertFalse(self.db.exists())

    def test_sign_in_does_not_change_public_priorities_or_restore_duplicate_tabs(self):
        anonymous = self.get("/inspection-queue").get_data(as_text=True)
        self.actor()
        signed_in = self.get("/inspection-queue").get_data(as_text=True)
        for html in [anonymous, signed_in]:
            nav = re.search(r'<nav class="site-links".*?</nav>', html, re.S).group()
            self.assertNotIn('href="/"', nav)
            self.assertNotIn('My account', html)
            self.assertNotIn('href="/faq', html)
            self.assertIn('aria-label="HeatAhead home"', html)
            self.assertIn('href="/inspection-queue"', nav)
        self.assertEqual(re.findall(r'/building\?bbl=(\d+)', anonymous),
                         re.findall(r'/building\?bbl=(\d+)', signed_in))
        self.assertIn('/api/auth/logout', signed_in)
        self.assertEqual(self.get('/').status_code, 200)

    def test_invalid_snapshot_shows_unavailable_instead_of_partial_queue(self):
        header='bbl,rank,p_calibrated,unitsres,c_last1,v_last1\n'
        good='2023010004,1,0.70,100,12,1\n'
        cases=[None, '', header, 'unexpected\nvalue\n',
               header+good+good,
               header+'2023010004,1,nan,100,12,1\n',
               header+'2023010004,1,1.2,100,12,1\n',
               header+'2023010004,1,0.7,-1,12,1\n',
               header+'<script>,1,0.7,100,12,1\n']
        for body in cases:
            with self.subTest(body=body), patch.object(self.module,'queue_csv',return_value=body):
                self.assertIsNone(self.module.inspection_shortlist())
                page=self.get('/inspection-queue')
                self.assertEqual(page.status_code,200)
                self.assertIn(b'The saved queue is unavailable.',page.data)
                self.assertNotIn(b'class="inspection-building"',page.data)
        with patch.object(self.module,'queue_csv',side_effect=OSError('unreadable')):
            self.assertIn(b'The saved queue is unavailable.',self.get('/inspection-queue').data)

    def test_tied_risks_keep_model_order_and_unknown_counts_are_not_zero(self):
        source=('bbl,rank,p_calibrated,unitsres,c_last1,v_last1\n'
                '2023010004,1,1.0,,,\n'
                '3000410007,2,1.0,20,1,0\n')
        with patch.object(self.module,'queue_csv',return_value=source):
            rows=self.module.inspection_shortlist()
            self.assertEqual([r['bbl'] for r in rows],['2023010004','3000410007'])
            self.assertIn('99%',rows[0]['risk'])
            self.assertNotIn('100%',rows[0]['risk'])
            self.assertIsNone(rows[0]['units'])
            self.assertIsNone(rows[0]['complaints'])
            self.assertEqual(rows[1]['violations'],0)
