"""Durable async jobs on loopback 5002. No long-running work on Vercel."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from flask import Flask, jsonify, request

from .data import DataStore
from .engine import Engine, ProviderError, validate_question

ROOT = Path(__file__).resolve().parents[1]


def signature(secret, timestamp, nonce, method, endpoint, body):
    data = '\n'.join([timestamp,nonce,method,endpoint,hashlib.sha256(body).hexdigest()])
    return hmac.new(secret.encode(),data.encode(),hashlib.sha256).hexdigest()


class Jobs:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,created REAL,status TEXT,question TEXT,result TEXT);
                CREATE TABLE IF NOT EXISTS budget(kind TEXT,stamp TEXT,n INTEGER,PRIMARY KEY(kind,stamp));
                CREATE TABLE IF NOT EXISTS search_cache(key TEXT PRIMARY KEY,created REAL,result TEXT);
                CREATE TABLE IF NOT EXISTS nonces(nonce TEXT PRIMARY KEY,created REAL);''')
            db.execute("UPDATE jobs SET status='failed',question=NULL,result=? WHERE status IN ('queued','running')",
                       (json.dumps({'error':'Service restarted; submit the question again'}),))
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='research')
        self.slot = threading.BoundedSemaphore(3)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def consume(self, kind):
        now = datetime.now(timezone.utc)
        limits = {'job':(3,100),'model':(12,400),'search':(6,100)}
        minute, daily = limits[kind]
        stamps = [(now.strftime('%Y-%m-%dT%H:%M'),minute), (now.strftime('%Y-%m-%d'),daily)]
        if kind=='search': stamps.append((now.strftime('%Y-%m'),900))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for stamp,limit in stamps:
                row = db.execute('SELECT n FROM budget WHERE kind=? AND stamp=?',(kind,stamp)).fetchone()
                if row and row[0] >= limit: raise ProviderError('Shared free-tier request budget reached; try later')
            for stamp,_ in stamps:
                db.execute('INSERT INTO budget VALUES(?,?,1) ON CONFLICT(kind,stamp) DO UPDATE SET n=n+1',(kind,stamp))
            db.execute('DELETE FROM budget WHERE stamp<?',(now.strftime('%Y-%m'),))

    def cached_search(self, search):
        def run(query):
            key=hashlib.sha256(query.strip().lower().encode()).hexdigest()
            with self.db() as db:
                row=db.execute('SELECT result FROM search_cache WHERE key=? AND created>?',(key,time.time()-3600)).fetchone()
            if row:return json.loads(row['result'])
            result=search(query)
            with self.db() as db:
                db.execute('DELETE FROM search_cache WHERE created<?',(time.time()-3600,))
                db.execute('INSERT OR REPLACE INTO search_cache VALUES(?,?,?)',(key,time.time(),json.dumps(result)))
            return result
        return run

    def submit(self, question, engine):
        if not self.slot.acquire(blocking=False): raise ProviderError('Assistant is busy; try again shortly')
        try:
            self.consume('job')
            job = secrets.token_hex(24)
            with self.db() as db:
                db.execute('DELETE FROM jobs WHERE created<?',(time.time()-3600,))
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,NULL)',(job,time.time(),'queued',question))
            self.pool.submit(self.work,job,question,engine)
            return job
        except Exception:
            self.slot.release()
            raise

    def work(self, job, question, engine):
        try:
            with self.db() as db: db.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
            result, status = engine.answer(question),'completed'
        except ProviderError as exc:
            result,status = {'error':str(exc)},'failed'
        except Exception as exc:
            # Never log the question, response, provider body, or credentials.
            logging.getLogger('assistant').warning('Job failed: %s',type(exc).__name__)
            result,status = {'error':'Analysis unavailable; check source coverage or retry a simpler question'},'failed'
        finally:
            self.slot.release()
        with self.db() as db:
            db.execute('UPDATE jobs SET status=?,question=NULL,result=? WHERE id=?',
                       (status,json.dumps(result,allow_nan=False),job))

    def read(self, job):
        with self.db() as db:
            row = db.execute('SELECT status,result FROM jobs WHERE id=? AND created>?',(job,time.time()-3600)).fetchone()
        return {'id':job,'status':row['status'],'result':json.loads(row['result']) if row['result'] else None} if row else None


def create_app(root=ROOT, engine=None, jobs=None):
    root = Path(root)
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 4096
    jobs = jobs or Jobs(root/'data/assistant/jobs.sqlite3')
    if engine is None:
        engine = Engine(DataStore(root),jobs.consume)
        engine.search = jobs.cached_search(engine.search_call)

    @app.before_request
    def authenticate():
        secret = os.environ.get('ASSISTANT_PROXY_SECRET','')
        if len(secret)<32: return jsonify(error='Assistant signing secret is not configured'),503
        timestamp, nonce = request.headers.get('X-HA-Time',''),request.headers.get('X-HA-Nonce','')
        endpoint = request.path.lstrip('/')
        try:
            if abs(time.time()-float(timestamp))>60 or len(nonce)!=32: raise ValueError()
            expected = signature(secret,timestamp,nonce,request.method,endpoint,request.get_data())
            if not hmac.compare_digest(expected,request.headers.get('X-HA-Signature','')): raise ValueError()
            with jobs.db() as db:
                db.execute('DELETE FROM nonces WHERE created<?',(time.time()-120,))
                db.execute('INSERT INTO nonces VALUES(?,?)',(nonce,time.time()))
        except (ValueError,sqlite3.IntegrityError):
            return jsonify(error='Invalid assistant proxy signature'),403

    @app.get('/health')
    def health():
        return jsonify(status='ok',model_configured=bool(os.environ.get('LLM_API_KEY')),
                       search_configured=bool(os.environ.get('TAVILY_API_KEY')),
                       mode='public_data_research',accelerator_used=False)

    @app.post('/jobs')
    def submit():
        data = request.get_json(silent=True)
        try:
            if not isinstance(data,dict) or set(data)!={'question'}: raise ValueError('Send a JSON object containing question')
            q = validate_question(data['question'])
            job = jobs.submit(q,engine)
            return jsonify(id=job,status='queued'),202
        except ValueError as exc: return jsonify(error=str(exc)),400
        except ProviderError as exc: return jsonify(error=str(exc)),429

    @app.get('/jobs/<job>')
    def read(job):
        if len(job)!=48 or any(c not in '0123456789abcdef' for c in job): return jsonify(error='Unknown job'),404
        result = jobs.read(job)
        return (jsonify(result),200) if result else (jsonify(error='Job expired or unknown'),404)

    @app.after_request
    def private(response):
        response.headers['Cache-Control']='private, no-store'
        response.headers['Referrer-Policy']='no-referrer'
        nonce = request.headers.get('X-HA-Nonce','')
        secret = os.environ.get('ASSISTANT_PROXY_SECRET','')
        if len(secret)>=32:
            response.headers['X-HA-Response'] = hmac.new(secret.encode(),nonce.encode()+b'\n'+response.get_data(),hashlib.sha256).hexdigest()
        return response
    return app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--port',type=int,default=5002)
    args=parser.parse_args()
    from waitress import serve
    serve(create_app(args.root),host='127.0.0.1',port=args.port,threads=4)


if __name__=='__main__': main()
