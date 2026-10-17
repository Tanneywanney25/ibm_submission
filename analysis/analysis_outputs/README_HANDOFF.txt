HEATAHEAD — ANALYSIS HANDOFF

Inputs: days.csv, buildings.csv, bbl_day_counts.csv.
Coverage: all five boroughs; available weather dates through 2026-10-12.
Main comparisons use October-May and properties built before 2017.
We assume these properties remained active and covered throughout.
BBL identifies a property/lot, which can contain multiple buildings.

RATE DEFINITION
Complaint-days / eligible property-days * 100.
A property counts once per day even if it received multiple complaints.
Days and properties with zero complaints are included in denominators.
Weather bands use TMIN: Frigid <20, Freezing 20-<32, Cold 32-<45, Mild >=45 F.

ALTERATION COMPARISON
Recorded alterations count as prior starting the following calendar year.
795 properties with alteration years before construction were excluded here.
Groups also differ in age and size; comparisons are descriptive.

EXPLORATORY PATTERN RULES
Chronic: Mild complaint-day rate >=5%, across >=3 heating seasons.
Cold-concentrated: >=5 Frigid complaint-days across >=2 heating seasons,
and Frigid/Mild rate >=3, or zero recorded Mild complaint-days.
Properties can match both patterns.
A zero Mild baseline leaves the raw multiplier blank.
No recorded complaints means no qualifying reports on selected dates.

USING THE HISTORY FILES
Histories summarize data through 2026-10-12.
For predictions on earlier dates, rebuild histories using only earlier data.
Pattern labels describe reporting history and are exploratory.

KEY FILES
*_weather_heatmap.png: charts for the presentation.
group_cold_sensitivity.csv: all group rates and weather multipliers.
property_weather_history.csv: individual property histories.
property_complaint_patterns.csv: histories with pattern labels.
property_pattern_counts.csv: counts in each pattern category.
