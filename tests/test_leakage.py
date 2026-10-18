"""T11c - the leakage test suite: every time-discipline rule as a test.

Run from the repo root:  python -m pytest tests/ -q
Needs model/out/panel.csv + building_day_counts(.bw).csv + data/ files;
tests skip (not fail) when inputs are absent so the suite runs anywhere.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model/out"
RNG = np.random.default_rng(7)


def season(d):
    return d.dt.year - (d.dt.month < 10).astype(int)


def need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"inputs absent: {missing}")


@pytest.fixture(scope="module")
def panel():
    need(OUT / "panel.csv")
    return pd.read_csv(OUT / "panel.csv", parse_dates=["day"])


@pytest.fixture(scope="module")
def bd():
    need(OUT / "building_day_counts.csv")
    df = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
    df["season"] = season(df.day)
    return df


def test_banned_columns_never_features():
    """currentstatus / problem_status_date must not appear in FEATS or any loader."""
    import sys
    sys.path.insert(0, str(ROOT / "model"))
    from common import FEATS
    banned = {"currentstatus", "problem_status_date", "novissueddate",
              "obs_mean_48h", "obs_min_48h", "n_48h", "v_7d_after"}
    assert not banned & set(FEATS)
    for py in (ROOT / "model").glob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            code = line.split("#")[0]
            assert "currentstatus" not in code and "problem_status_date" not in code, \
                f"{py.name}: banned column referenced outside a comment: {line.strip()}"


def test_history_strictly_prior_season(panel, bd):
    """c_last1 on 2025-26 rows equals the recomputed full 2024-25 count."""
    s24 = bd[bd.season == 2024].groupby("bbl")["n"].sum()
    rows = panel[panel.season == 2025].sample(500, random_state=0)
    expect = rows.bbl.map(s24).fillna(0).to_numpy()
    assert np.array_equal(rows.c_last1.to_numpy(), expect)


def test_trailing_windows_end_day_minus_one(panel, bd):
    """c_prev14 must cover [d-14, d-1] - never the row's own day."""
    rows = panel.sample(300, random_state=1)
    merged = rows[["bbl", "day", "c_prev14"]].reset_index(drop=True)
    got = []
    for r in merged.itertuples():
        w = bd[(bd.bbl == r.bbl) & (bd.day >= r.day - pd.Timedelta(days=14))
               & (bd.day <= r.day - pd.Timedelta(days=1))]["n"].sum()
        got.append(w)
    assert np.array_equal(merged.c_prev14.to_numpy(), np.array(got, dtype=float))


def test_own_day_complaints_not_in_features(panel, bd):
    """A row's same-day complaints must not leak into any trailing count."""
    hot = bd[bd.n >= 5].merge(panel[["bbl", "day", "c_prev2"]], on=["bbl", "day"])
    if len(hot) == 0:
        pytest.skip("no overlapping hot rows in panel sample")
    hot = hot.sample(min(200, len(hot)), random_state=2)
    for r in hot.itertuples():
        prior = bd[(bd.bbl == r.bbl) & (bd.day >= r.day - pd.Timedelta(days=2))
                   & (bd.day <= r.day - pd.Timedelta(days=1))]["n"].sum()
        assert r.c_prev2 == prior, \
            f"bbl {r.bbl} {r.day.date()}: c_prev2={r.c_prev2} includes same-day n"


def test_days_since_positive(panel):
    """days_since_* are >= 1 (as of the eve) or the NEVER sentinel - never 0."""
    assert (panel.days_since_c >= 1).all()
    assert (panel.days_since_v >= 1).all()


def test_universe_rule(panel):
    """Every panel row has some history (the team's inspectable-universe cut)."""
    import sys
    sys.path.insert(0, str(ROOT / "model"))
    from common import NEVER
    assert ((panel.days_since_c < NEVER) | (panel.days_since_v < NEVER)).all()


def test_ranked_list_universe():
    """Every scored building in the shipped list exists in the history files."""
    need(OUT / "ranked_inspection_list.csv", OUT / "building_day_counts.csv",
         ROOT / "data/hpd_heat_violations.csv")
    ranked = pd.read_csv(OUT / "ranked_inspection_list.csv", usecols=["bbl"])
    bdb = set(pd.read_csv(OUT / "building_day_counts.csv", usecols=["bbl"]).bbl)
    vb = set(pd.read_csv(ROOT / "data/hpd_heat_violations.csv",
                         usecols=["bbl"], low_memory=False).dropna().bbl.astype("int64"))
    outside = set(ranked.bbl) - bdb - vb
    assert not outside, f"{len(outside)} scored buildings have no history anywhere"


def test_display_rules():
    """Shipped probabilities are capped at 99% and never negative."""
    need(OUT / "season_risk_2026.csv")
    sr = pd.read_csv(OUT / "season_risk_2026.csv")
    assert sr.p_season.max() <= 0.99 + 1e-9
    assert sr.p_season.min() >= 0


def test_narrative_features_use_only_prior_complaints():
    """M14 category features: prior-season aggregates see only season S-1, and
    in-season counts stop at the eve - the spell day and later never count."""
    import sys
    sys.path.insert(0, str(ROOT / "model"))
    from narrative import narrative_features, prep
    start = pd.Timestamp("2025-01-20")                       # season 2024
    rows = [  # (bbl, complaint_id, day, problem_code, unit_key)
        (1, 1, "2024-01-10", "NO HOT WATER", 11.0),          # S-1: counts
        (1, 2, "2024-02-01", "NO HEAT AND NO HOT WATER", 12.0),  # S-1: counts
        (1, 3, "2022-12-01", "NO HOT WATER", 13.0),          # S-3: never
        (1, 4, "2025-01-19", "NO HOT WATER", 14.0),          # eve: in-season
        (1, 5, "2025-01-20", "NO HOT WATER", 15.0),          # spell day: never
        (1, 6, "2025-02-05", "NO HEAT", 16.0),               # after: never
        (1, 7, "2024-12-01", "NO HEAT", 17.0),               # in-season heat
        (2, 8, "2025-01-20", "NO HEAT", 21.0),               # spell day only
    ]
    c = pd.DataFrame(rows, columns=["bbl", "complaint_id", "day", "problem_code",
                                    "unit_key"])
    c["day"] = pd.to_datetime(c.day)
    c["minor_category"] = "APARTMENT ONLY"
    c["problem_duplicate_flag"] = "N"
    c["complaint_anonymous_flag"] = "N"
    X = narrative_features(prep(c), [1, 2, 3], 2024, start)
    assert X.loc[1, "nhw_last1"] == 1                        # id 1 only
    assert X.loc[1, "hhw_share_last1"] == 1.0                # id 2 is the S-1 heat
    assert X.loc[1, "units_last1"] == 1
    assert X.loc[1, "nhw_season"] == 1                       # eve yes, spell day no
    assert X.loc[1, "units_season"] == 1                     # id 7; id 6 is after
    assert (X.loc[2] == 0).all() and (X.loc[3] == 0).all()   # spell-day only / none


def test_no_apartment_columns_shipped():
    """Nothing under public/ or model/out ships an apartment column."""
    pat = re.compile(r"(^|,)\s*apartment\s*(,|$)", re.I)
    for f in list((ROOT / "public/data").rglob("*.csv")) + list(OUT.glob("*.csv")):
        try:
            header = f.open(encoding="utf-8", errors="replace").readline()
        except OSError:
            continue
        assert not pat.search(header), f"{f} ships an apartment column"
