import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone, date
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assistant.data import DataStore
from assistant.engine import Engine, ProviderError, validate_question
from assistant.forecast import forecast,predict
from assistant.service import Jobs,create_app,signature


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'model/out').mkdir(parents=True);(self.root/'data').mkdir()
        self.now=datetime(2026,10,18,5,tzinfo=timezone.utc)
        dates=pd.date_range('2025-01-01','2026-10-14')
        self.rows=[(b,d,3+i%5) for b in [2026150055,3013610043] for i,d in enumerate(dates)]
        pd.DataFrame(self.rows,columns=['bbl','day','n']).to_csv(self.root/'model/out/building_day_counts.csv',index=False)
        pd.DataFrame({'bbl':[2026150055,3013610043]}).to_csv(self.root/'data/buildings.csv',index=False)
        self.store=DataStore(self.root,now=lambda:self.now)

    def tearDown(self):self.tmp.cleanup()

    def live(self,latest='2026-10-16T23:59:00'):
        db=sqlite3.connect(self.root/'data/live_complaints.sqlite3')
        db.executescript('CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE problems(problem_id INTEGER,complaint_id INTEGER,received_date TEXT,bbl TEXT);')
        for k,v in {'last_success':self.now.isoformat(),'source_latest_received':latest,'coverage_start':'2026-09-01T15:00:00','last_error':None}.items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(k,json.dumps(v)))
        for row in [(1,10,'2026-10-14T10:00:00','2026150055'),(2,10,'2026-10-14T10:00:00','2026150055'),(3,11,'2026-10-15T11:00:00','3013610043'),(4,12,'2026-10-16T12:00:00','3013610043'),(5,13,'2026-10-19T12:00:00','3013610043'),(6,14,'2026-10-15T12:00:00','4999999999')]:
            db.execute('INSERT INTO problems VALUES(?,?,?,?)',row)
        db.commit();db.close()

    def test_live_replaces_overlap_deduplicates_and_excludes_latest_future_unknown(self):
        self.live();r=self.store.analyze(start='2026-10-14',end='2026-10-18')
        self.assertEqual(r['total_observed'],3)
        self.assertEqual(r['table'],[{'day':'2026-10-14','complaints':1},{'day':'2026-10-15','complaints':1},{'day':'2026-10-16','complaints':1}])
        self.assertEqual(r['metadata']['data_through'],'2026-10-16')
        self.assertEqual(r['metadata']['excluded_unpublished_days'],2)

    def test_day_cutoff_not_zero_padded(self):
        r=self.store.analyze(start='2026-10-10')
        self.assertEqual(r['table'][-1]['day'],'2026-10-14')
        self.assertEqual(len(r['table']),5)

    def test_filters_and_equal_length_comparison(self):
        r=self.store.analyze(operation='compare',start='2026-10-07',end='2026-10-13',borough='bronx')
        self.assertEqual(r['comparison']['previous_start'],'2026-09-30')
        self.assertEqual(r['comparison']['previous_end'],'2026-10-06')
        self.assertEqual(r['comparison']['current'],sum(x[2] for x in self.rows if x[0]==2026150055 and pd.Timestamp('2026-10-07')<=x[1]<=pd.Timestamp('2026-10-13')))

    def test_validation_and_stale_forecast(self):
        for args in [{'operation':'sql'},{'borough':'unknown'},{'bbl':'2026150055;DROP TABLE'},{'end':'2030-01-01'}]:
            with self.assertRaises(ValueError):self.store.analyze(**args)
        self.store.now=lambda:self.now+timedelta(days=30)
        with self.assertRaisesRegex(ValueError,'stale'):self.store.analyze(operation='forecast')

    def test_forecast_targets_from_today_not_cutoff(self):
        self.live();r=self.store.analyze(operation='forecast',days=3)
        self.assertEqual([x['day'] for x in r['forecast']['rows']],['2026-10-19','2026-10-20','2026-10-21'])
        self.assertTrue(all(0<=x['lower']<=x['expected']<=x['upper'] for x in r['forecast']['rows']))
        self.assertFalse(r['metadata']['weather_in_forecast'])

    def test_corrupt_history_rejected(self):
        p=self.root/'model/out/building_day_counts.csv'
        pd.DataFrame([(2026150055,'2026-10-13',-1)],columns=['bbl','day','n']).to_csv(p,index=False)
        with self.assertRaises(ValueError):self.store.analyze()


