"""M13-cal - an honest isotonic calibrator for the frozen M13 per-spell scorer.

M13 (model/24) ranks best (90.1 / 65.4 / 51.4 / 35.2 on the 8 held-out spells)
but its bag-mean output is not a probability, so the site cannot show it as a
percentage. This script fits a calibrator WITHOUT touching M13: the five frozen
member JSONs are only loaded and scored; ranking and precision@k are asserted
unchanged.

Fit set (the choice, and why): the M13 members were refit on 2018-2024, so the
2024-25 validation spells are in-sample for them and a calibrator fit on their
val scores is optimistic (the caveat in model/25). Instead we FORWARD-CHAIN:
a "shadow bag" with M13's exact recipe (same config, same tree count, same five
seeds, read from final_spell_ensemble.json) is refit on 2018-2023 only, and
scores the 2024-25 spells out of sample. Isotonic is fit on those
(shadow score, outcome) pairs and then applied to the FROZEN bag's scores. The
shadow bag is used for nothing else and never ranks anything. The in-sample
alternative (isotonic on the frozen bag's own val scores, as in model/25) is
reported beside it for comparison only; the shipped calibrator was chosen
before the test look, not by it.

Verification: bin by bin on the 8 held-out 2025-26 spells (pooled building-
spells), observed rate with a Wilson 95% interval (same formula as T7,
model/15_inference.py), plus Brier vs climatology. Building-spells of the same
building across spells are correlated, so the Wilson intervals are somewhat
narrow; read them as a check, not a proof.

Display rule (unchanged): calibrated, capped at 99%, exact % below 20%, bands
above. Ties created by isotonic plateaus are broken by the raw score, so the
displayed order is the M13 order.

Run (instance, repo root, after model/13 and model/24):
    ~/datathon-env/bin/python model/26_m13_calibration.py
Writes (new files only; nothing existing is overwritten):
    model/out/m13_calibration.csv       isotonic knots (raw_score -> p), np.interp
    model/out/m13_cal_reliability.csv   the reliability table with Wilson CIs
    model/out/m13_cal_summary.csv       Brier / ECE / precision@k checks
"""

import glob
import json

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from common import OUT

G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M13_FROZEN = {100: .901, 500: .654, 1000: .514, 2500: .352}
CAP = 0.99
BINS = [0, .01, .02, .05, .10, .20, .40, .60, .80, 1.0001]

for f in ("m13_calibration.csv", "m13_cal_reliability.csv", "m13_cal_summary.csv"):
    assert not (OUT / f).exists(), f"{f} exists; this script never overwrites"


def wilson(k, n, z=1.96):          # identical to model/15_inference.py
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(mid - half), float(mid + half)


def load(path):
    z = np.load(path)
    return z["X"], z["y"].astype(np.int8), z["in_univ"], int(z["season"])


data = [(p,) + load(p) for p in sorted(glob.glob(str(G / "spell_*.npz")))]
tr = [d for d in data if 2018 <= d[4] <= 2023]
va = [d for d in data if d[4] == 2024]
te = [d for d in data if d[4] == 2025]
print(f"{len(tr)} train spells (2018-2023), {len(va)} val (2024-25), "
      f"{len(te)} test (2025-26)")
assert len(te) == 8, "expected the 8 held-out 2025-26 spells"

recipe = json.loads((OUT / "final_spell_ensemble.json").read_text())
assert recipe["w_bag"] == 1.0, "M13 is the pure bag; blend term not handled"
cfg, n_trees = recipe["config"], recipe["n_trees"]

frozen = []
for name in recipe["members"]:
    m = xgb.XGBClassifier()
    m.load_model(OUT / name)
    frozen.append(m)
print(f"loaded {len(frozen)} frozen M13 members ({n_trees} trees, {cfg})")


def bag_scores(models, ds):
    return [np.mean([m.predict_proba(d[1][d[3]])[:, 1] for m in models], axis=0)
            for d in ds]


def labels(ds):
    return [d[2][d[3]] for d in ds]


def spell_p(scores, ys, tiebreak=None):
    out = {k: [] for k in KS}
    for i, (sc, y) in enumerate(zip(scores, ys)):
        if tiebreak is None:
            order = np.argsort(-sc, kind="stable")
        else:                       # primary sc desc, then raw desc
            order = np.lexsort((-tiebreak[i], -sc))
        for k in KS:
            out[k].append(float(y[order[:k]].mean()))
    return {k: float(np.mean(v)) for k, v in out.items()}


# ---------------- shadow bag: M13's recipe, refit WITHOUT 2024-25
print("fitting the forward-chained shadow bag on 2018-2023 (calibration only)")
Xtr = np.vstack([d[1][d[3]] for d in tr])
ytr = np.concatenate(labels(tr))
shadow = []
for seed in range(len(recipe["members"])):
    m = xgb.XGBClassifier(n_estimators=n_trees, eval_metric="aucpr",
                          tree_method="hist", n_jobs=-1, random_state=seed, **cfg)
    m.fit(Xtr, ytr)
    shadow.append(m)          # in memory only; never saved, never ranks

yv = np.concatenate(labels(va))
sv_shadow = np.concatenate(bag_scores(shadow, va))
sv_frozen = np.concatenate(bag_scores(frozen, va))
print(f"val pairs: {len(yv):,} building-spells, base rate {yv.mean():.4f}")

iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
iso.fit(sv_shadow, yv)                         # SHIPPED: forward-chained
iso_in = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
iso_in.fit(sv_frozen, yv)                      # comparison only (optimistic)

knots = pd.DataFrame(dict(raw_score=iso.X_thresholds_, p=iso.y_thresholds_))


def calibrate(raw):            # portable form: what the site would run
    return np.interp(raw, knots.raw_score.to_numpy(), knots.p.to_numpy())


# ---------------- the test look: frozen M13 scores on the 8 held-out spells
st = bag_scores(frozen, te)
yt = labels(te)
ct = [calibrate(s) for s in st]
for s, c in zip(st, ct):
    assert np.allclose(c, iso.predict(s), atol=1e-12), "knot CSV != isotonic"
    o = np.argsort(-s, kind="stable")
    assert np.all(np.diff(c[o]) <= 1e-12), "calibration not monotone in raw"

p_raw = spell_p(st, yt)
p_cal = spell_p(ct, yt, tiebreak=st)
p_cal_ties = spell_p(ct, yt)                   # what NOT to do: sort on p alone
print("\nprecision@k on the 8 test spells (ranking must be untouched):")
for k in KS:
    print(f"  @{k:<5} raw {p_raw[k]:.4f} | calibrated+raw-tiebreak {p_cal[k]:.4f}"
          f" | frozen {M13_FROZEN[k]:.3f} | calibrated-only sort {p_cal_ties[k]:.4f}")
    assert round(p_raw[k], 3) == M13_FROZEN[k], "frozen M13 not reproduced"
    assert p_cal[k] == p_raw[k], "calibration changed precision@k"

yall = np.concatenate(yt)
sall = np.concatenate(st)
call = np.concatenate(ct)
cin = iso_in.predict(sall)
shown = np.minimum(call, CAP)

# ---------------- reliability table, pooled over the 8 test spells
rows = []
idx = np.digitize(call, BINS) - 1
print("\nreliability (shipped forward-chained calibrator, 8 test spells pooled):")
print(f"  {'bin':>11} {'n':>8} {'pred':>7} {'obs':>7} {'wilson 95%':>17}")
for b in range(len(BINS) - 1):
    mask = idx == b
    n = int(mask.sum())
    if n == 0:
        continue
    k = int(yall[mask].sum())
    pred = float(call[mask].mean())
    obs = k / n
    lo, hi = wilson(k, n)
    inside = lo <= pred <= hi
    label = f"{BINS[b]:.0%}-{min(BINS[b+1], 1):.0%}"
    rows.append(dict(bin=label, lo_edge=BINS[b], hi_edge=min(BINS[b + 1], 1.0),
                     building_spells=n, failures=k, predicted=round(pred, 4),
                     observed=round(obs, 4), wilson_lo=round(lo, 4),
                     wilson_hi=round(hi, 4), gap_pp=round(100 * (obs - pred), 2),
                     pred_in_ci=bool(inside),
                     displayed_as=("exact %" if BINS[b + 1] <= .20 else "band")))
    print(f"  {label:>11} {n:>8,} {pred:7.3f} {obs:7.3f} "
          f"[{lo:.3f}, {hi:.3f}] {'OK' if inside else 'OUTSIDE'}")
rel = pd.DataFrame(rows)


def brier(p):
    return float(np.mean((p - yall) ** 2))


def ece(p):
    i = np.digitize(p, BINS) - 1
    return float(sum(abs(p[i == b].mean() - yall[i == b].mean()) * (i == b).sum()
                     for b in np.unique(i)) / len(p))


base = yall.mean()
summary = dict(
    test_building_spells=len(yall), test_base_rate=round(float(base), 5),
    val_pairs=len(yv), n_knots=len(knots),
    brier_raw=round(brier(sall), 6),
    brier_cal_forward_chained=round(brier(call), 6),
    brier_cal_forward_chained_capped=round(brier(shown), 6),
    brier_cal_in_sample_val=round(brier(cin), 6),
    brier_climatology=round(float(base * (1 - base)), 6),
    ece_raw=round(ece(sall), 5), ece_cal_forward_chained=round(ece(call), 5),
    ece_cal_in_sample_val=round(ece(cin), 5),
    mean_pred_forward_chained=round(float(call.mean()), 5),
    mean_pred_in_sample_val=round(float(cin.mean()), 5),
    max_cal_p=round(float(call.max()), 4),
    share_above_20pct=round(float((call > .20).mean()), 5),
    bins_pred_in_wilson=f"{int(rel.pred_in_ci.sum())} of {len(rel)}",
    **{f"p_at_{k}_raw": round(p_raw[k], 4) for k in KS},
    **{f"p_at_{k}_calibrated": round(p_cal[k], 4) for k in KS},
)
print("\nsummary:")
for k, v in summary.items():
    print(f"  {k:34s} {v}")

knots.to_csv(OUT / "m13_calibration.csv", index=False)
rel.to_csv(OUT / "m13_cal_reliability.csv", index=False)
pd.DataFrame([dict(metric=k, value=v) for k, v in summary.items()]).to_csv(
    OUT / "m13_cal_summary.csv", index=False)
print("\nwrote m13_calibration.csv, m13_cal_reliability.csv, m13_cal_summary.csv")
print("M13 ranking untouched; precision@k asserted equal to the frozen numbers")
