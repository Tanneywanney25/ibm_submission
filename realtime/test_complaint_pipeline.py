"""Offline contract tests: synthetic rows live only in temporary databases."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

try:
    from realtime.complaint_pipeline import connect, create_app, get, normalize, poll, snapshot
except ModuleNotFoundError:
    from complaint_pipeline import connect, create_app, get, normalize, poll, snapshot

NOW = datetime(2026, 10, 17, 16, tzinfo=timezone.utc)


def row(problem=1, complaint=10, date='2026-10-17T10:00:00.000', **kwargs):
    return dict(received_date=date, problem_id=str(problem), complaint_id=str(complaint),
                building_id='123', borough='BRONX', block='3212', lot='92',
                problem_code='NO HEAT', **kwargs)


class Source:
    def __init__(self, pages):
        self.pages, self.queries = iter(pages), []

    def __call__(self, query):
        self.queries.append(query)
        if '$where' not in query:
            return [{'newest': '2026-10-17T11:00:00.000'}]
        result = next(self.pages)
        if isinstance(result, Exception):
            raise result
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'complaints.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_dedup_problems_and_restart(self):
        source = Source([[row(1), row(2)], []])
        poll(self.db, fetch=source, now=NOW, page_size=2)
        data = snapshot(self.db, now=NOW)
        self.assertEqual(data['stats']['complaints_24h'], 1)
        self.assertEqual(data['buildings'][0]['bbl'], '2032120092')
        self.assertEqual(poll(self.db, fetch=Source([[row(1),row(2)]]), now=NOW)['net_problem_change'], 0)
        self.assertEqual(snapshot(self.db, now=NOW)['stats']['complaints_24h'], 1)
        self.assertIn('problem_id > 2', source.queries[-1]['$where'])

    def test_late_arrival_overlap(self):
        poll(self.db, fetch=Source([[row()]]), now=NOW)
        late = row(3, 11, '2026-10-16T10:00:00.000')
        source = Source([[late, row()]])
        poll(self.db, fetch=source, now=NOW+timedelta(minutes=5))
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM problems').fetchone()[0], 2)
        self.assertIn('2026-10-10', source.queries[1]['$where'])

    def test_failed_page_preserves_last_success_and_rows(self):
        poll(self.db, fetch=Source([[row()]]), now=NOW)
        with self.assertRaises(TimeoutError):
            poll(self.db, fetch=Source([[row(3,11)], TimeoutError()]),
                 now=NOW+timedelta(hours=1), page_size=1)
        with connect(self.db) as db:
            self.assertEqual(get(db,'last_success'), NOW.isoformat())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM problems').fetchone()[0], 1)
        self.assertEqual(snapshot(self.db, now=NOW)['stats']['status'], 'poll_error')

    def test_invalid_source_and_page_limit_fail_closed(self):
        for source,kwargs in [(Source([[row(),row()]]),{}),
                              (Source([[row()]]),dict(page_size=1,max_pages=1))]:
            with self.assertRaises(ValueError):
                poll(self.db, fetch=source, now=NOW, **kwargs)
        with connect(self.db) as db:
            self.assertIsNone(get(db, 'last_success'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM problems').fetchone()[0], 0)

    def test_no_pii_and_missing_location(self):
        sample = row()
        sample['lot'] = None
        sample['apartment'] = 'DO NOT STORE'
        poll(self.db, fetch=Source([[sample]]), now=NOW)
        data = snapshot(self.db, now=NOW)
        self.assertEqual(data['stats']['unlocated_complaints_7d'], 1)
        self.assertEqual(data['buildings'], [])
        self.assertNotIn('DO NOT STORE', self.db.read_bytes().decode(errors='ignore'))
        self.assertEqual(normalize(row())[4], '2032120092')

    def test_source_lag_staleness_and_request_validation(self):
        app = create_app(self.db).test_client()
        self.assertEqual(app.get('/stats').json['status'], 'waiting')
        for k in ['abc','0','101']:
            self.assertEqual(app.get('/queue?k='+k).status_code, 400)
        poll(self.db, fetch=Source([[row()]]), now=NOW)
        data = snapshot(self.db, now=NOW+timedelta(hours=2))
        self.assertEqual(data['stats']['status'], 'stale')
        self.assertEqual(data['stats']['source_lag_hours'], 3)
        self.assertIn('not predicted risk', data['stats']['ordering'])
        self.assertEqual(app.post('/ingest',json=row()).status_code,404)

    def test_outage_catches_up_and_time_window_expires(self):
        poll(self.db,fetch=Source([[row()]]),now=NOW)
        source = Source([[]])
        later = NOW+timedelta(days=15)
        poll(self.db,fetch=source,now=later)
        self.assertIn('2026-10-10',source.queries[1]['$where'])
        self.assertEqual(snapshot(self.db,now=later)['stats']['complaints_24h'],0)

    def test_successful_window_reflects_retracted_rows(self):
        poll(self.db,fetch=Source([[row()]]),now=NOW)
        poll(self.db,fetch=Source([[]]),now=NOW+timedelta(minutes=5))
        self.assertEqual(snapshot(self.db,now=NOW)['stats']['complaints_24h'],0)

    def test_feed_dedup_week_window_and_future_clock(self):
        previous=row(1,10,'2026-10-15T10:00:00.000')
        poll(self.db,fetch=Source([[previous,row(2,date='2026-10-15T10:00:00.000'),row(3,11)]]),now=NOW)
        data=snapshot(self.db,now=NOW)
        self.assertEqual(data['stats']['complaints_7d'],2)
        self.assertEqual(data['stats']['complaints_24h'],1)
        self.assertEqual(len(data['events']),2)
        self.assertEqual(data['events'][0]['complaint_id'],11)
        self.assertEqual(data['buildings'][0]['complaints_7d'],2)
        self.assertEqual(data['stats']['latest_heat_received'],'2026-10-17T10:00:00.000')
        before=snapshot(self.db,now=NOW-timedelta(days=4))
        self.assertEqual(before['stats']['complaints_7d'],0)
        self.assertEqual(before['events'],[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
