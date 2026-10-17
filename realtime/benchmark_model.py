"""Measure actual batch inference on this host, never a claimed accelerator run."""
import hashlib
import json
from pathlib import Path
import platform
import time

import pandas as pd
from replay_model import ModelReplay

root=Path(__file__).resolve().parents[1]
events=pd.read_csv(root/'data/replay_feb7_9.csv',usecols=['received_date'],parse_dates=['received_date'])
m=ModelReplay(root/'data',root/'model/out',events.received_date.min())
runs=[]
for repeat in range(3):
    t=time.perf_counter()
    m.predict()
    seconds=time.perf_counter()-t
    runs.append(dict(seconds=seconds,buildings_per_second=len(m.ids)/seconds))
cpuinfo=Path('/proc/cpuinfo').read_text() if Path('/proc/cpuinfo').exists() else ''
report=dict(architecture=platform.machine(),backend='xgboost_native_cpu',
            xgboost_version=m.xgb.__version__,model_features=len(m.features),
            buildings=len(m.ids),nnpa_flag_exposed='nnpa' in cpuinfo.split(),
            accelerator_used=False,includes='DMatrix creation, inference and isotonic calibration',
            model_sha256=hashlib.sha256((root/'model/out/heat_model_final.json').read_bytes()).hexdigest(),
            batch_runs=runs)
p=root/'data/realtime_model_benchmark.json'
p.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
print(f'Saved {p}')
