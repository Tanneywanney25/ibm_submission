#!/bin/bash
# HeatAhead Workstream 2: run the whole pipeline on the IBM z17 LinuxONE guest.
#   ssh linux1@148.100.77.112 ; cd ~/heatahead/stream2 ; ./run_all.sh
# Needs: raw/ygpa-z7cr.csv.gz, raw/wvxf-dwi5.csv.gz, raw/days.csv, raw/buildings.csv (team Drive),
#        raw/noaa_daily_centralpark.csv, raw/weather_archived_forecast_features_2024_onward.csv (team Drive),
#        and the Open Data pulls from ./pull_open_data.sh (run it first if raw/ lacks the five *_<id>.csv files).
set -euo pipefail
cd "$(dirname "$0")"
PY=~/datathon-env/bin/python
mkdir -p logs out work
echo "machine: $(uname -m) | $(grep -m1 machine /proc/cpuinfo) | dflt=$(grep -o -w dflt /proc/cpuinfo | head -1) nnpa=$(grep -o -w nnpa /proc/cpuinfo | head -1)"
T0=$(date +%s)
for step in s2_00_stage_protect s2_01_clean s2_02_violation_tier s2_04_forecast_only s2_03_geography s2_05_boiler_join; do
  echo "=== $step  $(date +%T) ==="
  $PY $step.py 2>&1 | tee logs/${step#s2_}.log | grep -E "^\[|complete|^  [a-zA-Z]" | tail -8
done
echo "=== executed notebook ==="
$PY -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=1800 02_stream2_analysis.ipynb 2>&1 | tail -2
echo "total wall-clock: $(( $(date +%s) - T0 )) s"
