# HeatAhead: The Complete Model Report

This document explains every model the HeatAhead team has built, how each one was built, how each one was scored, what the scores mean, and which models we decided to keep. It is written for a reader who has never seen this project before. Nothing here assumes you have read any other file in the repository, although each section names the script and the output file that hold the underlying evidence, so that every number can be traced and reproduced.

The report was written on October 18, 2026, the final day of the IBM Z Datathon. The feature elimination study described in Part 9 finished on the LinuxONE machine the same day, and its final test results are included.

## Contents

1. What we are predicting and why
2. The data and the time rules that keep the evaluation honest
3. How we score a model, explained from the ground up
4. The baselines every model must beat
5. How the main model was built, one iteration at a time
6. The submission model and its scores
7. How we checked that the scores are real
8. The supporting models that make the product work
9. Every experiment we ran after the submission model, and what happened
10. Where the models run: the IBM LinuxONE machine
11. What we use today, and what we decided not to use
12. Honest limitations
13. Glossary

---

## Part 1. What we are predicting and why

Every winter, thousands of New York City apartment buildings lose heat. New York City law requires landlords to keep apartments at 68 degrees Fahrenheit during the day and 62 degrees overnight from October 1 to May 31. When the heat fails, tenants call 311, the city's service line, and the Department of Housing Preservation and Development (HPD) sends an inspector. Today the city works through these complaints largely in the order they arrive. By the time an inspector reaches a building, the tenants may have been cold for days.

HeatAhead turns this around. Before a cold spell arrives, it ranks every building in the city by how likely it is to lose heat, so that inspectors can visit the most likely failures first, or even before the failure happens.

### The question each model answers

The main model answers one question for one building on one day: **given what we know on the evening before a freezing day, what is the probability that this building will have a heat failure within the next 48 hours?**

We need a precise definition of "heat failure" that can be measured from public records. We use this one:

> A building has a **heat failure** on a given day if it receives two or more separate heat complaints within a 48 hour window that starts on that day.

We require two complaints instead of one because a single complaint is often one cold apartment, a misunderstanding, or a call that leads nowhere. Two or more distinct complaints from the same building within two days is much more likely to mean the building's heating system has actually failed. We checked this directly with HPD's inspection records. When a building receives a single isolated complaint, an inspector finds and records a heat violation within seven days only 4.78 percent of the time. When it receives two or more complaints within 48 hours, that rate rises to 8.93 percent, which is 1.87 times higher. With three or more complaints it reaches 10.61 percent, and with five or more it reaches 12.31 percent. The relationship is stable across years: 1.88 times on the training seasons and 1.83 times on the held out 2025 to 2026 winter. These numbers come from the team's Stream 2 analysis of 1,027,559 heat season complaint clusters.

You may wonder why confirmed violations are so rare even for clear failures. The answer is inspector capacity, not a weak label. On February 8, 2026, the busiest day in the data, the city received 5,751 heat complaints and only 9.8 percent of the resulting clusters were confirmed within seven days. On the six busiest days of the 2025 to 2026 winter, inspections completed per 100 complaints fell by a third, from 36.8 to 25.1. A confirmed violation therefore measures how many inspectors were available as much as it measures broken boilers. For this reason we train our main models on the complaint based label and report the confirmed violation results separately as a second check.

We call the inspector confirmed version the **verified** label: a building is a verified failure if HPD records a heat violation (order numbers 666, 966 or 674) at that building within seven days. One model in this report, M8, is trained directly on the verified label.

---

## Part 2. The data and the time rules that keep the evaluation honest

### Sources

| Source | What it contains | How we use it |
|---|---|---|
| HPD heat complaints | About 2.2 million complaint records with the date, the building, the complaint category and intake flags | The label, and most of the strongest features |
| HPD heat violations | Every heat violation an inspector recorded | Violation history features, and the verified label |
| PLUTO building records | Units, floors, floor area, year built, alterations, community district, location | Building features |
| NOAA Central Park weather | Daily minimum and maximum temperature, snow and wind | Weather features and the definition of cold days |
| HPD registrations | The registered owner and managing agent of each building | Landlord portfolio features |
| Department of Buildings boiler records | Boiler defects and the fuel type | Boiler features |

The city has 172,485 residential buildings in our building table. We rank only the buildings that have at least one heat complaint or heat violation in their past, which is about 63,000 to 67,000 buildings depending on the date. We made this choice deliberately. A building with no history at all gives any method nothing to go on, and in testing we confirmed that no ranking method, ours or any baseline, could find the failures in buildings with no history. Cutting them removed nothing that any method could rank.

Every feature and every result is at the level of the whole building. The raw complaint file contains apartment numbers, but no apartment number appears in any table, feature, result or web page that this project produces.

### Seasons

A heating season runs from October through May. We name each season by the year it starts, so the "2024 season" or "2024 to 2025 season" means October 2024 through May 2025.

### The three time rules

Prediction models can easily look better than they are by accidentally using information from the future. We enforced three rules everywhere, and we wrote automated tests that fail if any of them is broken.

1. **Features only use the past.** Every feature for a building on a given day is computed only from data dated before that day. Season level history uses only earlier seasons. Short window counts such as "complaints in the last 14 days" end on the evening before the ranking day and never include the day itself.
2. **The test winter is never touched during development.** The 2025 to 2026 winter is held out. No model was trained on it, tuned on it or selected using it. Models are scored on it once, at the end.
3. **Status fields are never features.** Fields such as the complaint's final status and the date the problem was closed are only known after the fact, so they are banned from every feature list.

The automated test suite (`tests/test_leakage.py`) currently contains ten tests. They check that last season counts equal the true count from the previous season, that the trailing windows end the day before, that a building's own complaints on the ranking day never leak into a feature, that the banned columns never appear in any model script, that every shipped probability is capped at 99 percent, that no shipped file contains an apartment column, and that the new complaint category features use only earlier complaints. All ten pass.

### How the training data is built

To train the main model we build a **panel**: a table in which each row is one building on one heat season day, together with that row's features and whether a heat failure followed. Using every building on every day would produce tens of millions of rows, almost all of them non failures. Instead, the panel keeps every actual failure (every positive row) from the 2018 through 2025 seasons and adds twice as many randomly sampled non failure rows. The training panel for the submission model contains 622,362 rows. Because the panel deliberately contains far more failures than real life does, scores computed on the panel are inflated, and we never report panel scores as real world performance. All the real world scores in this report come from ranking every eligible building in the city, as described next.

---

## Part 3. How we score a model, explained from the ground up

This is the most important part of the report. Every number later in the document is one of the measures defined here.

### The basic idea: ranking, then counting

A city inspector cannot visit every building. On a cold day the inspection service can reach a limited number of buildings, perhaps a few hundred or a few thousand. What matters is therefore not whether the model gets every building right, but whether **the buildings at the top of its list are the ones that actually fail**.

So we score every model the way it would be used. On each test day, the model scores every eligible building in the city, about 60,000 to 67,000 of them. We sort the buildings from highest score to lowest. We take the top k buildings, where k is a number of inspections, and we count how many of those k buildings actually had a heat failure.

### Precision at k

**Precision at k** is the share of the top k buildings that actually failed.

For example, "precision at 100 is 69.1 percent" means that on an average test day, of the 100 buildings the model ranked highest, about 69 actually had a heat failure within the next 48 hours, and about 31 did not.

We report four values of k: 100, 500, 1,000 and 2,500. These stand for different amounts of inspection capacity. A precision at 100 tells you how good the very top of the list is. A precision at 2,500 tells you how good the list is at the scale of a citywide operation. Precision always falls as k grows, because the model puts its most confident picks first. A falling number at large k is expected and is not a weakness.

