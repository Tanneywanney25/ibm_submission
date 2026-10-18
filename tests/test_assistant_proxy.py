"""Run from repo root; validates Vercel-safe imports and signed proxy behavior."""
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ,{'APP_MODE':'lite','ASSISTANT_PROXY_SECRET':'s'*64,'FLASK_SECRET_KEY':'','REGISTER_FORWARD_URL':''})
        cls.env.start()
        sys.path.insert(0,str(ROOT/'web'))
        spec=importlib.util.spec_from_file_location('assistant_web_under_test',ROOT/'web/app.py')
        cls.module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=cls.module
        spec.loader.exec_module(cls.module)
        cls.client=cls.module.app.test_client()

    @classmethod
    def tearDownClass(cls):cls.env.stop()

    def test_assistant_and_original_monitor_routes(self):
        r=self.client.get('/monitor')
        self.assertEqual(r.status_code,200)
        self.assertIn(b'id="ask-form"',r.data)
        self.assertIn(b'/monitor?mode=current',r.data)
        self.assertIn(b'id="current-banner"',self.client.get('/monitor?mode=current').data)
        self.assertNotIn(b'id="ask-form"',self.client.get('/monitor?mode=replay').data)

    def test_origin_and_endpoint_validation(self):
        self.assertEqual(self.client.post('/api/assistant/jobs',json={'question':'hello'}).status_code,403)
        self.assertEqual(self.client.post('/api/assistant/jobs',headers={'Origin':'https://evil.example'},json={'question':'hello'}).status_code,403)
        self.assertEqual(self.client.get('/api/assistant/keys').status_code,404)
        self.assertEqual(self.client.get('/api/assistant/jobs/not-a-job').status_code,404)

    def test_signed_response_and_no_credentials_in_payload(self):
        import assistant_proxy
        def upstream(method,url,**kwargs):
            body=b'{"status":"ok","model_configured":true}'
            nonce=kwargs['headers']['X-HA-Nonce']
            class R:
                content=body;status_code=200
                headers={'X-HA-Response':hmac.new(b's'*64,nonce.encode()+b'\n'+body,hashlib.sha256).hexdigest()}
                def json(self):return json.loads(body)
            return R()
        with patch.object(assistant_proxy.requests,'request',side_effect=upstream):
            r=self.client.get('/api/assistant/health')
        self.assertEqual(r.status_code,200)
        self.assertNotIn(b's'*64,r.data)
        self.assertIn('no-store',r.headers['Cache-Control'])

    def test_tampered_reply_fails_closed(self):
        import assistant_proxy
        class R:
            content=b'{"status":"ok"}';status_code=200;headers={}
            def json(self):return {'status':'ok'}
        with patch.object(assistant_proxy.requests,'request',return_value=R()):
            r=self.client.get('/api/assistant/health')
        self.assertEqual(r.status_code,503)
        self.assertTrue(r.json['offline'])

    def test_same_origin_job_submission(self):
        import assistant_proxy
        def upstream(method,url,**kwargs):
            self.assertEqual(method,'POST')
            self.assertEqual(json.loads(kwargs['data']),{'question':'Show complaints'})
            body=json.dumps({'id':'a'*48,'status':'queued'}).encode()
            nonce=kwargs['headers']['X-HA-Nonce']
            class R:
                content=body;status_code=202
                headers={'X-HA-Response':hmac.new(b's'*64,nonce.encode()+b'\n'+body,hashlib.sha256).hexdigest()}
                def json(self):return json.loads(body)
            return R()
        with patch.object(assistant_proxy.requests,'request',side_effect=upstream):
            r=self.client.post('/api/assistant/jobs',headers={'Origin':'http://localhost'},json={'question':'Show complaints'})
        self.assertEqual(r.status_code,202)


if __name__=='__main__':unittest.main()
