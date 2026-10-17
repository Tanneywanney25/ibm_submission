import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location('replay_app', Path(__file__).with_name('app.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.data.joinpath('buildings.csv').write_text('bbl,latitude,longitude,unitsres\n1017700040,40.8,-73.9,6\n2023300051,40.81,-73.92,36\n')
        self.data.joinpath('replay_feb7_9.csv').write_text(
            'bbl,received_date,complaint_id\n' + ''.join(
                f'{1017700040 if i % 3 else 2023300051},2026-02-07 00:00:{i:02},c{i}\n' for i in range(24)))
        self.app = module.create_app(self.data, checkpoint_every=2)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, client, statuses):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = client.get('/stats').get_json()
            if result['status'] in statuses:
                return result
            time.sleep(.005)
        self.fail('Worker did not reach requested status')

    def test_resume_matches_full_run(self):
        self.assertEqual(self.client.post('/replay/start', json={'speedup': 100000}).status_code, 202)
        self.wait(self.client, {'completed'})
        expected = self.client.get('/queue').get_json()
        self.client.post('/replay/start', json={'speedup': 100})
        time.sleep(.04)
        self.assertEqual(self.client.post('/replay/pause').status_code, 202)
        paused = self.wait(self.client, {'paused'})
        self.assertGreater(paused['processed'], 0)
        self.assertLess(paused['processed'], 24)
        recovered = module.create_app(self.data, checkpoint_every=2).test_client()
        restored = recovered.get('/stats').get_json()
        self.assertEqual(restored['processed'], paused['processed'])
        self.assertTrue(restored['restored_from_checkpoint'])
        self.assertEqual(recovered.post('/replay/start', json={'resume': True, 'speedup': 100000}).status_code, 202)
        result = self.wait(recovered, {'completed'})
        self.assertEqual(result['processed'], 24)
        self.assertEqual(result['checkpoint_processed'], 24)
        self.assertEqual(recovered.get('/queue').get_json(), expected)
        saved = json.loads((self.data/'realtime_checkpoint.json').read_text())
        self.assertEqual(len(saved['latencies_ms']), 24)
        # A fresh start after recovery clears the old counters.
        recovered.post('/replay/start', json={'speedup': 100000})
        self.wait(recovered, {'completed'})
        self.assertEqual(recovered.get('/queue').get_json(), expected)

    def test_invalid_inputs(self):
        for body in ([], [1], None, 4, 'x', {'speedup':True}, {'speedup':'600'},
                     {'speedup':0}, {'speedup':100001}, {'resume':'true'}, {'unknown':1}):
            r = self.client.post('/replay/start', data=json.dumps(body), content_type='application/json')
            self.assertEqual(r.status_code, 400, body)
        for raw in ('{', '{"speedup": NaN}', '{"speedup": Infinity}'):
            self.assertEqual(self.client.post('/replay/start', data=raw, content_type='application/json').status_code, 400)
        for k in ('0', '-1', '1001', 'abc', '2.5'):
            self.assertEqual(self.client.get('/queue?k='+k).status_code, 400)
        self.assertEqual(self.client.get('/queue?sort=tenants').status_code, 400)
        self.assertEqual(self.client.post('/replay/start', json={'resume':True}).status_code, 409)
        self.assertEqual(self.client.post('/replay/start', data='x', content_type='text/plain').status_code, 400)
        self.assertEqual(self.client.post('/replay/start', data='x'*17000, content_type='application/json').status_code, 413)
        self.client.post('/replay/start', json={'speedup':100})
        self.assertEqual(self.client.post('/replay/start', json={}).status_code, 409)
        self.client.post('/replay/pause')
        self.wait(self.client, {'paused'})

    def test_rejects_changed_inputs_and_corrupt_checkpoint(self):
        self.client.post('/replay/start', json={'speedup':100000})
        self.wait(self.client, {'completed'})
        self.data.joinpath('buildings.csv').write_text('bbl,latitude,longitude,unitsres\n1017700040,40,-73,7\n')
        with self.assertRaisesRegex(ValueError, 'Checkpoint invalid'):
            module.create_app(self.data)
        self.data.joinpath('realtime_checkpoint.json').write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'Checkpoint invalid'):
            module.create_app(self.data)

if __name__ == '__main__':
    unittest.main(verbosity=2)