It helps to know how rare failures are. On a typical cold day, only a few percent of eligible buildings have a heat failure. If you picked 100 buildings at random, you would expect to find only about 3 failures. A precision at 100 of 69 percent is therefore roughly 20 times better than random selection.

### Daily scoring, spell scoring and the four horizons

We score precision in four ways. They differ in what counts as "the building failed."

1. **Exact 48 hours, scored daily.** On each of the 71 days of the 2025 to 2026 winter when the minimum temperature fell below 32 degrees, rank all buildings and count a building as a success only if it failed within 48 hours of that day. The reported number is the average over the 71 days. This is the strictest version, because tenants do not always call on the first day the heat fails.
2. **During the spell.** Inspectors work through a cold spell, not a single calendar day. We define a cold spell as two or more consecutive days with an average temperature below freezing. The 2025 to 2026 winter had eight such spells. For each spell, the model ranks buildings once, on the evening before the spell starts, and a building counts as a success if it fails at any point during the spell (plus one grace day). The reported number is the average over the eight spells.
3. **Within 30 days.** The same ranking, but a building counts as a success if it fails at any point in the next 30 days. This answers the operational question "should this building be checked now?" The forecast still only looks one to two days ahead. The 30 days is only the window in which we watch for the outcome.
4. **Preseason watchlist.** The model ranks buildings once, at the first cold spell of the season, and a building counts as a success if it fails at any point during that winter.

These four versions form what we call **the honest ladder**. Each step relaxes the timing requirement, so each number is higher than the last. All four are true at the same time, and each answers a different practical question.

### Recall

**Recall at k** is the share of all of the day's failures that appear in the top k. If 2,000 buildings fail on a given day and 1,300 of them are in the model's top 2,500, recall at 2,500 is 65 percent. Precision asks "how many of my picks were right?" Recall asks "how many of the real failures did I catch?"

### Measures over the whole list

Precision at k only grades the top of the list. To grade the whole ranking of roughly 62,000 buildings, we also report these measures.

- **Cumulative gain.** If you inspect the top X percent of the list, what share of all failures do you catch? Random inspection catches X percent of failures in X percent of buildings. A good model catches far more.
- **PR-AUC (area under the precision recall curve).** This is a single number between 0 and 1 that summarizes precision across every possible list length. A model with no skill scores about the base rate, which is the share of buildings that fail. So PR-AUC must always be read next to the base rate. A PR-AUC of 0.434 when only 3.1 percent of buildings fail is about 14 times better than no skill.
- **Brier score.** This measures how close the predicted probabilities are to what actually happened, as the average squared difference between the predicted probability and the outcome (1 for a failure, 0 for no failure). Lower is better. The usual comparison is "climatology," which means predicting the overall base rate for every building.

### Calibration: when a model says 60 percent, does it mean it?

A ranking only needs scores to be in the right order. But the website shows tenants and inspectors probabilities, and a probability is only honest if it is **calibrated**. A model is calibrated if, among all the buildings it gives a 60 percent chance, about 60 percent actually fail.

Raw model scores are not calibrated, partly because the training panel contains far more failures than real life does. A raw score of 0.999 on the panel corresponds to a real 48 hour chance of about 54 percent. So we pass every displayed number through a **calibrator**, a second small model that maps raw scores to real probabilities. We use **isotonic regression**, which learns the mapping from real data and only assumes that higher scores should mean higher probabilities. It does not change the order of the buildings, so it cannot change any precision at k score.

We check calibration with a **reliability table**: group buildings by predicted probability, then compare the average prediction in each group with the share that actually failed. We also put a **Wilson confidence interval** around each observed share, which is a standard way to measure how much a percentage could move by chance given the number of buildings in the group.

The website follows three display rules. Probabilities are always calibrated. They are capped at 99 percent, because certainty is never honest. Probabilities above 20 percent are shown as bands, such as "very high, roughly 60 percent," so that the page does not suggest more precision than the model has.

### Measures for the timing model

One model in this report, M10, predicts when a building will first fail, not just whether it will. It is scored with two additional measures.

- **The C-index (concordance index).** Take two buildings where the first actually failed earlier than the second. The C-index is the share of such pairs where the model also gave the earlier failing building the higher risk. A value of 0.5 means the model is guessing. A value of 1.0 means it always orders the pair correctly.
- **Horizon calibration.** At fixed dates (December 1, January 1 and February 1) we compare the model's predicted share of buildings that will have failed by that date with the share that actually had, separately for each tenth of the buildings sorted by predicted risk (a "decile"). The difference is reported in **percentage points**, which means the plain difference between two percentages. If the model predicts 30 percent and 25 percent actually failed, the gap is 5 percentage points.

### Measures for the alert guarantee

One part of the product, the email alerts, is scored by its **false negative rate**: of all the buildings that actually failed on a cold day, the share that the alert rule did not flag. A false negative rate of 7.4 percent means the alerts missed 7.4 percent of the real failures and caught the other 92.6 percent.

### Measures of speed

On the IBM machine we measure two speeds.

- **Batch throughput:** how many buildings per second the model can score when it scores the whole city at once.
- **p99 single row latency:** the time it takes to score one building, at the 99th percentile. This means 99 out of 100 single building requests finish at least this fast.

### How we decide whether a difference is real

A model that wins by one point on one winter might just be lucky. We used four tools to check whether differences are real.

- **Confidence intervals by cluster bootstrap.** We resample whole days (or whole spells) with replacement 2,000 times and recompute the score each time. The middle 95 percent of those recomputed scores is the 95 percent confidence interval. We resample whole days rather than single buildings because buildings on the same day share the same weather, so they are not independent.
- **Paired permutation tests.** For each test day we compute the model's score minus the baseline's score. If the model were no better than the baseline, these differences would be equally likely to be positive or negative. We randomly flip their signs 100,000 times and ask how often chance produces an edge as large as the real one. That share is the **p-value**. A small p-value means chance is a poor explanation.
- **Exact tests on spells.** With only eight spells we can list all 256 possible patterns of wins and losses. If the model beats the baseline in all eight spells, the p-value is exactly 1 in 256, which is 0.0039 and is the smallest an eight spell test can produce.
- **Seed checks.** Tree models use randomness during training. We retrain the same model with different random seeds and see how much the scores move. A gap smaller than the seed to seed spread is not evidence of anything.

### Validation and test

When we choose between model versions, we make every choice using the **validation winter**, 2024 to 2025, and only then look at the **test winter**, 2025 to 2026, once. If we chose the version with the best test score, the test score would be flattering by construction. Several sections below say "selected on validation, tested once." This is what they mean.

---

## Part 4. The baselines every model must beat

A model is only useful if it beats the simple rules a city could use today without any modeling. Every evaluation in this report scores three such rules under exactly the same protocol.

| Baseline | Rule | Precision at 100, exact 48 hours | Precision at 100, during the spell | Precision at 100, within 30 days |
|---|---|---|---|---|
| B1 | Rank by last season's complaint count | 43.5% | not separately reported | not separately reported |
| B2 | Rank by complaints in the last 14 days | 61.7% | 77.1% | 91.0% |
| B3 | Rank by last season's violation count | 14.7% | not separately reported | not separately reported |

B2, the trailing 14 day count, is the strong one and is the bar we measure against throughout. It is a genuinely good rule: a building whose tenants have been calling recently is likely to keep having trouble. Most earlier published work on this problem never measured against it. B1 is roughly what earlier approaches amounted to. B3 shows that violations alone are too sparse to rank with, which is also why the city's current Heat Sensors Program, which selects buildings mainly by violation history, struggles to find the right buildings.

---

## Part 5. How the main model was built, one iteration at a time

