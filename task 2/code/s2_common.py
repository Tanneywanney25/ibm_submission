"""Shared helpers for HeatAhead Workstream 2 (analysis, second thread).

Everything runs on the IBM z17 LinuxONE guest (s390x) under ~/heatahead/stream2/.
Paths, team traps (int64 keys, heat-only filter, holiday gaps, season clock) and
the weather bands live here so every step applies the same rules.
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("STREAM2_ROOT", str(Path.home() / "heatahead" / "stream2")))
RAW, WORK, OUT, LOGS = ROOT / "raw", ROOT / "work", ROOT / "out", ROOT / "logs"
for _p in (WORK, OUT, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

# six Christmas-week logging-gap dates (Emerson's EDA) -- excluded everywhere
HOLIDAY_GAPS = pd.to_datetime(["2017-12-31", "2018-12-30", "2019-12-29",
                               "2020-12-27", "2020-12-28", "2021-12-26"])
HEAT_CODES = ("NO HEAT", "NO HEAT AND NO HOT WATER")
HEAT_ORDERS = (666, 966, 674)        # Admin Code 27-2029, heat
HOTWATER_ORDERS = (670, 970)         # Admin Code 27-2031, hot water
TRAIN_SEASONS = list(range(2018, 2025))   # 2018-19 .. 2024-25
TEST_SEASON = 2025                        # 2025-26 holdout
SNAP_DAYS = pd.to_datetime(["2026-02-07", "2026-02-08", "2026-02-09"])
FEATURE_CUTOFF = pd.Timestamp("2025-10-01")   # nothing after this feeds a training feature
BAND_ORDER = ["Frigid", "Freezing", "Cold", "Mild"]
SIZE_ORDER = ["1-2 units", "3-29 units", "30-99 units", "100+ units"]
ERA_ORDER = ["pre-1901", "1901-1939 pre-war", "1940-1969", "1970-1999", "2000+"]


def season(d):
    """Heat season named by its starting year: Dec 2022 and Feb 2023 -> 2022."""
    d = pd.to_datetime(d)
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)


def in_heat_season(d):
    d = pd.to_datetime(d)
    return (d.dt.month >= 10) | (d.dt.month <= 5)


def to_int64(s):
    """Strip decimal strings like 2043190010.00000000 and cast to nullable Int64."""
    return pd.to_numeric(s, errors="coerce").round().astype("Int64")


def tmin_band(t):
    t = pd.Series(t).astype(float)
    return pd.Categorical(
        np.select([t < 20, t < 32, t < 45], ["Frigid", "Freezing", "Cold"], "Mild"),
        categories=BAND_ORDER, ordered=True)


def size_bucket(u):
    u = pd.Series(u).astype(float)
    return pd.Categorical(
        np.select([u <= 2, u <= 29, u <= 99], SIZE_ORDER[:3], SIZE_ORDER[3]),
        categories=SIZE_ORDER, ordered=True)


def era_bucket(y):
    y = pd.Series(y).astype(float)
    out = np.select([y < 1901, y <= 1939, y <= 1969, y <= 1999], ERA_ORDER[:4], ERA_ORDER[4])
    out = np.where(y.isna() | (y <= 0), None, out)
    return pd.Categorical(out, categories=ERA_ORDER, ordered=True)


def load_days():
    """Observed Central Park daily weather with band, season and holiday flags."""
    d = pd.read_csv(WORK / "days_weather.csv", parse_dates=["day"])
    d["band"] = tmin_band(d.TMIN)
    return d


def save_numbers(step, d):
    p = OUT / f"numbers_{step}.json"
    p.write_text(json.dumps(d, indent=2, default=_json_default))
    print(f"  numbers -> {p}")


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, (np.ndarray, pd.Series)):
        return o.tolist()
    return str(o)


class Timer:
    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self.t0 = time.perf_counter()
        print(f"[{time.strftime('%H:%M:%S')}] {self.label} ...", flush=True)
        return self

    def __exit__(self, *a):
        self.secs = time.perf_counter() - self.t0
        print(f"[{time.strftime('%H:%M:%S')}] {self.label} done in {self.secs:,.1f} s", flush=True)
