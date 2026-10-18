# About page — published copy and claim ledger

Updated October 18, 2026. Implemented in `web/templates/about.html`, styled only by
`web/static/about.css` plus the existing shared help/site styles. This replaces
the earlier draft: that draft mixed complaint labels with verified failures,
frozen and later model results, display bands with confidence intervals, and
simulated dispatch results with real-world impact.

## Purpose and layout

The About page explains the project and its evidence. Product walkthroughs and
building lookup remain elsewhere. Its hero has one in-page link to training;
it does not repeat the old “Check a building” / “How to use the site” action pair.
Desktop has a section index beside the text; smaller screens use a wrapping
index. Native `details` sections hold weather analysis, training settings,
other results and simulation details. All content is server-rendered and readable
without JavaScript, sign-in, model outputs or an AI provider.

Public section order:

1. Why we built it: earlier attention to likely heat problems, intended users,
   and the practical website the research feeds.
2. Data and signals: complaints, violations, PLUTO, owners, boilers and weather;
   identifiers, deduplication and weather-band reaction rates.
3. Training: define the target, build past-history features, fit boosted trees,
   evaluate a later winter, and explain the later spell-model split.
4. Evaluation: original M1 vs 14-day recency at four list depths; clearly
   separate other prediction windows, M13 and dispatch simulation.
5. Score meaning: ranking vs calibration, winter vs cold-day probability,
   actual season calibration split, and display bands vs uncertainty intervals.
6. IBM Z: what ran there, qualified CPU benchmark, LinuxONE/Vercel division.
7. Models and help chat: supervised prediction models; local help matching and
   optional pretrained-language-model topic selection.
8. Limits and next steps: reporting bias, incomplete coverage, observed-weather
   backtests, stale records, local performance audits and timing-model limits.
9. Team and reproducibility: NYU Tingineers, datathon, project record and contact.

## Stable links

Keep the existing IDs `what-it-is`, `methods`, `top-100`, `uncertainty` and
`open-source`. Other pages already link to `/about#methods`. New IDs are `data`,
`ibm-z`, `help-chat` and `limits`. No route, API or score format changed.

The `open-source` ID is retained for old links; its heading is now “Team &
reproducibility.” It does not assert a license that has not been committed.

## Claim ledger

These are existing project findings, not numbers recomputed for the page.
The primary evidence is the actual pipeline plus the team's frozen reports.