The main model is a gradient boosted decision tree model. A **decision tree** splits buildings into groups by asking a series of yes or no questions about their features, such as "were there more than three complaints in the last 14 days?" **Gradient boosting** builds hundreds of small trees one after another, with each new tree correcting the errors of the trees before it. Gradient boosted trees are the most consistently accurate method for tabular data of this kind, and every credible earlier effort on this problem used the same family. We used XGBoost, a widely used gradient boosting library, alongside scikit-learn's HistGradientBoosting, a second implementation of the same idea.

The table below shows how precision at 100 (exact 48 hours, averaged over the 71 test cold days) improved as we added features. Each iteration is described after the table.

| Iteration | What changed | Precision at 100, 48 hours | Precision at 100, within 30 days |
|---|---|---|---|
| 0 | The 14 day baseline itself | 61.7% | 91.0% |
| 1 | The planned 22 features | 65.7% | not measured |
| 2 | Cold sensitivity, days since last complaint, the history cut | 67.8% | not measured |
| 3 | Whole building outage counts and the 30 day horizon | 67.7% | 96.3% |
| 4 | Landlord portfolios, boiler facts, two model ensemble, calibration | 68.7% | 96.5% |
| 5 | Short term velocity, neighbor complaints, the season clock, leak free boiler columns | 69.1% (frozen submission figure) | 96.6% |

**Iteration 1: the planned features.** We started with the 22 features from the original model plan: complaint and violation counts from the previous one and two seasons, a "chronic" flag for buildings with five or more complaints in each of the last two seasons, complaint counts in the trailing 7, 14 and 30 days, building attributes (residential units, year built, floors, floor area, whether the building was altered, community district) and the day's weather (minimum and maximum temperature, the previous day's minimum, the three day rolling minimum, the change from the previous day, snow and wind). This model reached 65.7 percent and beat every baseline at every k, but on the ten coldest days it only tied the 14 day baseline. On the coldest days the chronic buildings are obvious, and every method finds them.

**Iteration 2: cold sensitivity.** We added each building's **reaction rate by weather band**: over the previous two seasons, the share of frigid days (below 20 degrees), freezing days (20 to 31 degrees) and cold days (32 to 44 degrees) on which the building received a complaint. Some buildings only fail in deep cold, while others fail at the first chill, and these rates capture the difference. We also added the number of days since the building's last complaint and last violation, and we applied the history cut described in Part 2. Precision at 100 rose to 67.8 percent, and the rolling backtest started winning every season. Days since the last complaint became the single strongest feature.

**Iteration 3: whole building outages.** HPD records whether a complaint concerns the entire building or a single apartment. A whole building complaint usually means the boiler has failed, while an apartment complaint often does not. We added whole building complaint counts for last season and for the trailing 14 days. This iteration also introduced the within 30 days horizon. At 48 hours the number held steady at 67.7 percent, and within 30 days the model's top 100 reached 96.3 percent against the baseline's 91.0 percent.

**Iteration 4: landlords, boilers, ensemble and calibration.** We added two landlord portfolio features from HPD registrations: how many buildings the owner holds, and how many complaints the owner's other buildings received last season. Neglect often follows the owner, not just the address. We mapped 136,589 owners, of whom 11,481 hold two or more buildings, with the largest holding 246. We added two boiler features from Department of Buildings records: recorded boiler defects and whether the building burns oil. We combined XGBoost and HistGradientBoosting into an **ensemble** that averages their probabilities, and we added the isotonic calibrator. Precision at 100 reached 68.7 percent at 48 hours and 96.5 percent within 30 days.

**Iteration 5: velocity, neighbors and the season clock.** We added three features. The first counts the building's own complaints in the last 48 hours, which measures velocity. The second counts complaints on the same tax block in the last 48 hours, excluding the building itself, because buildings that share heating systems or landlords tend to fail together. The third counts the days since the season's first day with an average temperature below 55 degrees, because early cold snaps catch boilers that have not been prepared. That season clock was immediately among the four strongest features. In the same round, a careful ablation study (described next) replaced the boiler columns with leak free versions. The result is the frozen submission model.

### The ablation study: testing extra features honestly

The team's Stream 2 analysis produced several more candidate features: seven season reaction rates, a reaction rate below 25 degrees, cold sensitivity multipliers, group flags, and richer boiler data such as heavy oil grades, inspection recency, overdue flags and late filing counts. We tested each set by training five versions of the model in exactly the same way and scoring them on the same 71 days. The full run took 579 seconds on the LinuxONE machine.

We found that the original boiler defect count had a subtle leak: it counted every defect report on the lot regardless of date, so 10.1 percent of its reports came from inside the test season. Recomputing it from reports dated before each season changed precision at 100 by only 0.15 points, so the leak was contributing nothing. We adopted the honest version anyway, because honesty matters more than a number that is the same either way.

| Version (71 test cold days, ensemble) | Precision at 100, 48 hours | Precision at 100, 30 days | Paired change at 100 against the current model | Decision |
|---|---|---|---|---|
| Current model (36 features) | 69.4% | 96.8% | none | keep |
| Boiler columns recomputed before each season | 69.2% | 96.9% | minus 0.15 points | adopted, because it removes a leak at no cost |
| Plus the richer boiler set | 68.5% | 96.9% | minus 0.86 points | rejected |
| Plus seven season reaction rates and group flags | 68.9% | 96.9% | minus 0.46 points | rejected |
| Both additions together (51 features) | 69.6% | 97.1% | plus 0.25 points | rejected, because 15 extra columns for a quarter point is not worth it |

Two identical trainings of this ensemble differ by about 0.3 points at k equal to 100, so only the richer boiler set's drop is larger than the noise. No feature set in this study moved precision at 100 by more than one point in either direction. The model's remaining errors are about timing, not missing information.

### A note on the feature count

Some older project documents describe the model as using 31 features. The feature list in the code (`model/common.py`) contains 36 entries, and the ablation study above also reports 36. The difference comes from features added in iterations 4 and 5 after the earlier documents were written. This report uses the correct count of 36.

---

## Part 6. The submission model and its scores

### M1: the cold day ranker

M1 is the model whose numbers we submitted. It is frozen, which means its numbers are never changed, even when a later model does better. Later models get new names and their own entries.

- **It predicts** the probability that a building has two or more heat complaints within the next 48 hours, for one building on the eve of a freezing day.
- **It is** an ensemble of XGBoost 3.4.1 and scikit-learn HistGradientBoosting, each with 400 trees of depth 6 and a learning rate of 0.08, with their probabilities averaged.
- **It was trained on** 622,362 panel rows from the 2018 through 2024 seasons.
- **Its strongest features** are the days since the last complaint, the complaint count over the last two seasons, the trailing 30 day complaint count and the season clock.

### The headline numbers: the honest ladder at k equal to 100

| Step | What counts as a success | Precision at 100 |
|---|---|---|
| 1 | The building fails within exactly 48 hours of the ranking day (average of 71 cold days) | **69.1%** |
| 2 | The building fails at any point during the cold spell (average of 8 spells) | **86.1%** |
| 3 | The building fails within 30 days | **96.6%** |
| 4 | Ranked once at the first cold spell, the building fails at some point that winter | **99%** |

Read in plain words: of the 100 buildings M1 ranks highest on the eve of a cold day, about 69 lose heat within two days, about 86 lose heat during the cold spell, about 97 lose heat within a month, and when the list is made before winter starts, 99 of the top 100 lose heat at some point that winter.

### Daily scores at every k

The table below gives the daily scores (averaged over the 71 cold days) at both horizons, against the 14 day baseline. The k equal to 100 row shows the frozen submission figures. The other rows come from the most recent run that recorded a full table at every k, the iteration 3 model on the LinuxONE machine. Later iterations changed the deeper rows by only a few tenths of a point, as the ablation table above shows for k equal to 500 and 2,500.

