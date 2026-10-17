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


def bench(name, predict, A):
    predict(A[:1000])                                   # warm up
    t0 = time.perf_counter()
    predict(A)
    batch = time.perf_counter() - t0
    lat = []
    for i in range(10_000):
        t0 = time.perf_counter()
        predict(A[i % len(A):i % len(A) + 1])
        lat.append(time.perf_counter() - t0)
    p99 = np.percentile(lat, 99) * 1000
    print(f"{name}: {len(A)/batch:,.0f} buildings/sec batch | p99 single-row {p99:.2f} ms")


from xgboost import XGBClassifier
xgb = XGBClassifier()
xgb.load_model(OUT / "heat_model.json")
bench("xgboost", lambda a: xgb.predict_proba(a), X)

try:
    from snapml import BoostingMachineClassifier
    snap = BoostingMachineClassifier()
    try:
        # tree_format="auto" logs whether the on-chip accelerator (nnpa/zdnn) was detected
        snap.import_model(str(OUT / "heat_model.json"), input_type="xgb_json",
                          tree_format="auto")
        print("snapml: imported the XGBoost model")
    except Exception as e:
        # XGBoost 3.x JSON sometimes won't import - train Snap ML natively instead
        print(f"snapml import failed ({e}); training natively on the panel")
        y = panel["failed48"].to_numpy()[:len(X) * 4]
        Xt = np.nan_to_num(panel[FEATS].to_numpy(dtype=np.float32)[:len(y)], nan=-1.0)
        snap = BoostingMachineClassifier(num_round=200, max_depth=6, n_jobs=3)
        snap.fit(Xt, y)
    snap.set_params(verbose=True)                        # logs zDNN/NNPA use on predict
    Xs = np.nan_to_num(X, nan=-1.0)                      # snapml cannot take NaNs
    bench("snapml", lambda a: snap.predict_proba(a), Xs)
except Exception as e:                                   # measured numbers still count
    print(f"snapml unavailable ({e}) - report the plain XGBoost numbers and say so")