| Public claim | Source and qualification |
|---|---|
| Main outcome = at least two distinct heat complaints across day d and d+1 | `model/01_build_panel.py`, `docs/model-plan.md`. Daily aggregates, not a rolling timestamp-level 48-hour window. A complaint cluster is a proxy for a reported heat problem, not proof of a boiler failure or a confirmed violation. |
| Records are joined by property IDs; BBL refers to a tax lot | `model/01_build_panel.py`, `model/00_second_tier.py`; see BBL vs BIN/building_id mismatch discussion in `docs/model-iterations.md`. Avoid implying one BBL always means one physical building. |
| Frigid <20°F, freezing [20,32), cold [32,45), mild 45°F+ | `model/common.py:band_prep`, `band_rates`. Previous two seasons; denominator includes eligible days with no complaint. No claim that every building is observed failing on these days. |
| Recent counts 2/7/14/30 days; previous-season history; portfolio/block/weather/property inputs | `model/common.py:FEATS`, `model/01_build_panel.py`. Avoid the stale “31 features” count from older docs; current serving notes list 36. |
| Original model averages XGBoost and HistGradientBoosting | `model/02_train.py`, M1 in `docs/model-catalog.md`. Both original recipes use 400 rounds, depth 6, learning rate 0.08. |
| 622,362 training building-days, seasons 2018–19 through 2024–25 | M1 in `docs/model-catalog.md`. Sampled negatives make the training base rate unsuitable for displayed probabilities; ranking evaluation uses the full eligible population. |
| Original ranking test = 2025–26, held out from fitting M1 | `model/02_train.py`, `model/03_evaluate.py`, `model/07_spell_eval.py`. Calibration uses separate protocols; do not call 2025–26 untouched for every use. Deployment refits include that season and are not evaluation models. |
| Later spell model fits 2018–23, selects on 2024–25, refits through 2024–25, tests 2025–26 | `model/21_spell_direct.py`, `model/24_final_squeeze.py`. Five seed fits; each finalist has a test evaluation, so repeated experiments do not create more independent test winters. The M13 blend selection also reuses validation data after refit; see code comment. |
| M1 spell precision at 100/500/1000/2500 = 86.1/64.6/51.4/34.8%; 14-day baseline = 77.1/59.9/47.8/31.9% | `docs/model-iterations.md` spell table, `docs/model-final-comparison.md`. Mean over eight 2025–26 spells; not a probability for every mapped building or a confirmed-violation rate. |
| Original model wins six of six forward-moving winter tests | `model/05_backtest.py`, M6 in `docs/model-catalog.md`. Historical comparisons; not a future performance guarantee. |
| Approximate spell 95% interval 81–92%; cold-day-block daily interval 66–71% | T7 statistical notes in `docs/model-iterations.md`, `model/15_inference.py`. Saved follow-up inference run has slight training variation vs frozen M1 points (about 87% vs 86.1%, 69.4% vs 69.1%). Page explicitly labels ranges approximate and states they come from the follow-up run. No invented M13 confidence interval. |
| Daily top-100 69.1% at 48h, 96.6% at 30d; first-spell watchlist top-100 99% | Frozen summary in `docs/model-iterations.md`, Part 6 of `docs/models-complete-report.md`, and the first-spell output in `model/07_spell_eval.py`. The 99% is a first-spell ranking followed through the rest of that winter, not M4 calibration. Corrects the earlier page/ledger interpretation. |
| M13 top-100 spell precision = 90.1% | `docs/model-final-comparison.md`, `model/24_final_squeeze.py`. Report separately; preserve original M1 numbers. The current `public/data/meta.json` lists M2/M4 outputs, so do not assert M13 powers the public map or every current score. |
| Ranking-objective and graph experiments not adopted | M7 and M9 in `docs/model-catalog.md`, `docs/experiments-report.md`. M7 improves top 100 but loses at greater depth; M9 scores below M1. Do not claim both lose at every cutoff. |
| Dispatch simulation: 183,384 cases, 700/day, expiry 14d, +7.8% estimated confirmations, 2.03 vs 3.12 day failing-case waits, 5,546 failing cases expired | T12 in `docs/experiments-report.md`. A retrospective simulation, with capacity/expiry assumptions and unvisited-case trade-offs; not a deployment trial, outage prevention, or observed health benefit. |
| Season calibration fits half of 2025–26 records and checks the other half | `model/09_season_risk.py`. Distinct from ranking holdout claims. Daily full-universe calibration described by M3 in `docs/model-catalog.md`. |
| Display cap 99%, approximate bands from 20% | `web/templates/base.html:fmtRisk`, `docs/webapp-spec.md`. These are display bands, not individual-building confidence intervals. |
| Snap ML 481,356 buildings/sec on a 3-core s390x guest | M5 in `docs/model-catalog.md`, frozen benchmark in `docs/SUBMISSION.md`. Separate native Snap ML benchmark; CPU tree engine, not evidence of Telum offload or website speed. |
| No LLM trained/fine-tuned for risk prediction | Inspected `model/` pipeline uses supervised tabular methods and a separate graph experiment. `web/site_guide.py` optionally calls an existing model only to choose a help topic. No LLM training artifact or recipe found. Revisit only if the team supplies evidence of additional work. |
| Chat supports local related-word/typo matching and ambiguity options | `web/static/guide.js`, `web/static/guide-content.json`, `web/site_guide.py`. Optional AI proposes a known topic for visitor confirmation; written answers, no score generation or autonomous account/message actions. |
| Reporting bias, observed weather backtests, history-based universe | Honest limitations in `docs/model-iterations.md`, eligibility logic in model evaluators. Unranked does not mean safe; weather forecast trials and equity validation remain follow-ups. |
| Timing model not shipped | M10/M10b in `docs/model-catalog.md`; do not promise precise failure dates. |

## Language and publication rules

- Explain a complaint cluster as a reported-problem label; use “confirmed” only
  for violations. Do not call a cluster a proven whole-building outage.
- Keep original headline figures fixed; distinguish model versions, time windows,
  ranking metrics, calibration, simulations and benchmark engines.
- Explain uncertainty without claims of certainty, causal impact, equitable
  performance or universal coverage. A good average is not a guarantee for an address.
- Nothing here changes the model, ranks, map, building page, account flow or alerts.
- The new page documents existing ML work; it does not invent LLM fine-tuning,
  embeddings, retrieval pipelines, Telum offload or a deployed Granite assistant.
