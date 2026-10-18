# VERCEL.md: how the HeatAhead site is deployed, and the rules every change must follow

Read this before touching anything in `web/`, `api/`, `public/`, `realtime/`, `vercel.json`,
`requirements.txt` or `.vercelignore`. The root `CLAUDE.md` points here; this is the full
contract. The production site is **https://ibmsubmission.vercel.app** and it deploys
automatically from every push to `main` of `Tanneywanney25/ibm_submission` (the repo moved
from `emersoncortazar/ibm_submission` on October 17, 2026; GitHub redirects the old URL and
the Vercel project followed the move).

## 1. Where things stand (updated October 17, 2026, evening)

- The Vercel entry point exists: `vercel.json`, `api/index.py`, `requirements.txt`,
  `.vercelignore` and `public/data/` (132 files, 13.1 MB, built on the s390x guest by
  `web/build_assets.py` from `season_risk_2026.csv` and `ranked_inspection_list.csv`
  regenerated that afternoon; `public/data/meta.json` records the model files, their sizes
  and the git sha they were built from).
- `web/app.py` now runs in two modes. FULL runs on the instance as the `heatahead-web`
  systemd service on port 8080 (open in iptables, rules persisted, Jupyter token rotated
  first). LITE runs on Vercel and forwards registrations to the instance (section 8).
- `REGISTER_FORWARD_URL` and `REALTIME_URL` are set as Production variables in the Vercel
  project (type Config, values in section 4) and production was redeployed with them at
  about 18:08 UTC on October 17, 2026. `/api/health` on the live site reports
  `"registrations_to": "linuxone"` and the instance's own health under `linuxone`.
- Before this, every route on the site returned Vercel's own `404: NOT_FOUND` because the
  repo had no entry point, and `web/app.py` imported pandas and read gitignored CSVs at
  import time, so it could not start on Vercel at all.

## 2. The architecture that fits Vercel (and keeps one codebase)

Two deployment targets, one Flask app, one URL contract.

| target | what runs | data | state |
|---|---|---|---|
| LinuxONE instance (`148.100.77.112`) | `web/app.py` in FULL mode (pandas, every CSV), `realtime/app.py` replay service on port 5000 | `model/out/` and `data/` on disk | SQLite `web/heatahead.db` |
| Vercel | the same `web/app.py` in LITE mode through `api/index.py` (Flask, requests, Google auth SDKs; no pandas) | precomputed JSON in `public/data/`, served statically by Vercel's CDN | signed account sessions in secure cookies; registrations forwarded to the instance; 503 if durable storage is unavailable |

Mode is decided at import time: FULL when `model/out/season_risk_2026.csv` exists, LITE
otherwise (override with `APP_MODE=full|lite`). Pandas is imported only inside the FULL
branch, so the Vercel bundle never needs it.

### Files that make the Vercel deploy

```
vercel.json              rewrites every non-static path to the one Python function
requirements.txt         pinned Flask, requests, google-auth, google-auth-oauthlib (no pandas)
.vercelignore            excludes task 2/, analysis/, R/, model/, docs/, slides/, .venv/, *.ipynb, data/
api/index.py             adds the repo root to sys.path and exposes `app` from web/app.py (WSGI)
public/data/             the precomputed assets below, committed to git (total must stay under 60 MB)
web/build_assets.py      run on the instance (where model/out and data exist) to regenerate public/data/
web/build_contacts.py    run on the instance before it: owner and managing-agent table (T5a)
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
| `b/<n>.json` for n = `bbl % 128` (0 to 127) | `{bbl: [record]}` where the record is a positional list over `FIELDS` in `web/app.py` (season risk and rank, units, community district, chronic flag, complaints and violations by season, last dates, cold-day risk and rank, coordinates, landlord name and portfolio size, then the T5a fields: managing agent, whether it files as a company, its address, the corporate owner's business address, HPD building id and last registration date); `building_payload()` turns a record into the `/api/building` JSON in both modes. New fields go at the end of `FIELDS`, so a shard built before them still reads (the missing ones are None) | about 78 KB each before T5a; see `meta.json` for the current total |
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
~/datathon-env/bin/python web/build_contacts.py --pull   # HPD contacts feu5-w2e2, about 35 s
~/datathon-env/bin/python web/build_assets.py     # about 11 s on the s390x guest
```

