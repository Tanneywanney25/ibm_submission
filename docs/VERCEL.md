# VERCEL.md: how the HeatAhead site is deployed, and the rules every change must follow

Read this before touching anything in `web/`, `api/`, `public/`, `realtime/`, `vercel.json`,
`requirements.txt` or `.vercelignore`. The root `CLAUDE.md` points here; this is the full
contract. The production site is **https://ibmsubmission.vercel.app** and it deploys
automatically from every push to `main` of `emersoncortazar/ibm_submission`.

## 1. Where things stand (updated October 17, 2026, evening)

- The Vercel entry point exists: `vercel.json`, `api/index.py`, `requirements.txt`,
  `.vercelignore` and `public/data/` (132 files, 13.1 MB, built on the s390x guest by
  `web/build_assets.py` from `season_risk_2026.csv` and `ranked_inspection_list.csv`
  regenerated that afternoon; `public/data/meta.json` records the model files, their sizes
  and the git sha they were built from).
- `web/app.py` now runs in two modes. FULL runs on the instance as the `heatahead-web`
  systemd service on port 8080 (open in iptables, rules persisted, Jupyter token rotated
  first). LITE runs on Vercel and forwards registrations to the instance (section 8).
- Before this, every route on the site returned Vercel's own `404: NOT_FOUND` because the
  repo had no entry point, and `web/app.py` imported pandas and read gitignored CSVs at
  import time, so it could not start on Vercel at all.

## 2. The architecture that fits Vercel (and keeps one codebase)

Two deployment targets, one Flask app, one URL contract.

| target | what runs | data | state |
|---|---|---|---|
| LinuxONE instance (`148.100.77.112`) | `web/app.py` in FULL mode (pandas, every CSV), `realtime/app.py` replay service on port 5000 | `model/out/` and `data/` on disk | SQLite `web/heatahead.db` |
| Vercel | the same `web/app.py` in LITE mode through `api/index.py` (Flask + requests only, no pandas) | precomputed JSON in `public/data/`, served statically by Vercel's CDN | registrations forwarded to the instance when `REGISTER_FORWARD_URL` is set, else `/tmp/heatahead.db` (ephemeral, demo only) |

Mode is decided at import time: FULL when `model/out/season_risk_2026.csv` exists, LITE
otherwise (override with `APP_MODE=full|lite`). Pandas is imported only inside the FULL
branch, so the Vercel bundle never needs it.

### Files that make the Vercel deploy

```
vercel.json              rewrites every non-static path to the one Python function
requirements.txt         flask, requests, nothing else (pandas is NOT installed on Vercel)
.vercelignore            excludes task 2/, analysis/, R/, model/, docs/, slides/, .venv/, *.ipynb, data/
api/index.py             adds the repo root to sys.path and exposes `app` from web/app.py (WSGI)
public/data/             the precomputed assets below, committed to git (total must stay under 60 MB)
web/build_assets.py      run on the instance (where model/out and data exist) to regenerate public/data/
```

`vercel.json` (static files in `public/` are matched before rewrites, so assets never hit the
function; `includeFiles` puts the templates and the shards inside the function bundle too):

```json
{
  "functions": { "api/index.py": { "includeFiles": "{web/**,public/data/**}" } },
  "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }]
}
```

`.vercelignore` anchors every pattern with a leading slash. Ignore files use gitignore
syntax, where a bare `data/` matches a `data` folder at any depth: on the first deploy it
silently dropped `public/data/`, `public/` was left empty, and Vercel fell back to serving
the repo root as static files (so `/web/app.py` was downloadable and every building call
returned 503).

### Precomputed assets in `public/data/` (built by `web/build_assets.py`)

