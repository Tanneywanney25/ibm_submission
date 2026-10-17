"""Phase 6 (LinuxONE only): import the XGBoost model into Snap ML and measure throughput.

Prereqs on the instance:  pip install --only-binary=:all: snapml
Run from the repo root:   python model/04_snapml_bench.py
Record alongside: `uname -m` (s390x) and `grep -o nnpa /proc/cpuinfo` screenshots.
"""

import time
import numpy as np
import pandas as pd
from common import FEATS, OUT

panel = pd.read_csv(OUT / "panel.csv")
X = panel[FEATS].to_numpy(dtype=np.float32)[:172_485]   # one full-universe batch
print(f"benchmark matrix: {X.shape}")


def bench(name, predict):
    predict(X[:1000])                                   # warm up
    t0 = time.perf_counter()
    predict(X)
    batch = time.perf_counter() - t0
    lat = []
    for i in range(10_000):
        t0 = time.perf_counter()
        predict(X[i % len(X):i % len(X) + 1])
        lat.append(time.perf_counter() - t0)
    p99 = np.percentile(lat, 99) * 1000
    print(f"{name}: {len(X)/batch:,.0f} buildings/sec batch | p99 single-row {p99:.2f} ms")


from xgboost import XGBClassifier
xgb = XGBClassifier()
xgb.load_model(OUT / "heat_model.json")
bench("xgboost", lambda a: xgb.predict_proba(a))

try:
    # tree_format="auto" logs whether the on-chip accelerator (nnpa/zdnn) was detected
    from snapml import BoostingMachineClassifier
    snap = BoostingMachineClassifier()
    snap.import_model(str(OUT / "heat_model.json"), input_type="xgb_json",
                      tree_format="auto")
    snap.set_params(verbose=True)
    bench("snapml", lambda a: snap.predict_proba(a))
except Exception as e:                                   # measured numbers still count
    print(f"snapml unavailable ({e}) - report the plain XGBoost numbers and say so")
