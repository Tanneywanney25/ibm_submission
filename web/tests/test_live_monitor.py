"""Published complaint monitor contracts; no external calls or production state."""
import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import uuid

import requests
from werkzeug.serving import make_server

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'web'))
sys.path.insert(0,str(ROOT/'realtime'))
from complaint_pipeline import create_app, poll, utcnow, NY


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        name='monitor_web_'+uuid.uuid4().hex
        spec=importlib.util.spec_from_file_location(name,ROOT/'web/app.py')
        self.web=importlib.util.module_from_spec(spec)
        sys.modules[name]=self.web
        with patch.dict(os.environ,{'APP_MODE':'lite','FLASK_SECRET_KEY':'','GOOGLE_CLIENT_ID':'',
                                   'GOOGLE_CLIENT_SECRET':'','REGISTER_FORWARD_URL':'','GUIDE_AI_KEY':''}):
            spec.loader.exec_module(self.web)
        self.web.DB=Path(self.temp.name)/'accounts.sqlite3'
        self.client=self.web.app.test_client()

    def test_current_and_replay_tabs_render_without_model_inputs(self):
        current=self.client.get('/monitor?mode=current')
        replay=self.client.get('/monitor?mode=replay')
        self.assertEqual(current.status_code,200)
        self.assertEqual(replay.status_code,200)
        self.assertIn(b'id="current-events"',current.data)
        self.assertIn(b'publication delay',current.data)
        self.assertNotIn(b'Start replay',current.data)
        self.assertIn(b'Start replay',replay.data)
        self.assertNotIn(b'id="current-events"',replay.data)
        ids=re.findall(rb'\bid="([^"\s]+)"',current.data)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertFalse(self.web.DB.exists())

    def test_offline_bad_json_and_read_only_allowlist(self):
        with patch.object(self.web.requests,'get',side_effect=requests.ConnectionError()):
            result=self.client.get('/api/current/stats')
            self.assertEqual(result.status_code,503)
            self.assertTrue(result.json['offline'])
        with patch.object(self.web.requests,'get',return_value=Mock(json=Mock(side_effect=ValueError()))):
            self.assertEqual(self.client.get('/api/current/events').status_code,503)
        self.assertEqual(self.client.get('/api/current/unknown').status_code,404)
        self.assertEqual(self.client.post('/api/current/events',json={}).status_code,405)
        self.assertFalse(self.web.DB.exists())

    def test_collector_to_same_origin_proxy_end_to_end(self):
        path=Path(self.temp.name)/'complaints.sqlite3'
        now=utcnow()
        stamp=now.astimezone(NY).replace(tzinfo=None).isoformat(timespec='milliseconds')
        # Poll excludes its upper bound; put this report one second earlier.
        from datetime import timedelta
        stamp=(now-timedelta(seconds=1)).astimezone(NY).replace(tzinfo=None).isoformat(timespec='milliseconds')
        row=dict(received_date=stamp,problem_id='1',complaint_id='10',building_id='123',
                 borough='BRONX',block='3212',lot='92',problem_code='NO HEAT')
        def source(query):
            return [row] if '$where' in query else [{'newest':stamp}]
        poll(path,fetch=source,now=now)
        server=make_server('127.0.0.1',0,create_app(path))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.web.COMPLAINT_URL=f'http://127.0.0.1:{server.server_port}'
        try:
            stats=self.client.get('/api/current/stats')
            events=self.client.get('/api/current/events')
            queue=self.client.get('/api/current/queue?k=5')
            self.assertEqual(stats.status_code,200)
            self.assertEqual(stats.json['complaints_7d'],1)
            self.assertEqual(events.json['events'][0]['bbl'],'2032120092')
            self.assertEqual(queue.json['buildings'][0]['complaints_7d'],1)
            self.assertEqual(self.client.get('/api/current/queue?k=abc').status_code,400)
        finally:
            server.shutdown();thread.join()


if __name__=='__main__':unittest.main(verbosity=2)
