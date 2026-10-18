"""Read only approved, building-level data; never read account or key files."""
from datetime import datetime, timedelta, timezone, date
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .forecast import forecast

NY = ZoneInfo('America/New_York')
BOROUGHS = {'manhattan':1,'bronx':2,'brooklyn':3,'queens':4,'staten island':5}
NAMES = {v:k.title() for k,v in BOROUGHS.items()}
SOURCE = 'https://data.cityofnewyork.us/Housing-Development/Housing-Maintenance-Code-Complaints-and-Problems/ygpa-z7cr'


class DataStore:
    def __init__(self, root, now=None):
        self.root = Path(root)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._fingerprint = None
        self.frame = None

    def load(self):
        path = self.root/'model/out/building_day_counts.csv'
        fingerprint = (path.stat().st_mtime_ns, path.stat().st_size)
        if fingerprint != self._fingerprint:
            frame = pd.read_csv(path, dtype={'bbl':'int64'}, parse_dates=['day'])
            if not {'bbl','day','n'} <= set(frame.columns):
                raise ValueError('History schema missing bbl,day,n')
            if frame[['bbl','day','n']].isna().any().any() or frame.duplicated(['bbl','day']).any():
                raise ValueError('Invalid or duplicate historical counts')
            if ((frame.bbl < 1000000000)|(frame.bbl >= 6000000000)).any():
                raise ValueError('Invalid historical building identifiers')
            if not np.isfinite(frame.n).all() or (frame.n < 0).any() or (frame.n % 1 != 0).any():
                raise ValueError('History requires nonnegative integer counts')
            if (frame.day != frame.day.dt.normalize()).any():
                raise ValueError('History must use calendar-day timestamps')
            self.frame = frame[['bbl','day','n']].copy()
            self._fingerprint = fingerprint
        # The building panel defines coverage. Never silently broaden historical
        # counts with live records outside the training extract's building universe.
        bpath = self.root/'data/buildings.csv'
        ids = set(pd.read_csv(bpath, usecols=['bbl'], dtype={'bbl':'int64'}).bbl)
        return self.frame[self.frame.bbl.isin(ids)].copy(), ids

    def view(self, forecast_only=False):
        frame, ids = self.load()
        now = self.now().astimezone(NY)
        today = now.date()
        # Historical maximum may be an incomplete source day: exclude the latest
        # received-date day unless the snapshot has an explicit coverage manifest.
        historical_latest = frame.day.max().date()
        cutoff = min(historical_latest-timedelta(days=1), today-timedelta(days=2)) if forecast_only else min(historical_latest,today)
        first = frame.day.min().date()
        metadata = {'historical_latest_received_day':str(historical_latest),
                    'source_latest_received':None, 'last_successful_poll':None,
                    'cutoff_policy':'conservative forecast inputs' if forecast_only else 'published observations; latest dates may be partial',
                    'now':now.isoformat(), 'publication_delay':'Received timestamps do not establish publication completeness. Latest source day and today are excluded from forecast inputs.',
                    'scope':'Distinct heat complaints in the historical building universe; not all NYC properties or confirmed outages.',
                    'count_source':SOURCE, 'weather_in_forecast':False}
        dbpath = self.root/'data/live_complaints.sqlite3'
        live = None
        begin = None
        if dbpath.is_file():
            with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro', uri=True, timeout=5) as db:
                db.execute('BEGIN')
                meta = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
                latest = meta.get('source_latest_received')
                last = meta.get('last_success')
                metadata.update(source_latest_received=latest,last_successful_poll=last)
                fresh = last and (self.now()-datetime.fromisoformat(last)).total_seconds() <= 900
                if fresh and not meta.get('last_error') and latest and meta.get('coverage_start'):
                    covered = datetime.fromisoformat(meta['coverage_start'])
                    begin = covered.date() + (timedelta(days=1) if covered.time() != datetime.min.time() else timedelta())
                    latest_day=datetime.fromisoformat(latest).date()
                    live_cutoff = min(latest_day-timedelta(days=1), today-timedelta(days=2)) if forecast_only else min(latest_day,today)
                    # Replace overlapping days, never add counts from two extracts.
                    if begin <= cutoff+timedelta(days=1) and live_cutoff >= begin:
                        rows = db.execute('''SELECT complaint_id,MIN(received_date),
                          CASE WHEN COUNT(DISTINCT bbl)=1 THEN MAX(bbl) END
                          FROM problems GROUP BY complaint_id''').fetchall()
                        live = pd.DataFrame(rows, columns=['complaint_id','received_date','bbl'])
                        live = live.dropna(subset=['bbl'])
                        live['bbl'] = pd.to_numeric(live.bbl, errors='raise').astype('int64')
                        live['day'] = pd.to_datetime(live.received_date).dt.normalize()
                        live = live[pd.to_datetime(live.received_date) < pd.Timestamp(now.replace(tzinfo=None))]
                        live = live[live.bbl.isin(ids) & live.day.ge(pd.Timestamp(begin)) & live.day.le(pd.Timestamp(live_cutoff))]
                        cutoff = max(cutoff, live_cutoff)
                else:
                    metadata['collector_note'] = 'Live source unavailable, stale, or errored; using the dated historical extract.'
        frame = frame[frame.day.le(pd.Timestamp(cutoff))]
        if live is not None:
            frame = frame[frame.day.lt(pd.Timestamp(begin))]
            counts = live.groupby(['bbl','day']).complaint_id.nunique().rename('n').reset_index()
            frame = pd.concat([frame,counts],ignore_index=True)
        metadata.update(data_through=str(cutoff),history_start=str(first),
                        gap_days=(today-cutoff).days,buildings_in_universe=len(ids),
                        freshness='recent_published_data' if (today-cutoff).days <= 3 else 'dated_extract')
        return frame, ids, metadata

    def analyze(self, operation='trend', start=None, end=None, borough=None, bbl=None, days=3, k=10):
        frame, ids, meta = self.view(forecast_only=operation=='forecast')
        now = self.now().astimezone(NY).date()
        cutoff = date.fromisoformat(meta['data_through'])
        first = date.fromisoformat(meta['history_start'])
        start = date.fromisoformat(start) if start else now-timedelta(days=30)
        end = date.fromisoformat(end) if end else now
        if not first <= start <= end or end > now or (end-start).days > 3660:
            raise ValueError('Date range must be ordered, within history, and no later than today (maximum ten years)')
        if borough:
            code = BOROUGHS.get(str(borough).lower())
            if not code: raise ValueError('Unknown NYC borough')
            frame = frame[frame.bbl // 10**9 == code]
        if bbl:
            if not str(bbl).isdigit() or len(str(bbl)) != 10 or int(bbl) not in ids:
                raise ValueError('BBL is outside the historical building universe')
            if borough and int(bbl)//10**9 != code: raise ValueError('BBL does not match borough')
            frame = frame[frame.bbl == int(bbl)]
        scope = str(bbl) if bbl else (borough or 'historical NYC building universe')
        meta.update(scope_filter=scope, requested_start=str(start), requested_end=str(end),
                    excluded_unpublished_days=max(0,(end-cutoff).days))
        observed_end = min(end,cutoff)
        selected = frame[frame.day.between(pd.Timestamp(start),pd.Timestamp(observed_end))]
        dates = pd.date_range(max(first,start),observed_end,freq='D')
        daily = selected.groupby('day').n.sum().reindex(dates,fill_value=0)
        sources = [{'id':'data-1','title':'HPD published heat complaints; local historical building extract', 'url':SOURCE}]
        result = {'operation':operation,'metadata':meta,'sources':sources,'charts':[]}
        if operation == 'catalog':
            result['summary'] = {'available':['daily trends','borough totals','top buildings','period comparisons','building complaint history','experimental count forecast'],
                                 'unavailable':['current calibrated building risk','private accounts','resident details','arbitrary server files'],
                                 'history_rows':len(frame)}
            return result
        if operation == 'forecast':
            if type(days) is not int or not 1 <= days <= 7: raise ValueError('Forecast days must be 1..7')
            if meta['gap_days'] > 7: raise ValueError('History is too stale to issue a current forecast')
            all_dates = pd.date_range(first,cutoff,freq='D')
            y = frame.groupby('day').n.sum().reindex(all_dates,fill_value=0)
            targets = [now+timedelta(days=i) for i in range(1,days+1)]
            f = forecast([d.date() for d in all_dates], y.to_numpy(), targets)
            if bbl or (y.tail(90).sum() < 100):
                raise ValueError('Count forecasting is supported for citywide or borough aggregates with sufficient volume, not individual buildings')
            result['forecast'] = f
            result['table'] = f['rows']
            points = [{'label':str(d.date()),'value':int(v)} for d,v in y.tail(28).items()]
            result['charts'] = [{'type':'forecast','title':f'Experimental daily complaint forecast: {scope}',
                                 'points':points+[{'label':r['day'],'value':r['expected'],'lower':r['lower'],'upper':r['upper'],'forecast':True} for r in f['rows']]}]
        elif operation == 'boroughs':
            counts = selected.assign(borough=selected.bbl//10**9).groupby('borough').n.sum()
            result['table'] = [{'borough':NAMES[i],'complaints':int(counts.get(i,0))} for i in range(1,6) if not borough or i == code]
            result['charts'] = [{'type':'bar','title':'Published heat complaints by borough','points':[{'label':r['borough'],'value':r['complaints']} for r in result['table']]}]
        elif operation == 'top_buildings':
            if type(k) is not int or not 1 <= k <= 25: raise ValueError('k must be 1..25')
            ranked = selected.groupby('bbl').n.sum().sort_values(ascending=False).head(k)
            result['table'] = [{'bbl':str(b),'complaints':int(n)} for b,n in ranked.items()]
            result['charts'] = [{'type':'bar','title':'Buildings by observed complaint count; not predicted risk','points':[{'label':r['bbl'],'value':r['complaints']} for r in result['table']]}]
        elif operation in ('trend','compare'):
            if operation == 'compare':
                length = (observed_end-start).days+1
                pstart, pend = start-timedelta(days=length), start-timedelta(days=1)
                if length < 1 or pstart < first: raise ValueError('Insufficient coverage for equal-length comparison')
                previous = frame[frame.day.between(pd.Timestamp(pstart),pd.Timestamp(pend))].n.sum()
                total = int(daily.sum())
                result['comparison'] = {'current_start':str(start),'current_end':str(observed_end),'previous_start':str(pstart),'previous_end':str(pend),'current':total,'previous':int(previous), 'change_percent':round((total/previous-1)*100,1) if previous else None}
            result['table'] = [{'day':str(d.date()),'complaints':int(v)} for d,v in daily.items()]
            # Aggregate long charts to calendar months while retaining exact table totals.
            plotted = daily if len(daily) <= 120 else daily.resample('MS').sum()
            result['charts'] = [{'type':'line','title':f'Published complaint counts: {scope}','points':[{'label':str(d.date()),'value':int(v)} for d,v in plotted.items()]}]
        else:
            raise ValueError('Unsupported analysis operation')
        result['total_observed'] = int(selected.n.sum())
        return result