| k | Model, 48 hours | Model, 30 days | Baseline, 48 hours | Baseline, 30 days |
|---|---|---|---|---|
| 100 | 69.1% | 96.6% | 61.7% | 91.0% |
| 500 | 41.7% | 86.1% | 39.3% | 80.3% |
| 1,000 | 30.6% | 77.0% | 28.5% | 71.7% |
| 2,500 | 17.9% (recall 65.3%) | 60.9% | 16.9% | 55.5% |

Training involves randomness, so repeated runs of the final model landed between 68.7 and 69.4 percent at k equal to 100. All of these values sit inside the confidence interval reported in Part 7, and the frozen citation is 69.1 percent.

The model also beats the baseline on the buildings the baseline cannot see. If we look only at the model's top 100 picks that the 14 day baseline did not pick, 58.5 percent of them fail within 48 hours and 95.6 percent fail within 30 days. These are buildings with no recent complaints that the model still correctly identified.

### Spell scores at every k

| k | During the spell | Within 30 days | Rest of the season | Baseline, during the spell |
|---|---|---|---|---|
| 100 | **86.1%** | 96.1% | 98.2% | 77.1% |
| 500 | **64.6%** | 87.8% | 92.9% | 59.9% |
| 1,000 | **51.4%** | 79.4% | 88.1% | 47.8% |
| 2,500 | **34.8%** (recall 53.9%) | 63.5% | 76.8% | 31.9% |

### The preseason watchlist

When the model ranks buildings once at the season's first cold spell, the share of its top k that fail at some point that winter is 99 percent at 100, 97.6 percent at 500, 95.4 percent at 1,000 and 87.3 percent at 2,500. For comparison, the city's Heat Sensors Program covers about 50 buildings a year. This list names a thousand buildings before winter starts, with 95 percent of them going on to fail.

### What the "misses" actually are

We examined every spell's top 100 by hand to understand the buildings that did not count as successes. Between 70 and 86 of each top 100 failed within the first 48 hours, between 72 and 96 failed during the spell, and between 93 and 99 failed within 30 days. Of the remainder, between 5 and 11 per list logged a single complaint, which means one household was cold but the building did not reach our two complaint bar. Buildings with no failure at all within 30 days numbered only 1 to 7 per 100. In other words, the model's choice of buildings is right more than 95 percent of the time. The strict 48 hour number is lower mainly because the timing of tenant calls is unpredictable.

### Panel scores, and why we do not headline them

On the training panel, M1 reaches an area under the precision recall curve of 0.981. This number is not comparable to anything a city would experience, because the panel contains two non failures for every failure, while real life contains about thirty non failures for every failure. We report it only for completeness. All the headline numbers above come from ranking every eligible building in the city.

---

## Part 7. How we checked that the scores are real

### Six winters, not one: forward chaining cross validation

One good winter could be luck. So we repeated the whole exercise six times. For each winter from 2020 to 2021 through 2025 to 2026, we trained the model only on the seasons before that winter, tested it on that winter, and moved forward. This is called **forward chaining cross validation**. Ordinary cross validation would mix past and future and is invalid for data ordered in time. Every fold used the same features and the same settings, with no fold specific tuning. The scores below are precision at 100 on each winter's ten coldest days.

| Test winter | Model | 14 day baseline |
|---|---|---|
| 2020 to 2021 | **55.8%** | 54.0% |
| 2021 to 2022 | **65.0%** | 62.9% |
| 2022 to 2023 | **66.5%** | 60.4% |
| 2023 to 2024 | **69.1%** | 64.4% |
| 2024 to 2025 | **74.4%** | 68.5% |
| 2025 to 2026 | **72.8%** | 70.3% |
| Average | **67.3%** | 63.4% |

The model won six winters out of six.

### Statistical significance (task T7)

- **Daily scores.** The model beat the 14 day baseline on 67 of the 71 test cold days at k equal to 100, tied on 1 and lost on 3, with an average edge of 7.7 percentage points. In 100,000 random sign flips, chance never produced an edge this large, so the p-value is about 0.00001 at every k and at both horizons. The 95 percent confidence interval for precision at 100 at 48 hours is 68 to 71 percent.
- **Correlated days.** Days within one cold snap are not independent, so we also resampled the 16 blocks of consecutive cold days instead of single days. The interval widens to 66 to 71 percent, but even its lower end is above the baseline's score.
- **Spells.** The model beat the baseline in all eight spells at every k, which gives the smallest possible p-value of 1 in 256. The 95 percent interval for spell precision at 100 is 81 to 92 percent. With only eight spells the interval is honestly wide.
- **Calibration.** For the season risk model, every one of the eight probability groups had its prediction inside the Wilson interval of the observed rate. Statistically, the probabilities cannot be told apart from the truth at any level.

### Whole list measures for the final per spell model (M13)

These grade the whole ranked list of roughly 62,000 buildings, using the frozen M13 scores on the eight held out spells.

| Top share of the list | Approximate number of buildings | Share of all spell failures captured |
|---|---|---|
| 0.1% | 62 | 4.3% |
| 0.5% | 309 | 16.5% |
| 1% | 618 | 25.7% |
| 2% | 1,237 | 38.3% |
| 5% | 3,092 | 59.2% |
| 10% | 6,183 | 75.3% |

Random inspection would capture 1 percent of failures in the top 1 percent, so the model's top 1 percent is about 26 times better than random, and its top 10 percent is about 7.5 times better. The average PR-AUC is 0.434 against an average base rate of 3.1 percent, about 14 times the no skill level. It ranges from 0.337 on the mild February 12 spell, where only 1.1 percent of buildings failed, to 0.574 on the severe January 23 spell, where 9.9 percent failed. Recall averages 6.8 percent at 100, 22.6 percent at 500, 33.9 percent at 1,000 and 54.3 percent at 2,500, against an average of about 1,910 failures per spell. The Brier score is 0.0235, compared with 0.0293 for climatology, which is about 20 percent better. That Brier comparison is slightly optimistic, because the calibrator for it was fit on validation spells that the model had also seen during its final refit.

---

## Part 8. The supporting models that make the product work

### M2: the deployment twin

M2 uses exactly the same recipe as M1 but is trained on all eight seasons, including 2025 to 2026. It is the model you would actually deploy this winter. Because it has seen the test winter, it is never used for any reported score. It produces the website's ranked inspection list of 67,125 buildings (`model/out/ranked_inspection_list.csv`), scored under the replayed weather of February 8, 2026.

### M3: the daily calibrator

M3 is the isotonic calibrator that turns M1's raw scores into honest 48 hour probabilities. It is fit on 142,000 pairs of score and outcome, sampled as 2,000 random buildings on each of the 71 test days. These pairs come from the whole universe of buildings, not the panel, because the panel's inflated failure rate would make displayed probabilities about 60 times too high. We tested it on nine different splits (random, by day, and from mild to coldest days), and the predicted and observed rates matched in every group. Below 20 percent the match is within about one percentage point everywhere. On the current website, the top ranked building has a calibrated 48 hour probability of 81.2 percent.

### M4: the season risk model

M4 answers the question a tenant cares about: what is the chance that this building loses heat at least once this winter? It has one row per building per season, with features as of October 1. It uses 21 features, which are M1's features minus the short term counts and the weather, since neither exists at the start of the season. It is a HistGradientBoosting model with 400 iterations and depth 6, trained on 305,413 building seasons from 2018 through 2024, of which 18.5 percent failed. It has its own isotonic calibrator, fit on half of the held out winter and checked on the other half.

Its reliability table on the held out winter is shown below. In every group, the predicted rate and the actual rate are within a few percentage points.

| Predicted probability group | Buildings | Average prediction | Actually failed |
|---|---|---|---|
| 0% to 5% | 12,868 | 2.6% | 2.4% |
| 5% to 10% | 3,045 | 7.0% | 7.7% |
| 10% to 20% | 4,510 | 13.7% | 12.8% |
| 20% to 35% | 2,803 | 25.7% | 24.9% |
| 35% to 50% | 3,267 | 42.1% | 40.7% |
| 50% to 65% | 551 | 60.3% | 56.6% |
| 65% to 80% | 1,462 | 71.7% | 69.4% |
| 80% to 100% | 1,362 | 91.1% | 91.3% |

