"""Synthetic tests; never train or change the supplied deployment model."""
from collections import namedtuple
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parent))
from app import create_app
from replay_model import ModelReplay, xgboost_module

FEATURES = ['c_last1','c_last2','v_last1','v_last2','chronic','c_prev7','c_prev14','c_prev30',
            'rate_frigid2','rate_freezing2','rate_cold2','days_since_c','days_since_v',
            'bw_last1','bw_prev14','lord_nbldg','lord_c_other_last1','boiler_defects','fuel_oil',
            'c_prev2','nb_block_2d','days_into_cold','unitsres','yearbuilt','altered','numfloors',
            'bldgarea','cd','TMIN','TMAX','tmin_lag1','tmin_roll3','tmin_drop','SNOW','AWND','wday_num']
Event = namedtuple('Event','bbl received_date minor_category')

class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.data=self.root/'data'; self.data.mkdir()
        self.out=self.root/'model/out'; self.out.mkdir(parents=True)
        self.ids=['1000050010','1000050020','2000060010']
        pd.DataFrame({'bbl':self.ids,'latitude':[40,41,42],'longitude':[-73,-74,-75],
                      'unitsres':[10,20,30]}).to_csv(self.data/'buildings.csv',index=False)
        pd.DataFrame({'bbl':[self.ids[i%2] for i in range(24)],
                      'received_date':[f'2026-02-07 00:00:{i:02}' for i in range(24)],
                      'complaint_id':[f'c{i}' for i in range(24)],
                      'minor_category':['ENTIRE BUILDING' if i%2 else 'APARTMENT ONLY' for i in range(24)]
                      }).to_csv(self.data/'replay_feb7_9.csv',index=False)
        hist=pd.DataFrame({'bbl':[self.ids[0],self.ids[1],self.ids[0],self.ids[0]],
                           'day':['2026-02-05','2026-02-06','2026-01-08','2026-02-08'],
                           'n':[2,3,4,900]})
        hist.to_csv(self.out/'building_day_counts.csv',index=False)
        hist.iloc[[0]].to_csv(self.out/'building_day_counts_bw.csv',index=False)
        dates=pd.date_range('2026-01-01','2026-02-12')
        pd.DataFrame({'day':dates,'TMIN':np.arange(len(dates))%20,'TMAX':30,'tmin_lag1':10,
                      'SNOW':0,'AWND':2}).to_csv(self.data/'days.csv',index=False)
        f=pd.DataFrame(0.,index=range(3),columns=FEATURES)
        f['bbl']=self.ids; f['unitsres']=[10,20,30]; f['yearbuilt']=1950; f['days_since_v']=9999
        f.to_csv(self.out/'building_features.csv',index=False)
        (self.out/'feature_schema.json').write_text(json.dumps({'asof':'2026-02-06',
                   'feats_in_model_order':FEATURES,'never_sentinel':9999}))
        # A tiny synthetic model ensures tests work with the native API on s390x.
        xgb=xgboost_module()
        rng=np.random.default_rng(2)
        X=rng.random((40,len(FEATURES)),dtype=np.float32)
        train=xgb.DMatrix(X,label=(X[:,5]>.5).astype(int),feature_names=FEATURES,nthread=1)
        model=xgb.train({'objective':'binary:logistic','max_depth':2,'nthread':1},train,num_boost_round=3)
        model.save_model(self.out/'heat_model_final.json')
        pd.DataFrame({'score':[0.,1.],'y':[0.,1.],'weight':[1.,1.]}).to_csv(self.out/'calibration.csv',index=False)

    def tearDown(self): self.tmp.cleanup()
    def engine(self): return ModelReplay(self.data,self.out,pd.Timestamp('2026-02-07'))
    def app(self): return create_app(self.data,checkpoint_every=2,model_dir=self.out).test_client()
    def wait(self,c,statuses):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            s=c.get('/stats').get_json()
            if s['status'] in statuses: return s
            if s['status']=='error': self.fail(s['error'])
            time.sleep(.005)
        self.fail('worker timed out')

    def test_window_expiry_neighbors_and_no_future_history(self):
        m=self.engine(); col=m.col
        self.assertEqual(m.X[0,col['c_prev2']],2)
        self.assertEqual(m.X[0,col['c_prev30']],6)
        self.assertEqual(m.X[0,col['nb_block_2d']],3)
        self.assertEqual(m.X[1,col['nb_block_2d']],2)
        self.assertEqual(m.X[2,col['days_since_c']],9999)
        m.event(Event(self.ids[0],pd.Timestamp('2026-02-07 10:00'),'ENTIRE BUILDING'))
        self.assertEqual(m.X[0,col['c_prev2']],3)
        self.assertEqual(m.X[0,col['bw_prev14']],3)
        self.assertEqual(m.X[1,col['nb_block_2d']],3)
        # Unknown building still affects known block neighbors but is not ranked.
        m.event(Event('1000050099',pd.Timestamp('2026-02-07 11:00'),'APARTMENT ONLY'))
        self.assertEqual(m.skipped,1)
        self.assertEqual(m.X[0,col['nb_block_2d']],4)
        m.rollover('2026-02-08')
        self.assertEqual(m.X[0,col['c_prev2']],1)  # Feb 5 expired, Feb 7 retained
        self.assertEqual(m.X[0,col['c_prev30']],3) # Jan 8 expired
        self.assertEqual(m.X[0,col['days_since_c']],1)
        self.assertLess(m.X[0,col['c_prev30']],900) # future-history row ignored

    def test_pause_restart_resume_and_reset(self):
        c=self.app(); c.post('/replay/start',json={'speedup':100000})
        self.wait(c,{'completed'}); expected=c.get('/queue').get_json()
        c.post('/replay/start',json={'speedup':100})
        time.sleep(.06); c.post('/replay/pause')
        paused=self.wait(c,{'paused'}); self.assertTrue(0<paused['processed']<24)
        restored=self.app()
        state=restored.get('/stats').get_json()
        self.assertEqual(state['processed'],paused['processed'])
        self.assertTrue(state['restored_from_checkpoint'])
        self.assertEqual(restored.post('/replay/start',json={'resume':True,'speedup':100000}).status_code,202)
        state=self.wait(restored,{'completed'})
        self.assertEqual(state['checkpoint_processed'],24)
        self.assertEqual(restored.get('/queue').get_json(),expected)
        restored.post('/replay/start',json={'speedup':100000})
        self.wait(restored,{'completed'})
        self.assertEqual(restored.get('/queue').get_json(),expected)

    def test_recovery_across_day_boundary(self):
        m=self.engine()
        events=[Event(self.ids[0],pd.Timestamp('2026-02-07 10:00'),'ENTIRE BUILDING'),
                Event(self.ids[1],pd.Timestamp('2026-02-08 12:00'),'APARTMENT ONLY'),
                Event(self.ids[0],pd.Timestamp('2026-02-09 11:00'),'ENTIRE BUILDING')]
        for ev in events: m.event(ev)
        expected_X=m.X.copy(); expected_p=m.p.copy()
        m.restore_prefix(events,2); m.event(events[2])
        np.testing.assert_array_equal(m.X,expected_X)
        np.testing.assert_allclose(m.p,expected_p,rtol=0,atol=0)

    def test_validation_and_input_fingerprint(self):
        c=self.app()
        for body in ([],None,True,{'speedup':True},{'speedup':0},{'speedup':'600'},{'resume':'true'},{'x':1}):
            r=c.post('/replay/start',data=json.dumps(body),content_type='application/json')
            self.assertEqual(r.status_code,400)
        self.assertEqual(c.get('/queue?k=0').status_code,400)
        self.assertEqual(c.get('/queue?sort=tenants').status_code,200)
        c.post('/replay/start',json={'speedup':100000}); self.wait(c,{'completed'})
        with (self.out/'calibration.csv').open('a') as f: f.write('\n')
        with self.assertRaisesRegex(ValueError,'Checkpoint invalid'): self.app()

if __name__=='__main__': unittest.main(verbosity=2)
