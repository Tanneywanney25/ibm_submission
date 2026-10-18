"""T20 / M14 feature builder: complaint category + flag features, per-unit rates.

The HPD complaint extract carries no prose - only categorical fields
(minor_category, problem_code) and intake flags. These are aggregated to
building level, from complaints strictly before the ranking moment:
prior-season (S-1) aggregates, plus in-season counts through the eve (start-1).
The apartment column is reduced to a per-building count of distinct units at
load time and dropped; no unit value survives past load_complaints().
"""

import numpy as np
import pandas as pd

CAT_FEATS = ["nhw_last1", "hhw_share_last1", "anon_share_last1", "dup_share_last1",
             "units_last1", "nhw_season", "units_season"]
UNIT_FEATS = ["c_last1_per100u", "c_prev14_per100u", "units_breadth_last1"]
HEAT_CODES = ("NO HEAT", "NO HEAT AND NO HOT WATER")
NON_UNIT = {"", "BLDG", "BUILDING", "NAN", "NONE", "N/A", "NA"}


def season(d):
    return np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)


def load_complaints(path):
    """Distinct complaints with category flags; apartment -> unit_key hash only."""
    c = pd.read_csv(path, low_memory=False,
                    usecols=["received_date", "complaint_id", "bbl", "apartment",
                             "minor_category", "problem_code",
                             "problem_duplicate_flag", "complaint_anonymous_flag"])
    c = c.dropna(subset=["bbl"])
    c["bbl"] = c["bbl"].astype(float).astype("int64")
    c["day"] = pd.to_datetime(c["received_date"]).dt.normalize()
    apt = c.apartment.astype(str).str.strip().str.upper()
    c["unit_key"] = np.where(apt.isin(NON_UNIT), np.nan,
                             pd.util.hash_array(apt.to_numpy()).astype("float64"))
    c = c.drop(columns=["apartment", "received_date"])
    return prep(c)


def prep(c):
    """Flag columns from raw fields (shared by the loader and the tests)."""
    c = c.copy()
    c["season"] = season(c.day)
    c["heat"] = c.problem_code.isin(HEAT_CODES)
    c["nhw"] = c.problem_code.eq("NO HOT WATER")
    c["hhw"] = c.problem_code.eq("NO HEAT AND NO HOT WATER")
    c["anon"] = c.complaint_anonymous_flag.eq("Y")
    c["dup"] = c.problem_duplicate_flag.eq("Y")
    return c


def season_aggregates(c, S):
    """Prior-season (S-1) aggregates per bbl: only complaints with season == S-1."""
    p = c[c.season == S - 1]
    per = p.groupby(["bbl", "complaint_id"]).agg(
        heat=("heat", "max"), nhw=("nhw", "max"), hhw=("hhw", "max"),
        anon=("anon", "max"), dup=("dup", "max"))
    g = per.groupby("bbl")
    h = per[per.heat].groupby("bbl")
    out = pd.DataFrame({"nhw_last1": g.nhw.sum().astype(float)})
    nheat = h.size()
    out["hhw_share_last1"] = h.hhw.sum() / nheat
    out["anon_share_last1"] = h.anon.mean()
    out["dup_share_last1"] = h.dup.mean()
    out["units_last1"] = p[p.heat].groupby("bbl").unit_key.nunique().astype(float)
    return out.fillna(0.0)


def in_season(c, S, start):
    """Season-S counts strictly before the spell start (through the eve)."""
    p = c[(c.season == S) & (c.day <= start - pd.Timedelta(days=1))]
    out = pd.DataFrame({
        "nhw_season": p[p.nhw].groupby("bbl").complaint_id.nunique().astype(float),
        "units_season": p[p.heat].groupby("bbl").unit_key.nunique().astype(float)})
    return out.fillna(0.0)


def narrative_features(c, bbls, S, start, agg=None):
    """CAT_FEATS for buildings `bbls` on the eve of `start` (season S).
    `agg` = season_aggregates(c, S), passed in to reuse across a season's spells."""
    agg = season_aggregates(c, S) if agg is None else agg
    ins = in_season(c, S, pd.Timestamp(start))
    X = pd.DataFrame(index=pd.Index(np.asarray(bbls, dtype="int64"), name="bbl"))
    X = X.join(agg).join(ins)
    return X[CAT_FEATS].fillna(0.0)


def unit_features(unitsres, c_last1, c_prev14, units_last1):
    """UNIT_FEATS: complaint intensity normalized by residential units."""
    u = np.clip(np.nan_to_num(np.asarray(unitsres, dtype=float)), 1, None)
    return np.column_stack([np.asarray(c_last1) / u * 100,
                            np.asarray(c_prev14) / u * 100,
                            np.clip(np.asarray(units_last1) / u, 0, 1)])
