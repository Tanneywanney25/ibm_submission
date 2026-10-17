#!/bin/bash
# Pull the second-tier NYC Open Data tables straight onto the LinuxONE server with curl.
# Paging: $limit=50000 / $offset, ordered by :id so pages are stable.
set -u
cd ~/heatahead/stream2/raw
BASE="https://data.cityofnewyork.us/resource"
page_pull () {  # id, outfile, select, where
  local id="$1" out="$2" sel="$3" where="$4" off=0 n=0 t0=$(date +%s.%N)
  rm -f "$out"
  while :; do
    url="$BASE/$id.csv?\$limit=50000&\$offset=$off&\$order=:id&\$select=$sel"
    [ -n "$where" ] && url="$url&\$where=$where"
    if [ $off -eq 0 ]; then curl -s -m 600 --retry 3 "$url" > page.tmp; else curl -s -m 600 --retry 3 "$url" | tail -n +2 > page.tmp; fi
    rows=$(wc -l < page.tmp); [ $off -eq 0 ] && rows=$((rows-1))
    cat page.tmp >> "$out"; n=$((n+rows)); off=$((off+50000))
    echo "  $id page offset=$((off-50000)) rows=$rows total=$n $(date +%T)"
    [ $rows -lt 50000 ] && break
  done
  rm -f page.tmp
  echo "$id -> $out rows=$n secs=$(echo "$(date +%s.%N) - $t0" | bc) bytes=$(stat -c %s "$out")"
}
echo "START $(date)"
page_pull 52dp-yji6 dob_boiler_52dp-yji6.csv "tracking_number,boiler_id,report_type,boiler_make,pressure_type,inspection_type,inspection_date,defects_exist,lff_45_days,lff_180_days,report_status,bin_number" ""
page_pull f4rp-2kvy dep_boiler_fuel_f4rp-2kvy.csv "requestid,applicationid,requesttype,borough,bin,block,lot,expirationdate,make,model,burnermake,primaryfuel,secondaryfuel,quantity,issuedate,status" ""
page_pull tesw-yqqr hpd_registrations_tesw-yqqr.csv "registrationid,buildingid,boroid,bin,block,lot,communityboard,lastregistrationdate,registrationenddate" ""
page_pull kj4p-ruqc hpd_buildings_active_kj4p-ruqc.csv "buildingid,boroid,block,lot,bin,communityboard,legalstories,legalclassa,legalclassb,registrationid,recordstatus" "recordstatus='Active'"
page_pull 64uk-42ks pluto_all_lots_64uk-42ks.csv "bbl,borough,cd,council,zipcode,bldgclass,numbldgs,numfloors,unitsres,unitstotal,yearbuilt,yearalter1,bldgarea,latitude,longitude" ""
echo "END $(date)"