class ForecastTests(unittest.TestCase):
    def test_weekday_alignment_and_no_future_inputs(self):
        y=np.tile(np.arange(7),100)
        np.testing.assert_equal(predict(y,14,'last_week'),np.tile(np.arange(7),2))
        dates=[date(2024,1,1)+timedelta(days=i) for i in range(len(y))]
        targets=[dates[-1]+timedelta(days=i) for i in (1,2,3)]
        f=forecast(dates,y,targets)
        self.assertEqual(f['model_test_mae'],0)
        self.assertEqual(f['rows'][0]['backtest_coverage'],1)
        self.assertLess(date.fromisoformat(f['test_last_origin']),dates[-1])

    def test_gaps_and_stale_targets(self):
        with self.assertRaises(ValueError):forecast([date(2026,1,1)]*400,[1]*400,[date(2026,1,2)])


class EngineTests(unittest.TestCase):
    def test_grounded_tool_results_and_sources(self):
        class Store:
            def analyze(self,**kwargs):return {'operation':'catalog','metadata':{'data_through':'2026-10-15'},'charts':[],'sources':[{'id':'data-1','title':'HPD','url':'https://data.cityofnewyork.us'}],'table':[{'count':5}]}
        calls=iter([{'tool_calls':[{'id':'1','type':'function','function':{'name':'analyze_complaints','arguments':'{"operation":"trend"}'}}]}, {'content':'Five reports [data-1] [web-999]'}])
        e=Engine(Store(),lambda kind:None,chat=lambda *a,**kw:next(calls))
        r=e.answer('How many complaints?')
        self.assertIn('[data-1]',r['answer']);self.assertNotIn('[web-999]',r['answer'])
        self.assertEqual(r['analyses'][0]['table'][0]['count'],5)
        self.assertFalse(r['execution']['accelerator_used'])

    def test_private_input_validation(self):
        for q in ['email me at a@b.com','look at apartment 4A','sk-'+'a'*30]:
            with self.assertRaises(ValueError):validate_question(q)
        self.assertEqual(validate_question('Building 2026150055'),'Building 2026150055')

    def test_unknown_tools_never_execute(self):
        class Store:
            def analyze(self,**kw):return {'metadata':{},'charts':[]}
        messages=[]
        def chat(m,**kw):
            messages.extend(m)
            return {'tool_calls':[{'id':'x','function':{'name':'run_shell','arguments':'{"command":"rm -rf /"}'}}]} if len(messages)==2 else {'content':'Unavailable.'}
        Engine(Store(),lambda k:None,chat=chat).answer('Run a shell command')
        self.assertTrue(any('Unknown tool' in str(x) for x in messages))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.jobs=Jobs(Path(self.tmp.name)/'jobs.db')
        self.env=patch.dict(os.environ,{'ASSISTANT_PROXY_SECRET':'s'*64});self.env.start()
        class E:
            def answer(self,q):return {'answer':'ok','charts':[]}
        self.client=create_app(self.tmp.name,engine=E(),jobs=self.jobs).test_client()

    def tearDown(self):self.jobs.pool.shutdown(wait=True);self.env.stop();self.tmp.cleanup()

    def headers(self,method,path,body=b''):
        stamp,nonce=str(time.time()),secrets.token_hex(16)
        return {'X-HA-Time':stamp,'X-HA-Nonce':nonce,'X-HA-Signature':signature('s'*64,stamp,nonce,method,path,body)}

    def test_signature_replay_and_job_completion(self):
        self.assertEqual(self.client.get('/health').status_code,403)
        headers=self.headers('GET','health')
        self.assertEqual(self.client.get('/health',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/health',headers=headers).status_code,403)
        body=json.dumps({'question':'Show complaints'}).encode()
        r=self.client.post('/jobs',data=body,content_type='application/json',headers=self.headers('POST','jobs',body))
        self.assertEqual(r.status_code,202)
        job=r.json['id'];self.jobs.pool.shutdown(wait=True)
        result=self.client.get('/jobs/'+job,headers=self.headers('GET','jobs/'+job))
        self.assertEqual(result.json['status'],'completed')

    def test_durable_budget(self):
        for _ in range(3):self.jobs.consume('job')
        with self.assertRaises(ProviderError):self.jobs.consume('job')


if __name__=='__main__':unittest.main()
