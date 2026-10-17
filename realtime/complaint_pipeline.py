"""Durable, building-level NYC HPD complaint ingestion; no synthetic production inputs.

Run `poll` from a systemd timer and `serve` behind the web app's same-origin proxy.
The February replay and this database deliberately have separate state and routes.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://data.cityofnewyork.us/resource/ygpa-z7cr.json'
NY = ZoneInfo('America/New_York')
HEAT = ('NO HEAT', 'NO HEAT AND NO HOT WATER')
BOROUGHS = {'MANHATTAN': 1, 'BRONX': 2, 'BROOKLYN': 3, 'QUEENS': 4, 'STATEN ISLAND': 5}
FIELDS = 'received_date,problem_id,complaint_id,building_id,borough,block,lot,problem_code'


def utcnow():
    return datetime.now(timezone.utc)


def local_stamp(value):
    """Source timestamps are NYC floating timestamps, not UTC."""
    d = datetime.fromisoformat(value)
    if d.tzinfo is not None:
        d = d.astimezone(NY).replace(tzinfo=None)
    return d.isoformat(timespec='milliseconds')


def numeric(value):
    value = str(value or '')
    if not re.fullmatch(r'[0-9]{1,18}', value):
        raise ValueError('Source identifier is not an unsigned integer')
    return int(value)


def normalize(row):
    if row.get('problem_code') not in HEAT:
        raise ValueError('Unexpected complaint type in heat-only response')
    problem, complaint = numeric(row.get('problem_id')), numeric(row.get('complaint_id'))
    received = local_stamp(row['received_date'])
    bbl = None
    try:
        borough = BOROUGHS[row['borough'].upper()]
        block, lot = numeric(row.get('block')), numeric(row.get('lot'))
        if 0 < block <= 99999 and 0 < lot <= 9999:
            bbl = str(borough * 10**9 + block * 10000 + lot)
    except (KeyError, ValueError):
        pass
    building = numeric(row['building_id']) if row.get('building_id') else None
    return problem, complaint, received, building, bbl, row['problem_code']


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS problems (
          problem_id INTEGER PRIMARY KEY, complaint_id INTEGER NOT NULL,
          received_date TEXT NOT NULL, building_id INTEGER, bbl TEXT, problem_code TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS problems_date ON problems(received_date);
        CREATE INDEX IF NOT EXISTS problems_complaint ON problems(complaint_id);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    return db


def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))


def get(db, key, default=None):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def fetch_json(params):
    headers = {'User-Agent': 'HeatAhead-complaints/1.0', 'Accept': 'application/json'}
    if os.environ.get('SOCRATA_APP_TOKEN'):
        headers['X-App-Token'] = os.environ['SOCRATA_APP_TOKEN']
    req = Request(SOURCE + '?' + urlencode(params), headers=headers)
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError('Source response exceeds size limit')
            result = json.loads(raw)
            if not isinstance(result, list):
                raise ValueError('Source did not return a JSON array')
            return result
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            # Capped retry; no tokens or response bodies written to logs.
            time.sleep(min(10, 2 ** attempt))
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def poll(path, *, fetch=fetch_json, now=None, lookback=None, page_size=5000, max_pages=100):
    """Commit an entire bounded poll atomically. Failed pages never advance coverage.

    Re-read seven days each poll and ninety days in the daily reconciliation job.
    Received-time cursors alone miss complaints published late.
    """
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.poll.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already_running'}
        db = connect(path)
        now = now or utcnow()
        try:
            prior = get(db, 'last_success')
            days = lookback if lookback is not None else (7 if prior else 35)
            if not 1 <= days <= 366:
                raise ValueError('lookback must be 1..366 days')
            end = now.astimezone(NY).replace(tzinfo=None)
            begin = end - timedelta(days=days)
            if prior and lookback is None:
                # Catch up after downtime, rather than silently skipping a gap.
                begin = min(begin, datetime.fromisoformat(prior).astimezone(NY).replace(tzinfo=None)-timedelta(days=7))
            start, stop = local_stamp(begin.isoformat()), local_stamp(end.isoformat())
            metadata = fetch({'$select': 'max(received_date) AS newest', '$limit': 1})
            newest = metadata[0].get('newest') if metadata else None
            if newest:
                newest = local_stamp(newest)
            base = (f"received_date >= '{start}' AND received_date < '{stop}' AND "
                    "problem_code in ('NO HEAT','NO HEAT AND NO HOT WATER')")
            staged, cursor = [], None
            # Keyset pagination, stable numeric problem_id tie-breaker.
            for page in range(max_pages):
                where = base
                if cursor:
                    d, p = cursor
                    where += f" AND (received_date > '{d}' OR (received_date = '{d}' AND problem_id > {p}))"
                rows = fetch({'$select': FIELDS, '$where': where,
                              '$order': 'received_date ASC,problem_id ASC', '$limit': page_size})
                if not rows:
                    break
                for row in rows:
                    record = normalize(row)
                    key = (record[2], record[0])
                    if not start <= record[2] < stop or (cursor and key <= cursor):
                        raise ValueError('Unordered or out-of-window source response')
                    staged.append(record)
                    cursor = key
                if len(rows) < page_size:
                    break
            else:
                raise ValueError('Page limit reached; refusing to claim complete coverage')
            old = db.execute('SELECT COUNT(*) FROM problems').fetchone()[0]
            with db:
                # A completed window is authoritative, including removals and
                # heat problems reclassified by the publisher. Never do this
                # until every page has been validated successfully.
                db.execute('DELETE FROM problems WHERE received_date>=? AND received_date<?', (start, stop))
                db.executemany('''INSERT INTO problems VALUES (?,?,?,?,?,?)
                    ON CONFLICT(problem_id) DO UPDATE SET complaint_id=excluded.complaint_id,
                    received_date=excluded.received_date,building_id=excluded.building_id,
                    bbl=excluded.bbl,problem_code=excluded.problem_code''', staged)
                put(db, 'last_success', now.isoformat())
                put(db, 'source_latest_received', newest)
                put(db, 'last_window', {'start': start, 'end': stop, 'days': days})
                covered = get(db, 'coverage_start')
                put(db, 'coverage_start', min(start, covered) if covered else start)
                put(db, 'last_error', None)
                count = db.execute('SELECT COUNT(*) FROM problems').fetchone()[0]
                result = {'status': 'ok', 'rows_fetched': len(staged),
                          'net_problem_change': count-old, 'source_latest_received': newest,
                          'last_success': now.isoformat()}
                put(db, 'last_poll', result)
            return result
        except Exception as error:
            with db:
                put(db, 'last_error', {'at': now.isoformat(), 'type': type(error).__name__})
            raise
        finally:
            db.close()


def snapshot(path, *, now=None, k=25):
    now = now or utcnow()
    end = now.astimezone(NY).replace(tzinfo=None)
    start = local_stamp((now-timedelta(hours=24)).astimezone(NY).replace(tzinfo=None).isoformat())
    week = local_stamp((now-timedelta(days=7)).astimezone(NY).replace(tzinfo=None).isoformat())
    stop = local_stamp(end.isoformat())
    db = connect(path)
    try:
        # Multiple problem rows still count as one complaint. Ambiguous BBLs are
        # excluded from the per-building table and counted as unlocated instead.
        sql = '''WITH complaints AS (
          SELECT complaint_id, MIN(received_date) AS received_date,
            CASE WHEN COUNT(DISTINCT bbl)=1 THEN MAX(bbl) END AS bbl,
            GROUP_CONCAT(DISTINCT problem_code) AS reported_problem
          FROM problems GROUP BY complaint_id)
        '''
        total = db.execute(sql + 'SELECT COUNT(*) FROM complaints WHERE received_date>=? AND received_date<?', (start,stop)).fetchone()[0]
        total_week = db.execute(sql + 'SELECT COUNT(*) FROM complaints WHERE received_date>=? AND received_date<?', (week,stop)).fetchone()[0]
        missing = db.execute(sql + 'SELECT COUNT(*) FROM complaints WHERE received_date>=? AND received_date<? AND bbl IS NULL', (week,stop)).fetchone()[0]
        latest_heat = db.execute('SELECT MAX(received_date) FROM problems WHERE received_date<?',(stop,)).fetchone()[0]
        rows = db.execute(sql + '''SELECT bbl,COUNT(*) AS complaints_7d,
          MAX(received_date) AS latest_received FROM complaints
          WHERE received_date>=? AND received_date<? AND bbl IS NOT NULL GROUP BY bbl
          ORDER BY complaints_7d DESC,latest_received DESC,bbl LIMIT ?''', (week,stop,k)).fetchall()
        events = db.execute(sql + '''SELECT complaint_id,bbl,received_date,reported_problem
          FROM complaints WHERE received_date>=? AND received_date<?
          ORDER BY received_date DESC,complaint_id DESC LIMIT 100''',(week,stop)).fetchall()
        last = get(db, 'last_success')
        latest = get(db, 'source_latest_received')
        source_lag = max(0, (now-datetime.fromisoformat(latest).replace(tzinfo=NY)).total_seconds()/3600) if latest else None
        poll_age = (now-datetime.fromisoformat(last)).total_seconds() if last else None
        error = get(db, 'last_error')
        status = 'waiting' if not last else ('poll_error' if error else ('stale' if poll_age > 900 else 'ok'))
        return {'stats': {'mode': 'published_hpd_complaints', 'status': status,
            'now': now.astimezone(NY).isoformat(), 'timezone': 'America/New_York',
            'source': SOURCE, 'last_successful_poll': last,
            'source_latest_received': latest, 'source_lag_hours': source_lag,
            'latest_heat_received': latest_heat,
            'poll_age_seconds': poll_age, 'last_error': error,
            'coverage_start': get(db, 'coverage_start'), 'last_window': get(db, 'last_window'),
            'complaints_24h': total, 'complaints_7d': total_week,
            'unlocated_complaints_7d': missing,
            'risk_scoring': 'unavailable_current_features_not_refreshed',
            'ordering': 'observed complaint count in last 7 days; not predicted risk',
            'publication_note': 'Polling sees published records, not the time a resident submits to 311.'},
            'buildings': [dict(row) for row in rows], 'events':[dict(row) for row in events]}
    finally:
        db.close()


def create_app(path):
    from flask import Flask, jsonify, request
    app = Flask(__name__)

    @app.get('/stats')
    def stats():
        return jsonify(snapshot(path)['stats'])

    @app.get('/queue')
    def queue():
        try:
            k = int(request.args.get('k', 25))
            if not 1 <= k <= 100:
                raise ValueError()
        except ValueError:
            return jsonify(error='k must be an integer from 1 to 100'), 400
        data = snapshot(path, k=k)
        return jsonify(buildings=data['buildings'], ordering=data['stats']['ordering'])

    @app.get('/events')
    def events():
        return jsonify(events=snapshot(path)['events'],window_days=7)

    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['poll', 'serve', 'check'])
    parser.add_argument('--db', type=Path, default=ROOT/'data/live_complaints.sqlite3')
    parser.add_argument('--lookback-days', type=int)
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    if args.command == 'poll':
        print(json.dumps(poll(args.db, lookback=args.lookback_days)))
    elif args.command == 'check':
        with urlopen(f'http://127.0.0.1:{args.port}/stats', timeout=10) as response:
            result = json.load(response)
        if result.get('mode') != 'published_hpd_complaints' or result.get('status') != 'ok':
            raise SystemExit('Collector is unhealthy: ' + str(result.get('status')))
        print(json.dumps({'status':'ok','last_successful_poll':result['last_successful_poll'],
                          'source_latest_received':result['source_latest_received']}))
    else:
        from waitress import serve
        serve(create_app(args.db), host='127.0.0.1', port=args.port, threads=4)


if __name__ == '__main__':
    main()
