# Google login and saved buildings

This is a code-and-configuration release. Uploading templates alone cannot enable Google
login. One teammate who can edit the Google Cloud project, Vercel environment and LinuxONE
service should do the setup below. Never put a client secret or session key in GitHub,
screenshots, chat, a notebook, or a browser-visible JavaScript variable.

## What is set up now (October 18, 2026)

The steps below have been done once for production; use them again only to rebuild.

| piece | where | state |
|---|---|---|
| Google Cloud project | **HeatAhead** (project id `heatahead`), owned by Tanush's Google account | consent screen "HeatAhead", External, **In production**, home page and privacy link (`/learn-more#data-and-privacy`) filled in, authorized domain `ibmsubmission.vercel.app` |
| OAuth web client | "HeatAhead website" in that project | one redirect URI, `https://ibmsubmission.vercel.app/api/auth/callback` |
| Vercel Production | Config: `AUTH_BASE_URL`, `GOOGLE_CLIENT_ID`; Secret: `FLASK_SECRET_KEY`, `GOOGLE_CLIENT_SECRET` | the two Secret values are pasted in by a person, never by an agent or through chat |
| LinuxONE | `~/.config/heatahead/accounts.env` (mode 600) holds `FLASK_SECRET_KEY`; the systemd drop-in `heatahead-web.service.d/accounts.conf` loads it | the Vercel value must be byte-for-byte this one |