- Follow T16's existing source-release rule: source on request until team sign-off
  and a LICENSE are in place. This change does not publish a new repository link.
- Contact: `heataheadnyc@gmail.com`. Independent project, not an NYC311/HPD service.

## Local checks for this update

- Python compile check: `python -m compileall -q web api`.
- 48 existing backend tests passed, including accounts, newsletter and guide routes.
- Existing help-chat DOM and matching checks passed (29 published questions,
  natural-language examples, ambiguity choices, safe links and offline fallback).
- 22 anonymous/signed-in template renders and 31 LITE HTTP routes/assets passed.
- About HTML nesting, unique IDs, old/new anchors, every local page/fragment/style
  link, read-only rendering without credentials and CSS parsing checked.
- Responsive rules are included for tablet/phone widths; this environment did not
  provide a local Chromium binary, so physical-device visual testing remains a
  Vercel preview check.

## Deeper methods expansion from the supplied October 18 report

The supplied `models-complete-report(1).md` was byte-identical to the current
`docs/models-complete-report.md` when read. The report is left unchanged; the
page uses it as an evidence source, checked against code and the public data.

- New hero: research/methodology framing, training counts, calm solid-green
  accents and an editorial reading layout. No repeated building-lookup CTA.
- `model/common.py` has 36 FEATS (verified by parsing the actual declaration),
  grouped 6+7+3+6+4+1+9 on the page. `09_season_risk.py` has 21 SFEATS.
- Expanded cleaning/label workflow, 1.87x historical confirmation association,
  sampling, original M1 settings and five-seed M13 recipe. The 61-tree/depth-7
  winner is a reported run finding, not a new fit made for this website change.
- Distinguish M1 evaluation ensemble, M2 XGBoost deployment refit, M3 calibration,
  M4 winter risk and M13 spell experiments. `06_final_scores.py` calls
  `make_model()` and fits XGBoost when available: do not label M2 an exported
  two-backend ensemble just because the narrative report says “same recipe.”
- Four evaluation windows are named precisely. Cold-day test uses TMIN<32F;
  spell test uses >=2 consecutive mean-temperature<32F days plus a grace day.
  The watchlist's 99% is not an M4 season-risk calibration result.
- M13 results and cumulative gain are separate from M1 headlines and from the
  current site queue. Six-winter table explicitly tests ten coldest days per
  fold, so its 2025-26 value does not replace the 71-day headline.
- Development runs, rejected models, confirmed-violation target, M14's lack of
  narrative text, unfinished feature-removal work and alert threshold trade-offs
  have their own native disclosures. No validation-only RFE score is promoted.
- Live public reliability data, not the older report's example table, supplies
  the season calibration table. `site_guide.init_app(..., about_data=...)` takes
  a read-only callback over the existing app's META/RELIABILITY objects. No
  network call, model import, database or additional package is introduced.
- LLM section documents local matching, optional pretrained-model topic
  classification, visitor confirmation, authored answers, strict topic schema,
  filtering and fallback. It does not invent fine-tuning on complaint stories.
- Engineering disclosure adds CPU benchmark comparison, separate compression/
  cryptography benchmarks and reproducible pipeline script names. Not Telum
  tree offload, web latency or observed tenant-health impact.
- Limitations explicitly include present-day ownership snapshots and large
  multi-building BBL complexes, alongside missing reports and unranked records.
- The original five deep-link IDs remain; new `experiments` ID joins the index.

The source-license rule from T16 remains as before. Reading or expanding this
page does not require publishing a new source link or changing model artifacts.

### Final combined-update checks

The navigation/queue/About package passed 52 backend tests, 24 anonymous/signed-in
page renders, 34 LITE HTTP route/asset checks, About HTML and all local-anchor
checks, all eight reliability-row comparisons against published data, CSS parsing,
help-chat/matcher/privacy checks and the existing map regression checks.
`public/data/top50.csv` has exactly 50 unique BBLs in the existing model order.
No new model training, real email, remote database write or production deployment
was performed. A local Chromium binary was not available for visual browser QA.

Source nuance: the report calls the time-filtered boiler variant adopted, while
`08_stream2_ablation.py` demonstrates it as a tested variant and the shared
loader still reads a boiler snapshot. The page says the corrected variant was
**tested**, without claiming every published artifact used it. The ownership/
snapshot limitation remains visible.

Before packaging, synced main through `f1acaec` and retained the teammate's new
Save-a-building address autocomplete, SMTP setup script and deployment notes.