For the 2026 to 2027 winter, M4 rates about 3,300 to 3,700 buildings at 80 percent or higher, about 8,000 to 8,900 at 50 percent or higher, and the median building at about 8 percent. Its output is `model/out/season_risk_2026.csv`, which covers 63,727 buildings.

### M5: the Snap ML twin for the IBM benchmark

M5 is an IBM Snap ML gradient boosting model with 200 rounds and depth 6, trained directly on the LinuxONE machine on M1's panel. Its purpose is to measure speed, not accuracy. Snap ML could not load XGBoost's model file, and its tree builder rejects missing values, so missing values were replaced with minus one before training. Its measured speed is in Part 10.

### M6: the backtest fleet

M6 is the set of six models used in the forward chaining cross validation in Part 7, one per test winter, each trained only on earlier seasons. They exist only for validation and were discarded after scoring.

---

## Part 9. Every experiment we ran after the submission model, and what happened

After freezing M1, we kept testing new ideas. Each idea got a new model name and was judged under the same frozen protocol. The rule for adoption was simple: a new model must beat the frozen model meaningfully and consistently, with all choices made on the validation winter. Most ideas did not pass, and we report those as carefully as the ones that did.

### Summary table

| Name | Idea | Main result | Decision |
|---|---|---|---|
| M7 | Train the model to rank directly | Better at the very top, worse deeper in the list | Not adopted |
| M8 | Train on inspector confirmed violations | About twice as good as the best baseline at finding confirmed violations | Kept as a second product |
| M9 | A graph neural network trained on the IBM machine | One to two points below M1 at every k | Not adopted |
| M11 | Train directly on the spell level task | 89.9% during the spell at 100, a gain of 3.8 points | Adopted, then superseded by M13 |
| M12 | A careful hyperparameter search | 89.2% at 100, ties or gains at every k | Adopted as the tuned daily configuration |
| M13 | Tuned spell model, averaged over five seeds | 90.1% at 100, the final per spell scorer | Adopted and frozen |
| T12 | A simulation of real inspection dispatch | 7.8% more violations confirmed and 50.2% fewer cold household days than first come first served | The policy result |
| T8 | Alert thresholds with a mathematical guarantee | The guarantee held on the test winter | Adopted |
| M10 and M10b | Predict when a building will first fail | Good ordering, but not calibrated well enough to show | Not shipped |
| M14 | Use complaint categories and per unit rates | A tie with the control | Not adopted |
| Watchlist v2 | Add year over year trend features to M4 | A tie with M4 | Not adopted |
| M16 | Remove features one by one, across three model types | 8 features match all 36 (90.0% against 89.5% at 100) | A simpler equal model; tuning it is the next step |

All the spell level comparisons below use the same eight held out spells of the 2025 to 2026 winter and report precision at 100, 500, 1,000 and 2,500 during the spell. For reference, frozen M1 scores 86.1, 64.6, 51.4 and 34.8 percent on this protocol, and the 14 day baseline scores 77.1, 59.9, 47.8 and 31.9 percent.

### M7: learning to rank (not adopted)

M1 is trained to predict each building's probability independently. A **learning to rank** model is instead trained to put buildings in the right order relative to each other on the same day. We trained an XGBoost ranking model with the same 36 features, the same data split and the same budget, with no extra tuning (`model/11_ranker.py`).

| | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|
| M7 ranking model | 87.9% | 64.6% | 50.7% | 33.7% |
| M1 frozen | 86.1% | 64.6% | 51.4% | 34.8% |

M7 is sharper at the very top, gaining 1.8 points at 100, and 97.4 percent of its top 100 failed within 30 days. But it is worse deeper in the list, which is where a citywide operation works, and its outputs are not probabilities, so they would need new calibration before display. We did not adopt it.

### M8: the enforcement ranker (kept as a second product)