| file | contents | size |
|---|---|---|
| `map_data.json` | `{columns:[lon,lat,p_season,c_last1,units], rows:[...], bbls:[...]}`, exactly what `/api/map_data` returns today | about 4 MB |
| `b/<n>.json` for n = `bbl % 128` (0 to 127) | `{bbl: [record]}` where the record is a positional list over `FIELDS` in `web/app.py` (season risk and rank, units, community district, chronic flag, complaints and violations by season, last dates, cold-day risk and rank, coordinates, landlord name and portfolio size); `building_payload()` turns a record into the `/api/building` JSON in both modes | about 78 KB each, 10.0 MB total |
| `reliability.json` | the calibration table (`/api/reliability`) | tiny |
| `top500.csv` | the government export (`/api/queue.csv?k=500`) | small |
| `meta.json` | citywide median season risk, ranked count, build timestamp, git sha, model file names | tiny |

In LITE mode the function reads `meta.json` and `reliability.json` at cold start and one
shard per building request (32 shards cached per warm instance). Vercel's Python builder
bundles the whole repo minus `.vercelignore`, so the shards are read from disk; if a future
builder leaves `public/` out of the bundle, the function fetches the shard from its own CDN
at `/data/b/<n>.json` instead. The `/api/building/<bbl>` route stays so the templates do
not change.

To rebuild after the model outputs change, on the instance:

```
cd ~/heatahead/site && git pull --rebase origin main
~/datathon-env/bin/python web/build_assets.py     # about 11 s on the s390x guest
```

then copy `public/` back to a laptop clone with
`ssh linux1@148.100.77.112 "cd ~/heatahead/site && tar czf - public" | tar xzf -`, commit it,
and say in the commit message which model files produced it. `.gitignore` ignores every
`data/` folder except `public/data/`.

## 3. The URL contract (do not break it; every page and task builds on these paths)

| route | method | serves | LITE mode source |
|---|---|---|---|
| `/` | GET | signup page (`index.html`) | template |
| `/building` | GET | lookup page (`building.html`) | template |
| `/map` | GET | risk map (`map.html`) | template |
| `/monitor` | GET | live monitor (`monitor.html`) | template |
| `/api/lookup?address=` | GET | `{bbl, normalized}` from NYC GeoSearch; 502 when the geocoder is down | live call, same in both modes |
| `/api/building/<bbl>` | GET | the building payload | `public/data/b/NN.json` |
| `/api/map_data` | GET | map rows | 302 redirect to `/data/map_data.json` (static, 3.1 MB; the function must not return 4 MB bodies, Vercel caps function responses at 4.5 MB). `fetch` follows the redirect, so `map.html` is unchanged |
| `/api/reliability` | GET | calibration table | `public/data/reliability.json` |
| `/api/register` | POST | `{ok, role, bbl, p_season?, normalized?, already_registered, stored_on, arch, durable}`; 400 with `{error}` for a bad role, email, phone or BBL, or an address GeoSearch cannot match on house number, street and borough; 502 when the geocoder is down | forwarded to `REGISTER_FORWARD_URL/api/register` when set (the instance geocodes, stores and sends the welcome email); if the instance is unreachable, held in `/tmp` SQLite with `durable:false` and the page says so |
| `/api/my_buildings?email=` | GET | `{buildings, total}`: the registered buildings plus the registered owner's portfolio | forwarded like register; without a forward target, the email's own registered buildings only |
| `/unsubscribe?email=&bbl=` | GET | deletes the registration rows, plain-text confirmation (linked from every email as an absolute `SITE_URL` link) | forwarded like register to the instance, where durable registrations live |
| `/api/health` | GET | `{mode, host, arch, ranked, built_at, registrations_to, linuxone?}`; the footer of every page shows it | adds the instance's own `/api/health` under `linuxone` (3 s timeout, `{offline:true}` when down) |
| `/data/<path>` | GET | the files in `public/data/` | Vercel's CDN serves them before any rewrite; Flask serves them for local runs |
| `/api/queue.csv?k=` | GET | top-k CSV | `public/data/top500.csv` (k capped at 500 in LITE) |
| `/api/draft_message/<bbl>` | GET | templated notice, never sent | computed from the shard |
| `/api/live/stats`, `/api/live/queue?k=` | GET | proxy to the realtime service | `REALTIME_URL` env var; 503 `{offline:true}` when unreachable |
| `/api/live/replay/start` | POST | proxy | same |

