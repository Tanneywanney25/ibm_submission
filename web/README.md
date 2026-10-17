# Website / frontend — workstream 3

Folium (or Leaflet) map of the ranked inspection list, served by Flask on the LinuxONE public IP.

- Build early against `data/buildings.csv` with placeholder scores; swap in real scores from `model/` when ready
- Two views: most likely to fail, and most tenants at risk (probability × apartments)
- Replay panel: Feb 7-9, 2026 cold snap beside the live Open-Meteo 16-day forecast
- Building-level only — never show apartment numbers

Also owns LinuxONE setup: docker container, change the Jupyter token, open ports, persist iptables, screenshot `uname -m` and the `nnpa` check (see `docs/heat-project-brief.md` §7).