M8 uses M1's recipe but is trained on the verified label: an inspector confirmed heat violation within seven days (`model/12_verified_model.py`). It answers a different question: which buildings will produce a confirmed violation? Scored on the 71 test cold days with confirmed violations as the truth, M8's precision at 100 is **30.2 percent**, against 16.5 percent for the best baseline (last season's violations) and 14.8 percent for the 14 day baseline. That is about twice the best simple rule. Of its top 100, 48.0 percent produce a confirmed violation within 30 days. The absolute numbers are low because inspection capacity limits confirmation, as explained in Part 1: even buildings that certainly failed are confirmed within seven days only 9 to 12 percent of the time. Against that ceiling, 30 confirmed in 100 is about 43 times better than random. We keep M8 as a second queue beside M1: M1 serves tenant protection and M8 serves enforcement targeting.

### M9: a graph neural network trained on LinuxONE (not adopted)

Buildings are connected. They share landlords and they sit on the same blocks. A **graph neural network** can learn from these connections directly. We built a graph of about 63,000 buildings linked through one hub node per multi building landlord and one per tax block, created 54 snapshots (one per cold spell, with the same features and the same time rules), and trained a two layer GraphSAGE network in PyTorch on the LinuxONE machine itself (`model/13_build_graph_dataset.py` and `model/14_graph_train.py`).

| | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|
| M9 graph network | 84.9% | 63.0% | 49.4% | 33.8% |
| M1 frozen | 86.1% | 64.6% | 51.4% | 34.8% |

M9 came in one to two points below M1 at every k. The reason is instructive. The two useful relationships in the graph, landlord portfolios and block contagion, were already built into M1 as explicit features (the landlord's other buildings' complaints and the same block complaints in the last 48 hours). The graph network could only smooth that information, not add to it. It remains our measured answer to "why not deep learning?": we tried it, on IBM Z, under the same rules, and the simpler model held.

### M11: train on the task you are graded on (adopted, then superseded)

M1 learns from daily 48 hour labels, but the operational score is per spell. M11 uses the same algorithm and the same features, but is trained directly on the spell level task: the 54 spell snapshots, with the label "fails during the spell." It was trained on seasons 2018 through 2023, the number of trees was chosen on the 2024 to 2025 spells, it was refit including 2024 to 2025, and it was tested once (`model/21_spell_direct.py`).

| | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|
| M11 spell model | 89.9% | 64.8% | 51.3% | 34.9% |
| M1 frozen | 86.1% | 64.6% | 51.4% | 34.8% |

M11 gained 3.8 points at the top with no loss deeper in the list. We checked that this was real. Three retrains with different seeds scored 88.0, 89.2 and 89.9 percent, so we quote "about 88 to 90 percent," not the best draw. M11 beat M1 in 7 of 8 spells, with an exact p-value of 0.0078, and its single loss was by one building on the mildest spell. The lesson is the clearest of the whole project: after five rounds of features and four alternative architectures, the largest late gain came from training the model on the exact task it is scored on.

### M12: a careful hyperparameter search (adopted as the tuned daily model)

M12 is M1's daily model with its settings chosen by a 20 trial random search, where every trial was scored on the validation winter only (`model/22_hpo.py`). The winner is shallower and more cautious than the hand chosen settings: depth 4, 800 trees, learning rate 0.05 and a minimum of 20 examples per leaf. It scored **89.2, 65.2, 51.8 and 34.8 percent**, which ties or beats M1 at every k. Its validation score (89.6 percent) and test score (89.2 percent) were close, which shows the search did not overfit to the validation winter.

### M13: the final per spell scorer (adopted and frozen)

M13 was the last hour of model work, with every choice made on the validation winter (`model/24_final_squeeze.py`). It ran a 12 trial search on the spell task (the winner used depth 7, a learning rate of 0.03 and 61 trees, with stronger regularization), trained that winner with five different seeds and averaged them to remove seed noise, and tested a blend with M12. The blend search chose the pure five seed average, so M12 added nothing on top.

| | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|
| **M13 final** | **90.1%** | **65.4%** | 51.4% | **35.2%** |
| M1 frozen | 86.1% | 64.6% | 51.4% | 34.8% |

M13 ties or improves every k, with a gain of 4.0 points at the top. We estimate the realistic ceiling with this label at about 92 to 94 percent at 100, because on mild spells few buildings truly fail and every model scores between 75 and 79 percent there. The remaining gap to that ceiling is mostly that mild spell floor. After M13, the model stream was frozen for the submission. M13 powers the per spell inspection list, and M1 remains the cited submission model.

### T12: what ranking buys a city, measured by simulation

A better list only matters if it changes what inspectors do. We replayed the real 2025 to 2026 complaint stream, 183,384 building day cases, day by day, under a fixed inspection capacity of 700 inspections per day, and compared three ways of choosing which cases to inspect: first come first served (the status quo), last season's complaint count, and HeatAhead's M13 ranking (`sim/run.py`). The chance that an inspection confirms a violation came from the team's measured confirmation rates, never from our own model, to avoid circular reasoning. The simulation was calibrated so that first come first served reproduces reality on both the season total of 10,886 violations and the measured waiting time of about three days.

| Policy | Violations confirmed | Median wait | Average wait for failing buildings | Cold household days |
|---|---|---|---|---|
| First come first served | 10,886 | 2 days | 3.12 days | 13,780,436 |
| Last season's count | 11,522 | 0 days | 2.10 days | 7,052,143 |
| **HeatAhead (M13)** | **11,730, give or take 201** | **0 days** | **2.03 days** | **6,861,709** |

With the same inspectors in the same winter, HeatAhead confirms 7.8 percent more violations, reaches failing buildings in 2.0 days instead of 3.1, and cuts **cold household days** by 50.2 percent. A cold household day is one household in a failing building waiting one day without heat. The cost is that prioritizing leaves about 24,000 low priority cases uninspected within the 14 day window, of which 5,546 were failing buildings. Their cold days are charged in full, so the 50.2 percent reduction already includes that cost. Across nine combinations of capacity (600, 700 and 800 per day) and case expiry (7, 14 and 28 days), HeatAhead beat first come first served in every one: between 5.9 and 10.2 percent more violations and between 27.6 and 65.1 percent fewer cold household days. The simulation assumes a late inspection is as likely to confirm a violation as a prompt one. In reality, heat often returns before a late visit, which would hurt slow policies more, so our numbers are a conservative floor.

### T8: alert thresholds with a mathematical guarantee (adopted)

The email alerts originally used a hand picked threshold. We replaced it with a threshold chosen by **conformal risk control**, a statistical method that guarantees, without assuming anything about the shape of the data, that the expected share of failures the alerts miss stays at or below a chosen level called alpha (`model/16_conformal.py`). The guarantee holds as long as future days behave like the calibration days, which is the only assumption the method makes.

We trained one model on the 2018 through 2022 seasons, scored every eligible building on all 102 cold days of the 2023 to 2024 and 2024 to 2025 seasons to choose the thresholds, and then checked them once on the 71 held out cold days of 2025 to 2026.

| Alert tier | Guaranteed maximum miss rate | Miss rate on the calibration days | Miss rate on the held out winter | Buildings alerted per cold day (average and median) |
|---|---|---|---|---|
| Broad | 10% | 9.1% | **7.4%** | 13,107 and 12,132 |
| Strict | 25% | 24.3% | **21.1%** | 5,220 and 4,740 |

The guarantee held on both tiers. The alert volume is the price of the guarantee: catching at least 90 percent of failures means alerting about 13,000 buildings on each cold day, roughly a fifth of all eligible buildings. That is why the guarantee powers the alert emails, which now state that the alert level "is calibrated to miss fewer than" the chosen share of failures, while inspections still follow the short ranked list.

### M10 and M10b: predicting when a building will first fail (not shipped)

Every other model predicts whether a building fails. M10 predicts when. It is a **discrete time hazard model**: for each building on each day, it predicts the chance that the building has its first failure of the season on that day, given that it has not failed yet. Multiplying the daily chances of not failing across the season gives a **survival curve**, the probability that the building is still without a failure by any date, from which we can say things like "a 50 percent chance of a first failure by January 20."

M10 was trained with XGBoost on 1.94 million building day rows from the 2018 through 2023 seasons, containing 46,423 first failures (`model/18_hazard.py`). To keep training manageable, it used every seventh day for buildings that had not yet failed and a 20 percent sample of buildings that never failed, and it weighted those rows back up so the totals stayed correct. Its daily chances were calibrated on the 2024 to 2025 season, and it was tested once on 2025 to 2026, using observed weather.

**Ordering is good.** The C-index is **0.871** over 450,808 comparable pairs, so the model does know which buildings will fail earlier.

**The probabilities were not good enough.** In eight of the ten risk groups, the predicted share of buildings that would have failed by each date was within about 4 percentage points of the truth. In the two highest risk groups, the model was badly overconfident.

| Date | Share of all buildings that had failed | Second highest group, predicted and actual | Highest group, predicted and actual |
|---|---|---|---|
| By December 1 | 8.3% | 28.1% predicted, 19.6% actual | 58.2% predicted, 24.8% actual |
| By January 1 | 12.2% | 41.2% predicted, 27.3% actual | 72.6% predicted, 30.9% actual |
| By February 1 | 16.6% | 51.0% predicted, 34.4% actual | 80.7% predicted, 40.3% actual |

The cause is that small overestimates in the daily chances multiply over about 240 days into large errors in the cumulative curve, and calibrating each day separately cannot see that compounding. For the top 1,000 buildings, the typical error in the predicted failure week was 11.1 weeks, far from the target of about 2 weeks.

**M10b** added a second calibration step that maps the cumulative predicted risk at each date to the realized share, fit on the full 2024 to 2025 curves (`model/19_hazard_recal.py`).

| Date | Largest gap in any risk group | Highest group, predicted and actual |
|---|---|---|
| By December 1 | 8.0 points | 32.9% predicted, 24.9% actual |
| By January 1 | 3.8 points | 34.8% predicted, 31.0% actual |
| By February 1 | 4.7 points | 35.4% predicted, 40.1% actual |

The overestimate of 8 to 42 points collapsed to under 5 points in January and February, but December 1 still misses by 8 points, and the failure week error only improved to 10.0 weeks. The C-index stayed at 0.869. Because the website may only show calibrated probabilities, and a timing chart that is right in February but wrong in December fails that rule, neither M10 nor M10b is shown on the site. The held out winter has now been used twice for this model family, so further adjustment would amount to fitting the test winter, and we stopped here.

### M14: complaint categories and per unit rates (not adopted)

Task T20 asked whether the text of the complaints carries information about severity that the counts miss. We first checked what text exists. The complaint file contains **no free text at all**. It has two category fields (whether the complaint concerns the entire building or one apartment, and whether it is about heat, hot water or both) and two intake flags (anonymous and duplicate), and these four fields are filled in for every complaint. So there was nothing for a language model to read, and we tested the categories instead (`model/narrative.py` and `model/20_narrative.py`).

The original pipeline discards complaints about hot water alone, more than 350,000 of them, so no model had ever seen them. Between 10,000 and 14,000 buildings per season file such complaints, and they could signal a struggling boiler. We built three variants on the M11 spell setup. M14a adds seven category features: last season's hot water only complaints, last season's shares of heat plus hot water, anonymous and duplicate complaints, the number of distinct apartments that complained last season (counted once at load time and then discarded, so no apartment value is kept), and this season's hot water complaints and distinct complaining apartments up to the evening before the spell. M14c adds three per unit rates: complaints per 100 units last season and in the last 14 days, and the share of units that complained. M14ac adds both. Each was trained three times with different seeds, alongside an identically trained control with only the standard features, and the winner was chosen on the validation winter.

| Variant | Validation, at 100 | Test, at 100 | Test, at 500 | Test, at 1,000 | Test, at 2,500 |
|---|---|---|---|---|---|
| Control (standard features) | 87.8% | 89.0% | 64.8% | 51.1% | 34.9% |
| **M14a, chosen on validation** | **88.7%** | 89.0% | 65.0% | 51.1% | 35.0% |
| M14c | 86.8% | 88.9% | 64.6% | 51.1% | 34.9% |
| M14ac | 88.2% | 89.1% | 64.6% | 51.1% | 35.0% |

M14a tied the control on the held out winter. It won 4 spells and lost 4, with an average change of minus 0.1 points. In a six winter backtest it was ahead in five winters, but by at most 2.2 points, and a sign test gives a p-value of about 0.11, which is not convincing given that the control's own seed to seed spread is 88.0 to 89.9 percent. We did not adopt it. The categories mostly restate what the whole building complaint counts already carry. The per unit rates did not change the ranking either, so the fact that very large complexes rank highly needs a fix in how the website presents them, not in the model.

### Watchlist v2: trend features for the season model (not adopted)

A separate experiment (`model/27_watchlist_v2.py`, which exists on the LinuxONE machine and has not yet been added to the repository) asked whether M4's season risk forecast improves with trend features: whether a building's complaints were rising or falling between seasons, whether its violations were rising, and the same trends across its landlord's other buildings. The script labels this model "M15." Selection was done on the 2024 to 2025 season and the 2025 to 2026 season was used once.

| Model | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|
| M4 season model | 100% | 98.0% | 96.7% | 92.0% |
| Watchlist v2 with trends | 100% | 97.8% | 96.5% | 92.3% |
| Last season's complaints | 97% | 95.8% | 94.6% | 89.0% |
| Failed last season | 97% | 95.8% | 94.6% | 89.0% |
| Last season's violations | 80% | 71.4% | 69.2% | 60.4% |

Here success means the building fails at least once during the winter, which 19.5 percent of the 59,687 eligible buildings did. The two models are effectively tied, and the forward chaining checks across 2020 through 2024 show the same picture. Both are well calibrated, with Brier scores of 0.0958 for M4 and 0.0955 for the trend version. The trend features add nothing meaningful, so M4 remains the season model.

### M16: removing features one at a time, across three model types (finished; a smaller model matches the full one)

Every model before this one used all 36 features. This experiment asks whether some of them add only noise, and whether a smaller model would do as well or better (`model/28_feature_rfe.py`). It was started under the name M15 and renamed M16, because the name M15 was already used by the watchlist experiment above.

**The method.** The experiment uses the M11 spell setup. For each of three model types it starts with all 36 features and repeats the following step until one feature is left. It trains the model on the 2018 through 2023 spells. It measures each feature's importance on the 2024 to 2025 validation spells by **permutation**: it shuffles that one feature among the buildings within each spell and measures how much the ranking gets worse, by the average per spell PR-AUC. It then removes the least important feature. Shuffling within each spell is the right test for a ranking task. A feature that is identical for every building in a spell, such as the day's temperature, cannot change the order of buildings within that spell, so it correctly scores zero.

The three model types are:

1. **Logistic regression**, a simple linear model that adds up weighted features. It cannot learn interactions between features, so it is a genuinely different kind of model.
2. **HistGradientBoosting**, scikit-learn's gradient boosted trees.
3. **XGBoost**, the same algorithm as M11 and M13.

The two tree models were trained with two seeds at every step. The rule for choosing each type's final feature set was fixed before any test score was seen: take the smallest feature set whose validation score (precision at 100 plus precision at 2,500) is within 0.005 of that type's best validation score. Each chosen set and the full 36 feature version were then retrained three times on 2018 through 2024 and tested once on the eight held out spells. All of the training and testing ran on the LinuxONE machine.

One limit of the method should be stated plainly. Removing one feature at a time does not try every combination of features. When two features carry nearly the same information, such as the 14 day and 30 day complaint counts, shuffling one while the other is still present can make it look unimportant. Removing features one at a time reduces this problem, because once one of the pair is gone the other's importance rises, but it does not remove it entirely.

**Which features each model type kept.**

| Model type | Features kept | The features |
|---|---|---|
| Logistic regression | 5 | Complaints over the last two seasons, complaints in the last 14 and 30 days, days since the last complaint, floor area |
| HistGradientBoosting | 9 | The same five, plus last season's complaints, complaints in the last 7 days, the freezing day reaction rate and the number of residential units |
| XGBoost | 8 | The same five, plus complaints in the last 2 and 7 days and the freezing day reaction rate |

All three model types kept the same five core features. The two tree models also kept short term complaint counts and how often the building complained on freezing days. None of the three kept any weather feature, any boiler or landlord feature, the same block neighbor count, the violation counts, the whole building outage counts, the year built or the community district. Every one of the eight weather features was removed with an importance of exactly zero.

**The test results on the eight held out spells (average of three seeds).**

| Model | Features | At 100 | At 500 | At 1,000 | At 2,500 |
|---|---|---|---|---|---|
| XGBoost, full | 36 | 89.5% | 64.8% | 51.3% | 34.9% |
| **XGBoost, chosen** | **8** | **90.0%** | **65.2%** | **51.6%** | **35.0%** |
| HistGradientBoosting, full | 36 | 89.3% | 64.8% | 51.3% | 35.0% |
| HistGradientBoosting, chosen | 9 | 89.1% | 65.1% | 51.6% | 35.0% |
| Logistic regression, full | 36 | 87.4% | 63.4% | 50.3% | 34.6% |
| Logistic regression, chosen | 5 | 85.9% | 62.8% | 49.8% | 34.5% |
| M13, frozen and tuned (reference) | 36 | 90.1% | 65.4% | 51.4% | 35.2% |

**What the results mean.**

- **The 8 feature XGBoost model is at least as good as the 36 feature version.** It scored 0.5 points higher at 100, and it was equal or higher at every other k. Spell by spell it won 3, lost 3 and tied 2 at 100, so the gain is not statistically clear, but all three of its seeds (89.5, 90.0 and 90.5 percent) landed at or above the full model's average. The honest summary is that removing 28 of the 36 features cost nothing.
- **The 9 feature HistGradientBoosting model tied its full version.** It was 0.2 points lower at 100 and slightly higher at 500 and 1,000, which is inside the noise.
- **Logistic regression lost 1.5 points with only 5 features.** A linear model cannot combine features the way trees do, so it needs more of them. Its smaller set is not a good trade.
- **The comparison with M13 is not a fair contest yet.** M13 had its settings tuned by a 12 trial search and averages five seeds. The 8 feature XGBoost model used untuned settings and was averaged over three seeds, and it still landed within 0.1 points of M13 at 100 and above it at 1,000. The fair next step is to give the 8 feature set exactly M13's treatment (the same tuning search run on the validation winter, then five seeds) and test it once against M13.

**Why this matters even though the top number barely moved.** A model with 8 inputs instead of 36 is easier to explain to a city agency, faster to compute, and depends on far fewer data sources. All 8 of its inputs come from the public HPD complaint file, apart from floor area, which comes from PLUTO. It no longer needs the owner registration file, the two boiler data sets, the violation file or the weather feed to rank buildings within a cold spell. Fewer data sources also means fewer ways for a stale table or a leak to creep in. The weather is still essential to the product, because it decides **when** a cold spell is coming and therefore when to rank, but it does not help decide **which** building is at risk once the spell is known.

The results are saved in `model/out/m16_results.csv` (one row per model and feature set), `model/out/m16_per_spell.csv` (every spell and seed) and `model/out/m16_rfe_<model type>.csv` (the full elimination path for each model type).

---

## Part 10. Where the models run: the IBM LinuxONE machine

All training and scoring for this project runs on the team's IBM LinuxONE guest, a virtual machine on an IBM z17 mainframe. The machine uses the s390x processor architecture and has 3 processor cores and 8 GB of memory. Python runs inside IBM's provided container with XGBoost 3.4.1, scikit-learn 1.9.0, NumPy 2.0.2 and pandas 3.0.6. Models move between machines only as JSON files, never as Python pickle files, because the mainframe stores numbers in a different byte order (big endian) from ordinary laptops (little endian), and a pickle made on one can fail to load on the other.

### Scoring speed

Scoring the whole city is fast, because scoring is the strength of this hardware.

| Engine | Batch scoring (whole city of 172,485 buildings) | p99 single building latency |
|---|---|---|
| XGBoost 3.4.1 | 358,629 buildings per second | 0.71 milliseconds |
| **IBM Snap ML (M5)** | **481,356 buildings per second (1.34 times XGBoost)** | 0.51 milliseconds |

The entire city can be re-ranked in under half a second. The machine also has the Telum chip's on chip AI accelerator (listed as "nnpa" by the operating system). The Snap ML speed above comes from its processor based tree engine, and we do not claim that our models currently use the accelerator. Task T22 is the plan to change that.

### Other measured hardware features

Measured on the real 361 MB complaint file: the z17's on chip compression runs at 2,077 MB per second against 33 MB per second with the hardware turned off, which is 63 times faster. AES-256 encryption through the CPU's cryptographic instructions runs at 728 MB per second against 106 MB per second without them. All 2.2 million apartment identifiers were replaced with secure one way codes (HMAC-SHA256) in 5.85 seconds before any table was built, so nothing below building level exists outside the raw data folder.

### Why training takes hours

Training is slower than scoring because the guest has only 3 cores, which is roughly the processing power of a mid range laptop and a small slice of a full z17. During the M16 experiment, the machine ran at about 270 percent of a possible 300 percent processor use, with plenty of memory free, so the hardware is fully used. The time comes from the amount of work: each elimination step trains two models on about 2 million rows and then rescores the validation spells hundreds of times to measure importance, and the steps must run one after another.

---

## Part 11. What we use today, and what we decided not to use

| Model | Status | Where it is used |
|---|---|---|
| M1 | Frozen submission model | The cited numbers: 69.1, 86.1, 96.6 and 99 percent at 100, six of six winters won |
| M2 | Deployed | Produces the website's ranked inspection list |
| M3 | Deployed | Turns raw scores into the probabilities on the website |
| M4 | Deployed | The "chance of losing heat this winter" number on each building's page |
| M5 | Benchmark | The IBM Z speed figure of 481,356 buildings per second |
| M6 | Validation only | The six winter cross validation |
| M7 | Not adopted | Documented as the answer to "did you try learning to rank?" |
| M8 | Kept as a second product | The enforcement queue for confirmed violations |
| M9 | Not adopted | Documented as the answer to "did you try deep learning?" |
| M10 and M10b | Not shipped | Timing ordering works, probabilities not calibrated well enough |
| M11 | Superseded by M13 | The lesson about training on the graded task |
| M12 | Adopted | The tuned configuration for daily models built after the freeze |
| M13 | Adopted and frozen | The per spell inspection list and the dispatch simulation |
| M14 | Not adopted | Complaint categories tie the control |
| Watchlist v2 | Not adopted | Trend features tie M4 |
| M16 | Finished, not yet adopted | An 8 feature model matches the full model; to be tuned and compared with M13 |
| T8 thresholds | Adopted | The alert email thresholds and their guarantee |

Across all of these experiments a consistent picture emerged. The strongest signal is a building's own recent and past complaint history. Hand built features that capture landlords, neighbors and whole building outages already carry what graph networks and complaint categories could offer. The one change that produced a large gain was training the model on exactly the task it is scored on.

---

## Part 12. Honest limitations

- **The label measures complaints, not boilers.** Our failure label is "tenants called 311 at least twice within 48 hours," not "the boiler stopped." Some buildings under report and some over report. The verified label and the M8 model are our check on this.
- **Backtests use observed weather.** In testing, we used the actual recorded temperatures in place of a forecast. We measured archived 24 to 48 hour forecasts at about 2 degrees Fahrenheit of error, so live performance should be close, but it is not identical.
- **Cold spells are only visible about a week ahead.** The system is designed to act one to two days before a spell, when the forecast is reliable.
- **Buildings with no history are not ranked.** Buildings that have never had a heat complaint or violation are outside the universe. The Heat Sensors Program and physical inspections of building systems are the complement for them.
- **Some building facts are current snapshots.** The landlord tables reflect today's owners, so past seasons in the backtest inherit today's ownership. The boiler columns were fixed to use only past records, but the landlord columns still carry this caveat.
- **Very large complexes rank highly partly because of their size.** A complex with thousands of units generates many complaints. The model's ranking is still correct about who fails, but the website should present such complexes clearly as complexes.
- **The timing model is not ready.** M10 orders buildings by timing well but its probabilities are not calibrated well enough to show.

---

## Part 13. Glossary

**Baseline.** A simple rule that needs no model, used as the bar a model must beat.

**Brier score.** The average squared difference between predicted probabilities and actual outcomes. Lower is better.

**Calibration.** Whether predicted probabilities match observed frequencies. A calibrated model's 60 percent predictions come true about 60 percent of the time.

**C-index.** For pairs of buildings where one failed earlier, the share where the model gave the earlier one higher risk. 0.5 is guessing and 1.0 is perfect.

**Cold spell.** Two or more consecutive heat season days with an average temperature below 32 degrees Fahrenheit.

**Confidence interval.** A range that would contain the true value in 95 out of 100 repetitions of the experiment.

**Conformal risk control.** A statistical method for choosing a threshold that guarantees an error rate stays below a chosen level, without assumptions about the shape of the data.

**Cross validation, forward chaining.** Training on earlier periods and testing on the next one, repeatedly, so that a model is never trained on data from after its test period.

**Ensemble.** A combination of several models whose predictions are averaged.

**False negative rate.** The share of actual failures that a rule failed to flag.

**Feature.** One piece of information about a building on a day that the model uses, such as "complaints in the last 14 days."

**Gradient boosted trees.** A model made of many small decision trees built in sequence, each correcting the errors of the earlier ones.

**Heat failure.** In this project, two or more distinct heat complaints at one building within 48 hours.

**Isotonic regression.** A calibration method that maps scores to probabilities while keeping their order.

**k.** The number of buildings at the top of a ranked list that would be inspected.

**Panel.** The training table: every actual failure plus twice as many sampled non failures, one row per building per day.

**Percentage point.** The plain difference between two percentages. Moving from 30 percent to 35 percent is a change of 5 percentage points.

**Permutation importance.** How much a model's score drops when one feature's values are randomly shuffled. A feature whose shuffling changes nothing is not being used.

**Precision at k.** Of the top k buildings in the ranking, the share that actually failed.

**PR-AUC.** The area under the precision recall curve, a one number summary of ranking quality across all list lengths. It must be compared with the base rate.

**p-value.** The probability that chance alone would produce a result at least as strong as the one observed. Small values mean chance is a poor explanation.

**Recall at k.** Of all actual failures, the share that appear in the top k.

**Seed.** The starting value for a model's random choices during training. Different seeds give slightly different models.

**Test winter.** The 2025 to 2026 heating season, held out from all development and scored once.

**Validation winter.** The 2024 to 2025 heating season, used to make all choices between model versions.

**Verified failure.** An HPD inspector recorded heat violation at the building within seven days.
