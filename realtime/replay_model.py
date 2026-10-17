"""Native XGBoost scoring with deterministic, building-level replay state."""
from collections import defaultdict
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression


def xgboost_module():
    try:
        import xgboost
    except ModuleNotFoundError as exc:
        if exc.name != 'xgboost':
            raise
        # Ubuntu's s390x XGBoost; keep the active venv's other packages first.
        sys.path.append('/usr/lib/python3/dist-packages')
        import xgboost
    return xgboost


def normalize_bbl(values):
    v = pd.to_numeric(values, errors='raise')
    if v.isna().any() or (v % 1 != 0).any():
        raise ValueError('BBLs must be non-missing integers')
    return v.astype('int64').astype(str)


class ModelReplay:
    mode = 'xgboost_final_isotonic_cpu'
    def __init__(self, data, out, first_day):
        self.data, self.out = Path(data), Path(out)
        self.first_day = pd.Timestamp(first_day).normalize()
        self.schema = json.loads((self.out/'feature_schema.json').read_text())
        self.features = self.schema['feats_in_model_order']
        self.never = self.schema.get('never_sentinel', 9999)
        self.asof = pd.Timestamp(self.schema['asof']).normalize()
        if self.asof != self.first_day - pd.Timedelta(days=1):
            raise ValueError('Feature snapshot must be dated the day before replay starts')
        f = pd.read_csv(self.out/'building_features.csv')
        f['bbl'] = normalize_bbl(f.bbl)
        if f.bbl.duplicated().any():
            raise ValueError('Feature matrix contains duplicate buildings')
        self.ids = f.bbl.tolist()
        self.index = {b:i for i,b in enumerate(self.ids)}
        self.blocks = np.array([int(b)//10000 for b in self.ids])
        self.members = defaultdict(list)
        for i, block in enumerate(self.blocks):
            self.members[int(block)].append(i)
        self.base = f[self.features].to_numpy(dtype=np.float32)
        if np.isinf(self.base).any():
            raise ValueError('Infinite feature values')
        self.col = {name:i for i,name in enumerate(self.features)}
        self.xgb = xgboost_module()
        self.model = self.xgb.Booster()
        self.model.load_model(self.out/'heat_model_final.json')
        self.model.set_param({'nthread':1})
        if self.model.num_features() != len(self.features):
            raise ValueError('Model and schema feature counts differ')
        if self.model.feature_names and self.model.feature_names != self.features:
            raise ValueError('Model and schema feature orders differ')
        calibration = pd.read_csv(self.out/'calibration.csv')
        self.iso = IsotonicRegression(out_of_bounds='clip')
        self.iso.fit(calibration.score, calibration.y, sample_weight=calibration.weight)
        self.initial_days = self.history(self.out/'building_day_counts.csv')
        self.initial_bw = self.history(self.out/'building_day_counts_bw.csv')
        # Keep only pre-replay history. Future rows in handoff files are ignored.
        self.last_initial = np.full(len(self.ids), np.datetime64('NaT', 'D'), dtype='datetime64[D]')
        for day, bucket in self.initial_days.items():
            for b in bucket:
                i = self.index.get(b)
                if i is not None and (np.isnat(self.last_initial[i]) or np.datetime64(day, 'D') > self.last_initial[i]):
                    self.last_initial[i] = np.datetime64(day, 'D')
        lower = (self.first_day - pd.Timedelta(days=30)).date()
        self.initial_days = {d:b for d,b in self.initial_days.items() if d >= lower}
        self.initial_bw = {d:b for d,b in self.initial_bw.items() if d >= lower}
        self.days = pd.read_csv(self.data/'days.csv', parse_dates=['day']).sort_values('day')
        self.days['tmin_roll3'] = self.days.TMIN.rolling(3).min()
        self.days['tmin_drop'] = self.days.TMIN.diff()
        self.days['wday_num'] = self.days.day.dt.weekday
        if self.days.day.duplicated().any():
            raise ValueError('Weather file has duplicate dates')
        season = self.first_day.year if self.first_day.month >= 10 else self.first_day.year-1
        d = self.days
        seasons = np.where(d.day.dt.month >= 10, d.day.dt.year, d.day.dt.year-1)
        cold = d[(seasons == season) & (d.day <= self.first_day) & (((d.TMIN+d.TMAX)/2) < 55)]
        self.first_cold = cold.day.min() if len(cold) else None
        self.weather = self.days.set_index('day')
        self.batch_timings = []
        self.reset()

    def history(self, path):
        df = pd.read_csv(path, parse_dates=['day'])
        df = df[df.day < self.first_day].copy()
        df['bbl'] = normalize_bbl(df.bbl)
        buckets = defaultdict(dict)
        for b, day, n in df[['bbl','day','n']].itertuples(index=False, name=None):
            if not np.isfinite(n) or n < 0 or n != int(n):
                raise ValueError('History counts must be nonnegative integers')
            date = day.date()
            buckets[date][b] = buckets[date].get(b, 0) + int(n)
        return dict(buckets)

    def reset(self):
        self.X = self.base.copy()
        self.buckets = {d:dict(b) for d,b in self.initial_days.items()}
        self.bw_buckets = {d:dict(b) for d,b in self.initial_bw.items()}
        self.last = self.last_initial.copy()
        self.counts = {}
        self.skipped = 0
        self.predictions = 0
        self.batch_timings = []
        self.day = None
        self.raw = np.zeros(len(self.ids))
        self.p = np.zeros(len(self.ids))
        self.rollover(self.first_day)
        self.initial_batch = dict(self.batch_timings[-1])

    def predict(self, indices=None):
        values = self.X if indices is None else self.X[indices]
        matrix = self.xgb.DMatrix(values, feature_names=self.features, nthread=1)
        raw = self.model.predict(matrix)
        p = self.iso.predict(raw)
        if not np.isfinite(raw).all() or not np.isfinite(p).all():
            raise ValueError('Model produced non-finite predictions')
        if indices is None:
            self.raw[:], self.p[:] = raw, p
        else:
            self.raw[indices], self.p[indices] = raw, p
        return len(values)

    def rollover(self, day, score=True):
        day = pd.Timestamp(day).normalize()
        if day not in self.weather.index:
            raise ValueError(f'Missing weather for {day.date()}')
        if self.day is not None and day < self.day:
            raise ValueError('Replay timestamps must be nondecreasing')
        minimum = (day-pd.Timedelta(days=30)).date()
        self.buckets = {d:b for d,b in self.buckets.items() if d >= minimum}
        self.bw_buckets = {d:b for d,b in self.bw_buckets.items() if d >= minimum}
        for w in (2,7,14,30):
            own = np.zeros(len(self.ids))
            lower = (day-pd.Timedelta(days=w)).date()
            block_counts = defaultdict(int)
            for d, bucket in self.buckets.items():
                if lower <= d <= day.date():
                    for b,n in bucket.items():
                        i = self.index.get(b)
                        if i is not None:
                            own[i] += n
                        if w == 2:
                            block_counts[int(b)//10000] += n
            self.X[:, self.col[f'c_prev{w}']] = own
            if w == 2:
                self.block_counts = block_counts
                self.X[:,self.col['nb_block_2d']] = np.maximum(
                    np.array([block_counts[int(b)] for b in self.blocks])-own, 0)
        wide = np.zeros(len(self.ids))
        lower = (day-pd.Timedelta(days=14)).date()
        for d,bucket in self.bw_buckets.items():
            if lower <= d <= day.date():
                for b,n in bucket.items():
                    i = self.index.get(b)
                    if i is not None:
                        wide[i] += n
        self.X[:,self.col['bw_prev14']] = wide
        since = (np.datetime64(day.date(),'D')-self.last).astype('timedelta64[D]').astype(float)
        self.X[:,self.col['days_since_c']] = np.where(np.isnat(self.last), self.never, since)
        # Violation history is frozen at the supplied snapshot; age it with clock.
        base_v = self.base[:,self.col['days_since_v']]
        self.X[:,self.col['days_since_v']] = np.where(base_v >= self.never, self.never,
                                                     base_v + (day-self.asof).days)
        weather = self.weather.loc[day]
        for name in ('TMIN','TMAX','tmin_lag1','tmin_roll3','tmin_drop','SNOW','AWND','wday_num'):
            value = float(weather[name])
            if not np.isfinite(value):
                raise ValueError(f'Invalid weather field {name} for {day.date()}')
            self.X[:,self.col[name]] = value
        self.X[:,self.col['days_into_cold']] = max(0,(day-self.first_cold).days) if self.first_cold is not None else 0
        self.day = day
        if score:
            t0 = time.perf_counter()
            self.predict()
            seconds = time.perf_counter()-t0
            self.batch_timings.append(dict(day=str(day.date()), buildings=len(self.ids),
                                          seconds=seconds, buildings_per_second=len(self.ids)/seconds))

    def event(self, ev, score=True):
        day = pd.Timestamp(ev.received_date).normalize()
        if day != self.day:
            self.rollover(day, score=score)
        b = str(ev.bbl)
        self.counts[b] = self.counts.get(b,0)+1
        bucket = self.buckets.setdefault(day.date(),{})
        bucket[b] = bucket.get(b,0)+1
        wide = str(ev.minor_category) == 'ENTIRE BUILDING'
        if wide:
            bucket = self.bw_buckets.setdefault(day.date(),{})
            bucket[b] = bucket.get(b,0)+1
        i = self.index.get(b)
        if i is not None:
            for w in (2,7,14,30):
                self.X[i,self.col[f'c_prev{w}']] += 1
            self.X[i,self.col['days_since_c']] = 0
            self.last[i] = np.datetime64(day.date(),'D')
            if wide:
                self.X[i,self.col['bw_prev14']] += 1
        else:
            self.skipped += 1
        block = int(b)//10000
        self.block_counts[block] += 1
        affected = self.members.get(block, [])
        for j in affected:
            self.X[j,self.col['nb_block_2d']] = max(0,self.block_counts[block]-self.X[j,self.col['c_prev2']])
        if score and affected:
            self.predictions += self.predict(affected)
        return len(affected)

    def restore_prefix(self, rows, n):
        self.reset()
        for ev in rows[:n]:
            self.event(ev, score=False)
        self.predict()  # Deterministically rebuild feature state; batch score once.

    def queue(self,k,sort,metadata):
        values = self.p * np.nan_to_num(self.X[:,self.col['unitsres']],nan=0) if sort=='tenants' else self.raw
        order = sorted(range(len(self.ids)), key=lambda i:(-float(values[i]),self.ids[i]))[:k]
        result = []
        for rank,i in enumerate(order,1):
            b = self.ids[i]
            p = float(self.p[i])
            units = float(self.X[i,self.col['unitsres']])
            units = units if np.isfinite(units) else None
            row = dict(metadata.get(b,{}))
            row.update(rank=rank,bbl=b,score=p,p_calibrated=p,raw_score=float(self.raw[i]),
                       replay_complaints=self.counts.get(b,0),unitsres=units,
                       tenants_at_risk=p*units if units is not None else None)
            result.append(row)
        return result
