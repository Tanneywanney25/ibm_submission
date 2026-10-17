# T9 — Explainability: SHAP per building, "why" on the website

**Goal:** every risk number comes with its reasons. Global attribution for the
deck; per-building top-5 factors on the lookup page: "Why: 76 complaints last
season · owner's other buildings · 14 in the last 2 weeks · oil boiler ·
chronic." Transparency a tenant, a landlord's lawyer and a judge can all read.

## Method

1. `pip install shap` (laptop is fine — XGBoost **JSON** models load
   cross-platform; the no-cross-machine rule is about pickles). TreeExplainer
   on M2 (`heat_model_final.json`) over the replay/static feature matrix
   (`model/out/replay/static_features.csv` or regenerate via `model/10`).
2. **Global:** mean |SHAP| bar table + beeswarm for the deck; compare with
   `feature_importance.csv` (gain) — note where they disagree.
3. **Per building:** top-5 features by |SHAP| with sign and a human phrase
   (map feature → template: `c_last1` → "{v} heat complaints last season").
   Guardrails: building-level only; phrases describe the building's record,
   never accusations; landlord phrasing matches T5's tone rule.
4. **Ship to the site:** extend `web/build_assets.py` to add
   `why: [five strings]` to each building shard (`public/data/b/NN.json`);
   building.html renders a "Why this number" list (LITE mode reads the shard,
   FULL mode may compute live or read the same file). Keep shards under the
   VERCEL.md 60 MB total budget — five short strings per building is ~3 MB.
5. Also attach per-building `why` to M8's enforcement queue export if time.

## Deliverables

- `model/17_shap.py` → `model/out/shap_global.csv`, `shap_why.csv` (bbl + 5 phrases)
- Updated shards via `web/build_assets.py` + the building-page panel
- Two deck images (global bar, one annotated building example)

## Acceptance

- [ ] Global SHAP ranks plausibly (days_since_c / c_last2 family on top)
- [ ] Spot-check 5 buildings: phrases match their actual records
- [ ] No apartment data, no accusatory phrasing, bands/caps respected
- [ ] Site smoke test (VERCEL.md §6) green after the shard rebuild

**Effort ~4h. Depends on:** M2 + feature matrix (done). **Feeds:** website, deck, T5 drafts.
