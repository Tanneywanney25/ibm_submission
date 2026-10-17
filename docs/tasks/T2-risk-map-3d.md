# T2 — The risk map (heat map, optionally 3D)

**Goal:** the "wow" visual — every ranked building on a citywide map, colored by
winter risk, with problem clusters unmistakable (the Bronx corridor should jump
out). 3D if it stays smooth; 2D heat map is the fallback, not a failure.

## Data (ready now)

- `GET /api/map_data` (already in `web/app.py`): 63,727 rows —
  `[lon, lat, p_season, c_last1, units]` + BBL list (~4 MB JSON, one fetch)
- District overlays if wanted: `task 2/deliverables/cd_level_map_data.csv`
  (centroids + per-CD complaint rates)

## Recommended build: deck.gl standalone (no build step, CDN scripts)

- `maplibre-gl` (CSS+JS) + `deck.gl` dist.min.js from CDN; CARTO dark-matter style
- **3D view:** `HexagonLayer` — elevation = complaints last season, color =
  mean p_season; radius ~120 m; pitch 45°
- **Building view (zoom ≥ 14):** `ScatterplotLayer`/`ColumnLayer` per building,
  click → tooltip (risk %, units, complaints) with a link to `/building?bbl=`
- Toggle: 3D hexagons ↔ flat heat map; filter slider on p_season
- Keep the Figma step light: design the panel/tooltip/legend in Figma first if
  it helps alignment, but don't block the map on it — the design system is
  dark panel, orange accent (`#ff6b35`), tokens already in `web/templates/base.html`

## Display rules (non-negotiable, from docs/webapp-spec.md)

- Building-level only, never apartment data
- Probabilities capped at 99%; above 20% show bands in tooltips
- Color scale: sequential single hue for risk (not rainbow); legend always visible

## Steps

1. `web/templates/map.html`: fetch `/api/map_data`, render HexagonLayer
2. Tooltip + click-through to the building page
3. 2D/3D toggle + risk filter
4. Screenshot/screen-record for the video (Bronx fly-in is the money shot)

## Acceptance

- [ ] Loads in <5 s on the instance over the public IP
- [ ] Bronx CDs 204/205/207 visibly hottest (cross-check `fig_bronx_cd_impact.png`)
- [ ] Click any hexagon/building → correct building page
- [ ] Legend + "what am I seeing" one-liner on screen

**Depends on:** T1 shell. **Feeds:** video, community-impact bonus.