New endpoints go under `/api/` and get a row in this table in the same commit.

## 4. Environment variables (set in the Vercel project settings, never in the repo)

| name | value | used by |
|---|---|---|
| `REALTIME_URL` | `http://148.100.77.112:8080/api/live` (the instance's FULL app proxies its own realtime service on `127.0.0.1:5000`, so only port 8080 is open) | live monitor proxy |
| `REGISTER_FORWARD_URL` | `http://148.100.77.112:8080` | registrations, landlord portfolio, unsubscribe, health |
| `APP_MODE` | leave unset (auto); `lite` forces the JSON path | `web/app.py` |
| `SMTP_*` | only if alerts ever send from Vercel (they should not; the alert worker runs on the instance) | `web/alerts.py` |
| `SITE_URL` | base URL used in email links (default `https://ibmsubmission.vercel.app`); set on the instance, where the emails are sent from | `web/mailer.py` |

Vercel functions make outbound HTTP calls server-side, so a plain-HTTP instance URL is fine
there. The browser must never call the instance directly from the HTTPS site (mixed content
is blocked), which is exactly why the proxies exist.

## 5. Vercel limits that shape every decision

- Function bundle under 250 MB: that is why `.vercelignore` drops the analysis folders and
  why pandas stays out of the Vercel path (the five CSVs alone are 100 MB).
- Function response bodies under 4.5 MB: big payloads are static files in `public/`.
- Default function timeout is 10 s on the Hobby plan: keep every request under 2 s; do not
  compute anything heavy per request; the replay loop and the alert worker run on the
  instance, never on Vercel.
- Filesystem is read-only except `/tmp`, and `/tmp` is wiped between cold starts: nothing on
  Vercel is durable. Durable state (registrations) lives on the instance (or a managed
  database if someone sets one up and documents it here).
- No long-lived processes: no threads that outlive a request, no polling loops server-side.
- Every push to `main` is a production deploy; every push to any other branch is a preview
  deploy with its own URL. Risky UI work goes to a branch first.

## 6. Rules for every prompt that touches the site (Claude: follow these)

1. Keep the URL contract in section 3 intact. Templates only call same-origin `/api/...`
   paths and `/data/...` static files. Never reference `localhost`, `127.0.0.1` or the
   instance IP from browser code.
2. Code that runs on Vercel imports only the standard library, Flask and requests. Put any
   pandas or numpy use behind the FULL-mode branch of `web/app.py` or in
   `web/build_assets.py`.
3. Never commit `data/`, `model/out/`, pickles, databases or any file over 25 MB. The only
   data that ships is `public/data/`, rebuilt by `web/build_assets.py` on the instance, total
   under 60 MB, and the build commit says which model files produced it (`meta.json`).
4. Every page must degrade cleanly: realtime service offline shows the banner and logs no
   console errors; geocoder down lets the user type a 10-digit BBL; an unranked building
   shows the "not individually ranked" note with the citywide median, never a zero.
5. Display rules from `docs/webapp-spec.md` hold everywhere: building-level only (no
   apartment numbers anywhere, not even in a tooltip), probabilities capped at 99%, bands
   above 20%, calibrated numbers only, the trust table reachable from the building page.
6. Before pushing to `main`: `python -m compileall web api` passes; `APP_MODE=lite python
   web/app.py` starts without `model/out/` present and `curl` returns 200 for `/`, `/map`,
   `/building`, `/monitor`, `/api/reliability`, `/api/building/2043190010` and
   `/api/map_data` (with `curl -L`: LITE answers it with a 302 to the static file); then watch the Vercel deployment finish and open the production URL.
   If the deploy fails, read the build log before changing anything else.
7. Secrets never enter the repo: SMTP credentials, tokens, API keys go in Vercel environment
   variables or the instance's environment. The Jupyter token is not a secret anyone should
   paste anywhere.
8. Do not create a second Vercel project, rename this one, or change `vercel.json` routing
   without updating sections 2 and 3 in the same commit.
9. The instance is the only place the model, the replay loop and the alert worker run. The
   site on Vercel is the public face; when the instance is down the site still loads, says
   so on the monitor page, and every static page keeps working.
10. Pull with rebase before every commit, push to `main` (no force pushes), one commit per
    working change, and never leave `main` in a state where the production deploy fails.

## 7. Bringing the site up from the current 404 (the order of work)

Steps 1 to 4 were done on October 17, 2026; step 5 needs the two variables in section 4
set once in the Vercel project settings; step 6 follows the first good deploy.

1. On the instance, produce the two model outputs the site needs if they are missing:
   `python model/06_final_scores.py` (ranked_inspection_list.csv) and
   `python model/09_season_risk.py` (season_risk_2026.csv, season_reliability.csv).
2. Write `web/build_assets.py` and run it there: it writes `public/data/` as in section 2.
3. Add the LITE branch to `web/app.py`, plus `api/index.py`, `vercel.json`,
   `requirements.txt`, `.vercelignore`.
4. Run the section 6 smoke test locally, commit everything including `public/data/`, push to
   `main`, confirm https://ibmsubmission.vercel.app/ renders the signup page and
   `/api/building/2043190010` returns Building 60119's record.
5. In the Vercel project settings, set `REALTIME_URL` and `REGISTER_FORWARD_URL` once the
   instance ports are open (iptables, rules persisted, Jupyter token changed first), redeploy.
6. Record the production URL and the deploy time in `docs/SUBMISSION.md`.

## 8. The instance side (what runs on `148.100.77.112`)

| systemd unit | what | where |
|---|---|---|
| `heatahead-web` | `web/app.py` in FULL mode under waitress, `0.0.0.0:8080` | `~/heatahead/site` (a clone of `main`; `data` and `model/out` are symlinks into `~/heatahead/ibm_submission`), log `~/heatahead/logs/web.log`, SQLite `~/heatahead/site/web/heatahead.db` |
| `heatahead-realtime` | `realtime/app.py` replaying `data/replay_feb7_9.csv` (14,018 complaints at 6,454 buildings, building-level columns only) on `127.0.0.1:5000` | same clone, log `~/heatahead/logs/realtime.log` |
| `heatahead-jupyter` | JupyterLab on `127.0.0.1:8888`, reached through an SSH tunnel | token in `~/.config/heatahead/jupyter.env` (mode 600); read it in your own terminal with `ssh linux1@148.100.77.112 cat ~/.config/heatahead/jupyter.env` and never paste it into a chat |
| cron, minute 7 of every hour | `web/alerts.py` against the same SQLite | log `~/heatahead/logs/alerts_cron.log` |

After a push that changes `web/`: `cd ~/heatahead/site && git pull --rebase origin main &&
sudo systemctl restart heatahead-web`. Port 8080 is the only port open besides 22
(`sudo iptables -S INPUT`; persisted in `/etc/iptables/rules.v4`).

## 9. Checking a deploy without the dashboard

```
curl -sS -o /dev/null -w "%{http_code}\n" https://ibmsubmission.vercel.app/
curl -sS https://ibmsubmission.vercel.app/api/reliability | head -c 300
curl -sS https://ibmsubmission.vercel.app/api/building/2043190010 | head -c 400
curl -sS -o /dev/null -w "%{http_code} %{size_download}\n" https://ibmsubmission.vercel.app/data/map_data.json
```

All four must return 200 and the building call must mention `"ranked": true`.