The site does its own Google sign-in; it does not use Supabase. The Supabase project's
Google provider uses a different client (`IBM_Submission` in the "Default Gemini Project",
whose consent screen is ScoutTree's), and nothing on the site depends on it. To check
production, `curl https://ibmsubmission.vercel.app/api/health` must show
`"google_sign_in":true`, `"account_protocol":1`, and the same two under `linuxone`.

## What users get

- One **Continue with Google** button for both first-time and returning users.
- Optional **Keep me signed in for 30 days on this device**. Unchecked means a browser
  session, with a 12-hour server expiry; checked means a fixed 30-day maximum. Browser
  cookie settings can shorten this. A stable `FLASK_SECRET_KEY` preserves valid sessions
  across deployments; rotating it intentionally signs everyone out.
- Google-verified email, name and account id in a signed, HttpOnly, Secure, SameSite=Lax
  session cookie. Google access, refresh and ID tokens are never saved there. No site
  passwords and no Drive/Gmail permissions.
- Durable registrations in the existing `web/heatahead.db` on LinuxONE. Signing in with
  the same verified email restores existing registrations, including earlier alert signups.
- Sign-out, an account list of saved buildings, and removal of one's own alert registrations.
  Public map, building records and inspection views remain available while signed out.

Tenant/landlord/government/viewer are preferences for public views and alerts, not proof of
building ownership or government employment. No extra private inspector data is unlocked.

## 1. Put the code on a fresh GitHub branch

Start from current `main`, create `google-login-map`, and upload the changed files to their
original paths. The download preserves `web/`, `docs/`, and `requirements.txt`; upload those
items at the repository root. Keep the folder hierarchy. Do not upload the zip itself,
databases, environment files, model files or test dependencies.

Open a PR. Vercel will give it a preview. Its Google button stays disabled until the
configuration below is present. Use a stable branch preview URL, not a changing deployment
hash URL. Do not merge until the preview login and durable registration checks pass.

## 2. Create the Google web client

Official setup: <https://developers.google.com/identity/protocols/oauth2/web-server>
and <https://developers.google.com/workspace/guides/configure-oauth-consent>.

1. Open <https://console.cloud.google.com/>. Create/select a project named **HeatAhead**.
2. Open **Google Auth Platform** (search the console if needed), then **Get started**.
3. Branding: app name **HeatAhead**, a support email the team owns, and a developer contact
   email. Audience: **External** for a demo used outside the school's managed organization.
4. Data access: use only `openid`, `.../auth/userinfo.email`, and `.../auth/userinfo.profile`.
   The code requests these three scopes and nothing else.
5. Under **Audience**, if the app is in Testing, add the team's actual Google accounts to
   **Test users**. Do not assume Testing permits every judge's account; configure the
   intended audience before presenting a public signup. Follow Google's requirements if
   you later publish the consent configuration.
6. **Clients → Create client → Web application**. Name it **HeatAhead website**.
7. Add this exact **Authorized redirect URI** (no trailing slash):

   ```text
   https://ibmsubmission.vercel.app/api/auth/callback
   ```

8. Add a second redirect URI using the exact stable preview origin:

   ```text
   https://YOUR-STABLE-PREVIEW.vercel.app/api/auth/callback
   ```

9. Create the client and securely keep its **Client ID** and **Client secret**. Set them
   directly in Vercel; do not send them to chat or commit the downloaded client JSON.
   This is a server redirect flow; Authorized JavaScript origins are not used by this code.

## 3. Generate ONE shared signing secret on LinuxONE

In your own SSH terminal, run:

```sh
mkdir -p ~/.config/heatahead
chmod 700 ~/.config/heatahead
~/datathon-env/bin/python - <<'PY'
from pathlib import Path
import os, secrets
target = Path.home() / '.config/heatahead/accounts.env'
if target.exists():
    print('Already exists; keep the current key:', target)
else:
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('FLASK_SECRET_KEY=' + secrets.token_urlsafe(48) + '\n')
    print('Created private account environment:', target)
PY
```

Read that file **only in your own terminal** and copy the value after `FLASK_SECRET_KEY=`
into Vercel. Do not generate a second value there. Google credentials are not needed on
LinuxONE; SDK imports are lazy and account forwarding uses Flask/itsdangerous only. Do not
upgrade the instance's pandas/numpy/model packages.

## 4. Set Vercel environment variables

Open the existing **ibmsubmission** project → **Settings → Environment Variables**.

| Variable | Production | Preview |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Google's web Client ID | same ID, or a separate configured test web client |
| `GOOGLE_CLIENT_SECRET` | matching secret | matching secret |
| `FLASK_SECRET_KEY` | private value generated in step 3 | same value as the backend for this demo |
| `AUTH_BASE_URL` | `https://ibmsubmission.vercel.app` | exact stable preview origin from step 2 |
| `REGISTER_FORWARD_URL` | existing LinuxONE base URL | same durable backend URL |

Scope the Preview `AUTH_BASE_URL` to the test branch if other branches exist. Redeploy the
preview after changing variables: existing deployments do not acquire new environment values.
Do not change `REALTIME_URL` or create a second Vercel project. `SITE_URL` on the instance
stays the production origin so welcome/alert email links point to the public site.

If sign-in starts on an origin different from `AUTH_BASE_URL`, the app moves to the
configured origin before creating OAuth state. This prevents callback cookies ending up
on a different host. Production and preview cookies are separate.

## 5. Update the LinuxONE registration backend

The backend must run the same account protocol before the website can save registrations.
Pull the reviewed PR branch in `~/heatahead/site` (coordinate with its owner; preserve their
local work), then add the private environment file to the existing systemd service:

```sh
sudo mkdir -p /etc/systemd/system/heatahead-web.service.d
printf '[Service]\nEnvironmentFile=%s\n' "$HOME/.config/heatahead/accounts.env" | sudo tee /etc/systemd/system/heatahead-web.service.d/accounts.conf > /dev/null
sudo systemctl daemon-reload
sudo systemctl restart heatahead-web
```

This adds a drop-in and preserves the service's current SMTP and data configuration. On a
failed restart, read its service log; do not change model dependencies. `/api/health` on
the instance must report `"account_protocol":1`. An old backend or mismatched key produces
a visible 503 instead of falsely claiming a building was saved. The schema adds only an
`account_request_nonces` table; it does not delete or rebuild existing users or alerts.

Account requests and replies are signed, bound to their exact payload/method/URL, expire
after 60 seconds and reject reused nonces. **The current plain HTTP instance URL does not
encrypt registration data.** Prefer an HTTPS backend or encrypted private transport for
production confidentiality. No Google tokens, Google password or client secret is sent
to LinuxONE. Do not describe the existing HTTP transport as confidential.

## 6. Check before merging

Local checks (Python 3.10+ with `pip install -r requirements.txt`, Node 18+):

```sh
python -m compileall web api
python -m unittest discover -s web/tests -v
node web/tests/test_map.cjs
```

In the actual preview, with a Google account allowed by the consent configuration:

1. Signed out: map, building lookup and monitor still open. Google button starts Google.
2. Complete Google sign-in. Your verified email and **Sign out** appear.
3. Save an actual mapped BBL such as `3000410007`; reload and see it under saved buildings.
4. Close/reopen the tab with Remember enabled: still signed in. Sign out and sign in
   again with the same account: the building remains. Another Google account cannot see
   that registration. Browser privacy settings can remove cookies earlier than 30 days.
5. Cancel a new Google sign-in and retry; show a friendly result. Never paste callback
   URLs containing `code=` into chat or screenshots.
6. Remove a saved building. Recheck the list. A GET unsubscribe link only shows confirmation.
7. Click a multi-building map hexagon: list all members across pages. Click a list link:
   correct building page, including imagery and owner/draft features. Check mouse-wheel,
   trackpad, drag and repeated 2D/3D zoom on the team's actual computers.

Then merge the PR, let Production redeploy with its Production environment, return the
instance clone to current `main`, restart its web service and repeat sign-in/save/reload
on <https://ibmsubmission.vercel.app>. A local provider fixture is not a real Google
end-to-end deployment test; actual credentials, provider policy and hosting must be checked.

## Common setup failures

- **Google button disabled:** check all three secrets/config values, `AUTH_BASE_URL`,
  Google SDK installation and that you redeployed after setting the environment.
- **redirect_uri_mismatch:** Google Clients must contain exactly the callback for the
  current `AUTH_BASE_URL`. A preview callback does not authorize Production, or vice versa.
- **Access blocked:** check Google's Audience/Test users and any school Workspace policy.
- **Signed in, but save/load fails:** inspect `/api/health` on the website and instance,
  confirm the instance runs the new code and the exact same shared signing key.
- **Signed out after every deploy:** do not regenerate `FLASK_SECRET_KEY` on startup.
  Also check browser cookie settings and that you return to the same deployment host.
