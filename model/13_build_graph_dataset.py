"""M9 data: one graph snapshot per cold spell for the GraphSAGE experiment.

Nodes = every building that ever appears in the history universe, plus virtual
hub nodes (one per multi-building landlord, one per multi-building tax block) so
portfolio cliques stay linear. Per spell: node features (the 31 FEATS, as of the
spell's eve), spell label (fails during the spell +1 grace day), and the
in-universe mask for that date. Train spells: seasons 2018-2024. Test: the same
8 held-out 2025-26 spells the frozen numbers use.

Run from the repo root:  python model/13_build_graph_dataset.py
Writes model/out/graph/: nodes.npz (bbl order + edge_index), spell_<date>.npz
"""

import numpy as np
import pandas as pd

from common import (DATA, FEATS, NEVER, OUT, add_second_tier, band_prep, band_rates,
                    days_into_cold, first_cold_day, load_days, season, second_tier)

G = OUT / "graph"
G.mkdir(exist_ok=True)

days = load_days()
bd = pd.read_csv(OUT / "building_day_counts.csv", parse_dates=["day"])
bw = pd.read_csv(OUT / "building_day_counts_bw.csv", parse_dates=["day"])
buildings = pd.read_csv(DATA / "buildings.csv")
buildings["bbl"] = buildings["bbl"].astype(float).astype("int64")
viol = pd.read_csv(DATA / "hpd_heat_violations.csv", low_memory=False,
                   usecols=["bbl", "inspectiondate", "ordernumber"])
viol = viol[viol.ordernumber.astype(str).isin(["666", "966", "674"])].dropna(subset=["bbl"])
viol["bbl"] = viol["bbl"].astype(float).astype("int64")
viol["inspectiondate"] = pd.to_datetime(viol["inspectiondate"])
viol["season"] = season(viol.inspectiondate)

# ---- fixed node set: ever-active buildings
ever = sorted(set(bd.bbl) | set(viol.bbl))
buildings = buildings[buildings.bbl.isin(ever)].reset_index(drop=True)
bbls = buildings.bbl.to_numpy()
idx = {b: i for i, b in enumerate(bbls)}
NB = len(bbls)

# ---- edges through hub nodes (landlord, block)
lord_map = pd.read_csv(DATA / "second_tier/bbl_landlord.csv")
lord_map = lord_map[lord_map.bbl.isin(idx)]
lsz = lord_map.groupby("landlord").bbl.nunique()
lord_map = lord_map[lord_map.landlord.isin(lsz[lsz >= 2].index)]
lords = {l: NB + i for i, l in enumerate(sorted(lord_map.landlord.unique()))}

