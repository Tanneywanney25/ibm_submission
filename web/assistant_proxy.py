"""Lightweight same-origin job proxy, including on Vercel; no model keys here."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import requests
from flask import Response, jsonify, request


def digest(secret, stamp, nonce, method, endpoint, body):
    data='\n'.join([stamp,nonce,method,endpoint,hashlib.sha256(body).hexdigest()])
    return hmac.new(secret.encode(),data.encode(),hashlib.sha256).hexdigest()


def init_app(app):
    @app.route('/api/assistant/<path:endpoint>',methods=['GET','POST'])
    def assistant_api(endpoint):
        if not ((endpoint=='jobs' and request.method=='POST') or
                (request.method=='GET' and (endpoint=='health' or re.fullmatch(r'jobs/[0-9a-f]{48}',endpoint)))):
            return jsonify(error='Unknown assistant endpoint'),404
        if request.content_length and request.content_length>4096:
            return jsonify(error='Question is too large'),413
        secret=os.environ.get('ASSISTANT_PROXY_SECRET','')
        if len(secret)<32: return jsonify(error='Assistant connection is being configured',offline=True),503
        body=request.get_data()
        if len(body)>4096: return jsonify(error='Question is too large'),413
        stamp,nonce=request.headers.get('X-HA-Time',''),request.headers.get('X-HA-Nonce','')
        incoming=False
        try:
            incoming=(abs(time.time()-float(stamp))<=60 and len(nonce)==32 and
                      hmac.compare_digest(digest(secret,stamp,nonce,request.method,endpoint,body),request.headers.get('X-HA-Signature','')))
        except ValueError: pass
        if request.method=='POST' and not incoming:
            try:
                origin=urlsplit(request.headers.get('Origin',''))
                if origin.scheme not in ('http','https') or origin.netloc!=request.host or origin.path not in ('','/'):
                    return jsonify(error='Use the assistant form on this website'),403
            except ValueError: return jsonify(error='Invalid origin'),403
        if not incoming:
            stamp,nonce=str(time.time()),secrets.token_hex(16)
        headers={'Content-Type':'application/json','X-HA-Time':stamp,'X-HA-Nonce':nonce,
                 'X-HA-Signature':digest(secret,stamp,nonce,request.method,endpoint,body)}
        base=os.environ.get('ASSISTANT_URL','http://127.0.0.1:5002').rstrip('/')
        try:
            r=requests.request(request.method,base+'/'+endpoint,data=body,headers=headers,timeout=(2,4),allow_redirects=False)
            if len(r.content)>1_500_000: raise ValueError()
            expected=hmac.new(secret.encode(),nonce.encode()+b'\n'+r.content,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,r.headers.get('X-HA-Response','')): raise ValueError()
            if not isinstance(r.json(),dict): raise ValueError()
            response=Response(r.content,status=r.status_code,content_type='application/json')
            response.headers['Cache-Control']='private, no-store'
            if incoming: response.headers['X-HA-Response']=expected
            return response
        except (requests.RequestException,ValueError):
            return jsonify(error='Research service unreachable; the complaint monitor remains available',offline=True),503