then copy `public/` back to a laptop clone with
`ssh linux1@148.100.77.112 "cd ~/heatahead/site && tar czf - public" | tar xzf -`, commit it,
and say in the commit message which model files produced it. `.gitignore` ignores every
`data/` folder except `public/data/`.

## 3. The URL contract (do not break it; every page and task builds on these paths)

| route | method | serves | LITE mode source |
|---|---|---|---|
| `/` | GET | Google sign-in or signed-in account, saved buildings and registration (`index.html`) | template + authenticated account API |
| `/building` | GET | lookup page (`building.html`); `?bbl=` opens a building directly, `?q=` runs an address search on arrival (T17) | template |
| `/map` | GET | risk map (`map.html`); `?bbl=` opens centered on that building with a highlight ring, `?embed=1` is the chrome-free embed the building page's map panel uses (T17) | template |
| `/monitor` | GET | live monitor (`monitor.html`) | template |
| `/learn-more` | GET | how the site works, map reading, prediction windows, actions, data and privacy | template + shared guide content |
| `/faq` | GET | 26 searchable, categorized questions with deep links and official sources | shared guide content, server-rendered answers (works without JavaScript) |
| `/about` | GET | About/Methods page: what HeatAhead is, methods, why precision@k, ranges and calibration, open source (`about.html`; copy source `docs/about-copy.md`) | template only, static content |
| `/api/guide/ask` | POST | `{question,previous_topic?}` → `{topic,mode}`; optional AI selects an existing FAQ id; no generated URLs, scores, account actions or conversation storage; 400 invalid/private input, 403 cross-origin, 429 warm-worker request limit | stdlib + requests; 200 `{topic:null,mode:"guide"}` if unconfigured or provider fails |
| `/api/lookup?address=` | GET | `{bbl, normalized}` from NYC GeoSearch; 502 when the geocoder is down | live call, same in both modes |
| `/api/building/<bbl>` | GET | the building payload | `public/data/b/NN.json` |
| `/api/map_data` | GET | map rows | 302 redirect to `/data/map_data.json` (static, 3.1 MB; the function must not return 4 MB bodies, Vercel caps function responses at 4.5 MB). `fetch` follows the redirect, so `map.html` is unchanged |
| `/api/reliability` | GET | calibration table | `public/data/reliability.json` |
| `/api/register` | POST | save a building to the signed-in account (`{address or bbl, phone?}`); `role` is optional since T14 (one account type) and defaults to `tenant`, the value the `users.role` column and `web/alerts.py` use for building alerts; older clients may still send one of the four legacy roles; signed-in identity and `X-CSRF-Token` required; email comes from the session; 400 missing/invalid building, unknown role or bad phone, 401 signed out, 403 other email or bad CSRF, 503 unavailable account service | signed request forwarded to the instance; no ephemeral fallback |
| `/api/my_buildings` | GET | `{buildings, total, registrations:[{role,bbl}]}` for the signed-in email, plus public portfolio context; optional legacy `email=` must equal that account | signed request forwarded to the instance; 503 when unavailable |
| `/api/account/panels` | GET, POST | the signed-in account's dashboard panel set (T14: `buildings`, `audit`, `queue`, `stats`); GET returns `{panels}` where null means "never customized" (the page derives defaults from the account's registration roles); POST `{panels:[...]}` stores a distinct subset in fixed display order; 400 unknown panel, 401 signed out, 403 bad CSRF, 503 account service unavailable (the page then falls back to role defaults and a per-device copy) | signed request forwarded to the instance; 503 when unavailable |
| `/unsubscribe?email=&bbl=` | GET | sign-in followed by a confirmation form; GET never deletes data | signed-in website template |
| `/api/account/remove` | POST | `{ok,removed}`; JSON/form optional `bbl` (omit to remove all own registrations), signed-in identity and CSRF required; form success redirects home | signed request to durable instance storage |
| `/api/auth/google` | GET | start Google sign-in; optional safe local `next`, `remember=1` (30 days) or `0` (browser session, maximum 12 hours); 503 when unconfigured | Google library authorization-code flow with PKCE, state and nonce |
| `/api/auth/callback` | GET | verifies Google code and ID token, establishes signed session, redirects to safe local destination | exact registered Google redirect URI |
| `/api/auth/email` | POST | `{email, remember}` → sends a signed one-use 15-minute sign-in link (passwordless, T14); 400 invalid email, 429 per-worker budget, 503 unconfigured or backend unreachable | token signed on Vercel with the shared secret; the email is sent by the instance via a signed forward to `/api/account/email_link` |
| `/api/auth/email/callback` | GET | verifies the link token and consumes its nonce one-use, establishes the same signed session as Google, redirects home | nonce consumed on the instance (`/api/account/email_consume`); 503 fail-closed when it is unreachable |
| `/api/account/email_link`, `/api/account/email_consume` | POST | instance side of email sign-in: mail the website's link / consume a link nonce; 403 for anything but the signed website-to-backend protocol | FULL mode only (the instance) |
| `/api/auth/session` | GET | `{user,google_ready,email_ready,csrf_token}`; user is null when signed out | signed cookie, private/no-store |
| `/api/auth/logout` | POST | clear session, redirect home; form or `X-CSRF-Token` required | website session |
| `/api/health` | GET | existing health fields plus `account_protocol` (1 when shared secret configured), `google_sign_in`, `email_sign_in` (on the instance: true only with `SMTP_HOST` set; on Vercel: the instance's value, cached two minutes) | adds instance health under `linuxone` (3 s timeout, `{offline:true}` when down) |
| `/data/<path>` | GET | the files in `public/data/` | Vercel's CDN serves them before any rewrite; Flask serves them for local runs |
| `/api/queue.csv?k=` | GET | top-k CSV | `public/data/top500.csv` (k capped at 500 in LITE) |
| `/api/draft_message/<bbl>?as=&address=` | GET | `{to, recipients, subject, body, framing, note}`: a notice the user copies or opens in their own mail client, never sent. `as=tenant` (default) is a resident's request to the registered owner care of the managing agent; `as=landlord` is the owner's pre-winter self-audit; `address` names the building in the text (units are cut). 400 for another `as`, 404 for an unranked building | computed from the shard |
| `/api/live/stats`, `/api/live/queue?k=` | GET | proxy to the realtime service | `REALTIME_URL` env var; 503 `{offline:true}` when unreachable |
| `/api/live/replay/start` | POST | proxy | same |
| `/api/current/stats`, `/api/current/queue?k=`, `/api/current/events` | GET | published HPD complaints and collection freshness | COMPLAINT_URL proxy; 503 when unavailable |

New endpoints go under `/api/` and get a row in this table in the same commit.

## 4. Environment variables (set in the Vercel project settings, never in the repo)

| name | value | used by |
|---|---|---|
| `REALTIME_URL` | `http://148.100.77.112:8080/api/live` (the instance's FULL app proxies its own realtime service on `127.0.0.1:5000`, so only port 8080 is open) | live monitor proxy |
| `COMPLAINT_URL` | LinuxONE: `http://127.0.0.1:5001`; Vercel Production: `http://148.100.78.43:8080/api/current` | published complaint monitor |
| `REGISTER_FORWARD_URL` | `http://148.100.77.112:8080` | registrations, landlord portfolio, unsubscribe, health |
| `APP_MODE` | leave unset (auto); `lite` forces the JSON path | `web/app.py` |
| `SMTP_*` | only if alerts ever send from Vercel (they should not; the alert worker runs on the instance) | `web/alerts.py` |
| `SITE_URL` | base URL used in email links (default `https://ibmsubmission.vercel.app`); set on the instance, where the emails are sent from | `web/mailer.py` |
| `FLASK_SECRET_KEY` | stable random secret of at least 32 characters; exactly the same value on Vercel and LinuxONE; never commit it | signed cookies and one-use account forwarding |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth web application credentials; Vercel only | Google sign-in |
| `AUTH_BASE_URL` | `https://ibmsubmission.vercel.app` for Production; exact stable preview origin for a preview; no trailing path | OAuth callback origin and cookie host |
| `OPENAI_API_KEY` | optional server-side provider key; never send it to the browser or commit it | guide AI topic matching only |
| `GUIDE_AI_MODEL` | explicit active Responses API model with Structured Outputs support; AI stays disabled unless both variables are set | optional semantic matching of unfamiliar wording |

The browser calls only the HTTPS website. Account forwarding now signs the exact request
and matching reply with 60-second expiry, SHA-256, and a SQLite one-use nonce. An old backend,
wrong secret or tampered response fails closed with 503. The existing HTTP instance URL
does **not** encrypt registration data in transit; use an HTTPS backend/private encrypted
transport for production confidentiality. Google tokens and client secrets never go to the
instance. Full setup and coordinated rollout: [GOOGLE_LOGIN.md](GOOGLE_LOGIN.md).

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
   paths and `/data/...` static files, plus the public third-party services already in use
   (basemap/tile CDNs, ArcGIS imagery, and NYC Planning GeoSearch autocomplete for the T17
   search box — the query string is the only thing sent). Never reference `localhost`,
   `127.0.0.1` or the instance IP from browser code.
2. Code that runs on Vercel imports the standard library, Flask, requests and the pinned
   Google auth libraries in `requirements.txt`. Google SDK imports are lazy, used only by
   sign-in; the LinuxONE registration service does not need them. Put any
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
   For account/map changes, also run `python -m unittest discover -s web/tests -v` (with
   the pinned Google SDKs on Python 3.10+) and `node web/tests/test_map.cjs` (Node 18+).
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

All six steps were done on October 17, 2026.

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
| `heatahead-realtime` | `realtime/app.py` replaying `data/replay_feb7_9.csv` on `127.0.0.1:5000` and scoring every complaint with the frozen model (`scoring_mode: xgboost_final_isotonic_cpu`, 36 features, 62,716 ranked buildings). The replay file uses the model's own complaint filter (`problem_code` NO HEAT or NO HEAT AND NO HOT WATER, as in `model/01_build_panel.py`) with columns `received_date, complaint_id, bbl, minor_category`: 13,186 complaints at 6,133 tax lots, 8,252 of them ENTIRE BUILDING (`docs/SUBMISSION.md` counts 13,222 at 6,382 HPD building ids; 36 of those complaints carry no BBL). Startup also needs `model/out/feature_schema.json` and `model/out/building_features.csv`, which git does not carry: make them with `python model/10_export_replay_assets.py 2026-02-06` and copy `model/out/replay/features_schema.json` and `static_features.csv` to those two names | same clone, log `~/heatahead/logs/realtime.log`, checkpoint `data/realtime_model_checkpoint.json` |
| `heatahead-jupyter` | JupyterLab on `127.0.0.1:8888`, reached through an SSH tunnel. Pick the `datathon-env` kernel (the project venv, registered October 17, 2026); the default `python3` kernel is the system interpreter, which has no Flask. `web/jupyter/run_in_jupyter.py <notebook>` executes a notebook inside this server from an SSH shell | token in `~/.config/heatahead/jupyter.env` (mode 600); read it in your own terminal with `ssh linux1@148.100.77.112 cat ~/.config/heatahead/jupyter.env` and never paste it into a chat |
| cron, minute 7 of every hour | `web/alerts.py` against the same SQLite | log `~/heatahead/logs/alerts_cron.log` |

After a push that changes `web/`: `cd ~/heatahead/site && git pull --rebase origin main &&
sudo systemctl restart heatahead-web`; after one that changes `realtime/`, restart
`heatahead-realtime` too and check `curl -s localhost:5000/stats` reports the model scoring mode
(a failed start loops under `Restart=always`, so read `~/heatahead/logs/realtime.log`). Port 8080
is the only port open besides 22 (`sudo iptables -S INPUT`; persisted in `/etc/iptables/rules.v4`).

This instance is production: `REALTIME_URL` and `REGISTER_FORWARD_URL` in Vercel point here,
and its `model/out` holds the frozen model files the published site was built from
(`public/data/meta.json` lists them). Other team LinuxONE guests are development machines; a copy
of `model/out` taken from the shared Drive before the 17:42 UTC rebuild on October 17, 2026 is an
older model (its `heat_model_final.json` hashes differently), so compare `sha256sum` before
quoting numbers measured there. On October 17, 2026 the replay service crash-looped from about
20:16 to 20:27 UTC after the model-scoring code was pulled without those two files, then stayed
stopped until 22:07 UTC, when the files above were generated here and a full replay passed
(p50 0.40 ms and p99 0.99 ms per complaint; 62,716 buildings rescored in 0.55 s).

## 9. Checking a deploy without the dashboard

```
curl -sS -o /dev/null -w "%{http_code}\n" https://ibmsubmission.vercel.app/
curl -sS https://ibmsubmission.vercel.app/api/reliability | head -c 300
curl -sS https://ibmsubmission.vercel.app/api/building/2043190010 | head -c 400
curl -sS -o /dev/null -w "%{http_code} %{size_download}\n" https://ibmsubmission.vercel.app/data/map_data.json
```

All four must return 200 and the building call must mention `"ranked": true`.

## 10. Accounts and map interactions

Google sign-in configuration and release checks are in [GOOGLE_LOGIN.md](GOOGLE_LOGIN.md).
Email sign-in (T14) is passwordless: the site emails a signed link that works once for
15 minutes; no password is ever stored or accepted. It needs `FLASK_SECRET_KEY` (the same
value on Vercel and the instance), `REGISTER_FORWARD_URL`, `SMTP_*` on the instance, and
the instance's `~/heatahead/site` clone pulled and restarted; until all of those are in
place the form says it is being set up and `/api/health` reports `email_sign_in: false`.
The instance counts as ready only when `SMTP_HOST` is set, because without it `mailer.py`
only logs messages and nobody would receive the link; Vercel offers email sign-in only
while the instance's `/api/health` says `email_sign_in: true` (checked at most every two
minutes). A laptop run (`host: local`) treats its log as the inbox for testing.
The instance only mails links that point at its own `SITE_URL`, so preview deploys cannot
send sign-in email. Remembered sessions last up to 30 days; browser cookies are Secure,
HttpOnly and SameSite=Lax.
No Google access, refresh or ID token is stored in the cookie. There is one account type
(T14): the dashboard shows the panels each user turns on in their profile, and no panel
grants verified inspector or owner privileges. A role stored by an older registration only
picks that account's default panels until the user changes them. Alert registration rows remain
in the existing instance SQLite database and reload after a fresh Google sign-in.

The map uses a fixed pale-blue to deep-blue risk scale, interpolated into 256 steps for
deck.gl 8 compatibility. Area color is mean property risk; the legend uses the same endpoints.
Clicking a hexagon opens all its current-filter buildings in a paginated list; only clicking
an individual marker or list link navigates to a building. The citywide view uses 400 m
hexagon radii, smoothly blending to fixed 120 m radii at zooms 11.3–12.5, before the existing
12.8–14.8 fade to individual property dots. All layers use the same filtered properties;
color remains the mean risk, height the sum of last-season complaints at 1.5 display m per
complaint. No scores or public assets change. A grid switch closes any previous area list
so its members do not refer to the old grid. Exactly one representation handles picking.

Wheel easing is disabled, wheel speed is explicit, and camera updates coalesce per frame.
Panning reuses existing data layers and fixed radii avoid per-frame re-binning. Basemap
pixel ratio follows the screen up to 2, and the data overlay up to 1.5, instead of forcing
both to 1 and blurring Retina text. Caps bound the fill/picking cost. The flat/3D choice
is preserved when zooming to buildings. Verify actual-device appearance/performance in
the preview; logic tests cannot prove frame rate or GPU rendering.

## 11. Learn more, FAQs and site guide

`web/site_guide.py` owns `/learn-more`, `/faq` and the optional AI topic endpoint. The 26
answers live once in `web/static/guide-content.json`, which drives the FAQ page and the
guide on every page. The guide matches common wording locally using `web/static/guide.js`;
it runs without Google credentials, a provider key or the LinuxONE backend. FAQ details
and links remain available when JavaScript is disabled. New UI uses the existing theme.

Optional AI **only selects a topic id** from the shared catalog. The application, not the
model, supplies the published answer and allowlisted links. The visitor clicks a shortcut
to navigate; no account changes, notices, complaint filings or model scoring occur.
Questions use a same-origin POST, not a query string. Account identity and conversation
history never enter the provider payload; BBLs are redacted, obvious contact/unit details
are rejected, and the application stores no guide conversation. `store:false` on provider
requests is not a promise of zero provider retention. No provider error, question or key
is logged. Source links for heat requirements and reporting go to official NYC pages.

The public AI endpoint has a warm-worker budget of 5 requests/client/minute and 20 total
requests/minute, a 400-character input cap, bounded provider timeout and output length,
and no automatic retries. These are **not distributed quotas or a global spending cap**:
set a provider project budget/rate limit and hosting controls before enabling public AI.
Without a key/model, only the local guide runs; it must not be advertised as generative AI.
Setup, tests and rollout: [SITE_GUIDE.md](SITE_GUIDE.md).

## 12. Current published heat complaints (Sid)

`/monitor` shows current public HPD heat-complaint observations. The historical model
replay remains at `/monitor?mode=replay`, with its existing `/api/live/*` routes unchanged.

Residents report through NYC311: call 311 or the official residential heat/hot-water page
https://portal.311.nyc.gov/article/?kanumber=KA-01036 . HPD handles residential maintenance
complaints. The public 311 dataset `erm2-nwe9` is updated daily, not a direct streaming
subscription. The monitor uses HPD `ygpa-z7cr`, matching the existing model's NO HEAT and
NO HEAT AND NO HOT WATER filter. A live API check on October 17 found HPD's newest published
records newer than the general 311 heat feed. The collector selects building-level fields
only and does not scrape the complaint-submission form, submit reports, or fetch resident
contact/unit details.

Poll every five minutes, refresh the page every 15 seconds. A fast poll does not remove
the publisher's delay. Show complaint received time and collector check time separately;
never claim the page receives a resident's submission instantly. A report does not prove
an outage is still active. The current page contains distinct-complaint volume and recent
reports, not calibrated October predictions. The February features and replay stay separate.
The source combines heat-only and heat-plus-hot-water reports; water-only reports are excluded.

### Collector and durability

`realtime/complaint_pipeline.py` provides `poll`, `serve`, and `check`. It runs under
waitress on loopback 5001 and stores data in ignored `data/live_complaints.sqlite3`.
Initial pull: 35 days. Polls overlap seven days and extend backward after downtime.
Reconciliation rereads 90 days daily. Numeric problem_id plus received_date supplies
keyset pagination. All pages must validate before an atomic SQLite window replacement;
failed pages retain the prior successful data. Problems deduplicate by problem_id and
reports by complaint_id. Conflicting or missing BBLs remain unlocated. Counts and the
feed cover received times in the preceding seven days; the 24-hour total is also shown.
The feed lists at most 100 reports and the building table at most 25 tax lots by observed
complaint count. Arbitrarily old changes beyond the reconciliation window and concurrent
upstream edits during pagination are not guaranteed captured. This is a published-data
monitor rather than a full historical archive or streaming city integration.

`realtime/deploy_complaint_automation.py` generates reviewable systemd units under ignored
`data/complaint-automation-units`. Install with `--install`: an initial source pull must
succeed before units change. Poll every five minutes, reconcile at 04:20 New York daily,
run temporary-database tests every six hours and collector health checks every ten minutes.
Existing complaint units are backed up before replacement. Web/replay units, model files,
registration SQLite, SMTP, firewall and Vercel settings are untouched by this deployer.
A failed health unit is visible in systemctl/journal; external notifications are not configured.
Optional SOCRATA_APP_TOKEN goes only in ~/.config/heatahead/complaints.env (mode 600).

### Sid's development server (148.100.78.43)

Use ~/ibm_submission and ~/jupyter-env/bin/python. Install the guarded live-monitor patch,
then:

```
cd ~/ibm_submission
~/jupyter-env/bin/python -m pip install --only-binary=:all: waitress
~/jupyter-env/bin/python realtime/deploy_complaint_automation.py
~/jupyter-env/bin/python realtime/deploy_complaint_automation.py --install
curl --fail --retry 10 --retry-connrefused --retry-delay 2 -sS localhost:5001/stats
```

Restart Sid's web process so it picks up the new proxy/template. If it is systemd-managed,
`sudo systemctl restart heatahead-web`. If it is still manually launched, stop that web
process with Ctrl+C and start `APP_MODE=lite ~/jupyter-env/bin/python web/app.py`. Do not
start a second process on 8080. The web app defaults COMPLAINT_URL to localhost:5001 on the
same guest; no Vercel setting is needed for the SSH-tunneled development monitor.
Verify localhost:8080/api/current/stats and /monitor before requesting a production cutover.

### Public deployment using Sid's collector

Current published complaints run on 148.100.78.43:
- Collector: loopback port 5001.
- Web proxy: port 8080 under heatahead-web.
- Vercel Production COMPLAINT_URL: http://148.100.78.43:8080/api/current

Merge the source changes, set that variable in the existing Vercel project,
and redeploy. Verify the public /api/current/stats and /monitor afterward.
REALTIME_URL and REGISTER_FORWARD_URL remain on 148.100.77.112.

All frontend calls remain same-origin `/api/current/*`. No pandas/scientific packages
enter the Vercel import path. The public collector API is read-only; no synthetic inputs
are accepted. Automated tests use temporary databases and offline source fixtures. No
emails or NYC complaints are sent by tests, checks, installation, or page polling.