blocks = pd.Series(bbls // 10000)
bsz = blocks.value_counts()
blk_ids = {b: NB + len(lords) + i for i, b in enumerate(sorted(bsz[bsz >= 2].index))}

src, dst = [], []
for b, l in zip(lord_map.bbl, lord_map.landlord):
    src += [idx[b], lords[l]]
    dst += [lords[l], idx[b]]
for i, blk in enumerate(blocks):
    h = blk_ids.get(blk)
    if h is not None:
        src += [i, h]
        dst += [h, i]
N = NB + len(lords) + len(blk_ids)
edge_index = np.array([src, dst], dtype=np.int64)
np.savez_compressed(G / "nodes.npz", bbls=bbls, n_nodes=N, n_buildings=NB,
                    edge_index=edge_index)
print(f"graph: {NB:,} buildings + {len(lords):,} landlord hubs + "
      f"{len(blk_ids):,} block hubs = {N:,} nodes, {edge_index.shape[1]:,} directed edges")

# ---- shared aggregates (same code path as the frozen evaluators)
bd["season"] = season(bd.day)
bw["season"] = season(bw.day)
sc = bd.groupby(["bbl", "season"])["n"].sum()
sv = viol.groupby(["bbl", "season"]).size()
sbw = bw.groupby(["bbl", "season"])["n"].sum()
num, den = band_prep(bd, days)
lord2, boiler = second_tier()
sc_df = sc.rename("c").reset_index()
first55 = first_cold_day(days)

base = buildings[["bbl", "unitsres", "yearbuilt", "yearalter1",
                  "numfloors", "bldgarea", "cd"]].copy()
base["yearbuilt"] = base.yearbuilt.replace(0, np.nan)
base["altered"] = (base.yearalter1.fillna(0) > 0).astype(int)


def hist(s, yr, bb):
    return bb.map(s.xs(yr, level="season")).fillna(0) \
        if yr in s.index.get_level_values(1) else 0.0


# truth: cluster building-days
nxt = bd[["bbl", "day", "n"]].copy()
nxt["day"] -= pd.Timedelta(days=1)
truth = bd[["bbl", "day", "n"]].merge(nxt, on=["bbl", "day"], how="outer",
                                      suffixes=("", "_next")).fillna(0)
truth = truth[(truth.n + truth.n_next) >= 2]

# spells across all seasons
wx = days[days.heat_season].sort_values("day").copy()
wx["tmean"] = (wx.TMAX + wx.TMIN) / 2
wx["frz"] = wx.tmean < 32
wx["run"] = (wx.frz & ~wx.frz.shift(fill_value=False)).cumsum()
spells = (wx[wx.frz].groupby("run").agg(start=("day", "min"), end=("day", "max"),
                                        ndays=("day", "size")))
spells = spells[spells.ndays >= 2]
spells["S"] = season(spells.start)
spells = spells[spells.S.between(2018, 2025)]
print(f"{len(spells)} spells (seasons 2018-2025)")

Xseason_cache = {}
for _, sp in spells.iterrows():
    s, e, S = sp.start, sp.end + pd.Timedelta(days=1), int(sp.S)
    if S not in Xseason_cache:
        X0 = base.copy()
        X0["c_last1"] = hist(sc, S - 1, X0.bbl)
        X0["c_last2"] = X0.c_last1 + hist(sc, S - 2, X0.bbl)
        X0["v_last1"] = hist(sv, S - 1, X0.bbl)
        X0["v_last2"] = X0.v_last1 + hist(sv, S - 2, X0.bbl)
        X0["chronic"] = ((X0.c_last1 >= 5) & (hist(sc, S - 2, X0.bbl) >= 5)).astype(int)
        X0["bw_last1"] = hist(sbw, S - 1, X0.bbl)
        X0 = X0.merge(band_rates(num, den, S, X0.bbl), on="bbl", how="left")
        X0 = add_second_tier(X0, lord2, boiler, sc_df, S)
        Xseason_cache = {S: X0}            # keep only the current season cached
    X = Xseason_cache[S].copy()

    cutoff = s - pd.Timedelta(days=1)
    pre = bd[bd.day <= cutoff]
    for w, col in [(2, "c_prev2"), (7, "c_prev7"), (14, "c_prev14"), (30, "c_prev30")]:
        r = pre[pre.day > cutoff - pd.Timedelta(days=w)].groupby("bbl")["n"].sum()
        X[col] = X.bbl.map(r).fillna(0)
    X["days_since_c"] = (s - X.bbl.map(pre.groupby("bbl").day.max())).dt.days.fillna(NEVER)
    X["days_since_v"] = (s - X.bbl.map(viol[viol.inspectiondate <= cutoff]
                                       .groupby("bbl").inspectiondate.max())).dt.days.fillna(NEVER)
    bwpre = bw[(bw.day <= cutoff) & (bw.day > cutoff - pd.Timedelta(days=14))]
    X["bw_prev14"] = X.bbl.map(bwpre.groupby("bbl")["n"].sum()).fillna(0)
    blk2 = (pre[pre.day > cutoff - pd.Timedelta(days=2)]
            .assign(blk=lambda t: t.bbl // 10000).groupby("blk")["n"].sum())
    X["nb_block_2d"] = np.clip((X.bbl // 10000).map(blk2).fillna(0) - X.c_prev2, 0, None)
    drow = days.loc[days.day == s].iloc[0]
    for c in ["TMIN", "TMAX", "tmin_lag1", "tmin_roll3", "tmin_drop", "SNOW", "AWND", "wday_num"]:
        X[c] = drow[c]
    X["days_into_cold"] = days_into_cold([s], [S], first55)[0]

    in_univ = ((X.days_since_c < NEVER) | (X.days_since_v < NEVER)).to_numpy()
    pos = set(truth.loc[truth.day.between(s, e), "bbl"])
    y = np.fromiter((b in pos for b in X.bbl), dtype=np.int8, count=len(X))
    np.savez_compressed(G / f"spell_{s.date()}.npz",
                        X=X[FEATS].to_numpy(dtype=np.float32), y=y,
                        in_univ=in_univ, season=S)
    print(f"  {s.date()} S{S}: universe {in_univ.sum():,}, positives {int(y[in_univ].sum()):,}",
          flush=True)
print("done ->", G)
