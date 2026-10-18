# Newsletter, contact and cookie choices

The home page now has a project-update form: optional name, required email and Subscribe.
The footer links to that form, `/contact`, `/privacy` and Cookie settings. The public team
address is **heataheadnyc@gmail.com**. Contact links open the visitor's own email app.
They do not automatically send a message.

## Deployment: the frontend and instance must both update

1. Upload this patch to a branch and open its Vercel preview. Check the form, contact
   links and cookie choices. A preview without backend configuration deliberately says
   newsletter signup is being set up; it must not claim a signup was saved.
2. Merge after reviewing the preview. On the existing account instance, pull the same
   code and restart its web service:

   ```bash
   cd ~/heatahead/site
   git pull --rebase origin main
   sudo systemctl restart heatahead-web
   ```

3. Keep the existing `REGISTER_FORWARD_URL` on Vercel. Both targets need the same stable
   `FLASK_SECRET_KEY` (32+ characters). Keep `SITE_URL` on the instance set to the public
   HTTPS website, not the instance's HTTP address.
4. The instance needs working `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` and `SMTP_FROM` values;
   `SMTP_PORT` defaults to 587. Reuse the existing mail service. `SMTP_FROM` must be a
   sender the provider permits; the team Gmail is the Reply-To, not an invented SMTP
   credential. Configure secrets privately in the service environment, never in code,
   GitHub upload files or chat. Restart after changing the environment.
5. Check `/api/health`: `newsletter_protocol` should be `1` on both targets and
   `newsletter_delivery_ready` true on the instance and public site. This checks settings
   and backend version, not whether SMTP credentials work. Test delivery once with a
   team-controlled address using the website after deployment.

An old backend returns a clear unavailable message. The form, map, account and contact
page continue to render. No new database service, package, Vercel project or background
worker is required. No model artifacts or public data shards change.

The current backend URL uses HTTP. Newsletter forwarding inherits that existing lack
of transport encryption; an HTTPS/private encrypted backend is needed for production
confidentiality, as with existing registration forwarding. Newsletter actions are public
opt-in requests and do not assert a signed-in identity or reuse the private account
forwarding protocol. They cannot create a login session or change building registrations.

## What a signup does

- Validate name/email and explicit Subscribe intent. A hidden honeypot discards common
  automated submissions. No phone, building, password or Google access is requested.
- Store a `pending` row in `newsletter_subscribers` in the instance's existing ignored
  `web/heatahead.db`. Emails are trimmed/lowercased and unique; name is optional. Store
  request/confirmation times, status and the consent wording version.
- Send one confirmation email. A ten-minute resend cooldown lives in SQLite. Each warm
  worker also allows at most 20 sends/minute; this is not a distributed spam quota. Add
  host/provider rate limits if public traffic needs them.
- A confirmation URL opens a page. The visitor must press Confirm subscription before
  the row becomes `subscribed`. Confirmation expires in 24 hours. Email scanners visiting
  links cannot opt anyone in or out.
- The signed links contain a random subscriber id, never an email address. Confirm and
  unsubscribe use different signing purposes. Unsubscribe doesn't expire, needs no login,
  and invalidates outstanding confirmation links. Old unsubscribe links still work after
  rejoining. A new signup after unsubscribing can request a link immediately and must
  be confirmed again; the resend cooldown applies to pending signups.
- Signup responses do not reveal whether an address was already subscribed or allow an
  anonymous request to overwrite an active subscriber's name. Existing subscribers get
  the same generic receipt without another confirmation email.
- Newsletter status is separate from `users` and `alerts_sent`. Signing in, saving a
  building and subscribing do not silently opt a person into the other email stream.

GET management pages and all newsletter API responses use `Cache-Control: private,
no-store` and `Referrer-Policy: no-referrer`. Confirmation tokens can still enter hosting
request logs; restrict those logs as account-link logs are restricted.

### Failures are visible

Missing SMTP/shared secret, missing durable backend and storage failures return 503;
they never report a successful subscription or use Vercel's temporary filesystem.
SMTP failure leaves the row pending and allows a retry after one minute. Forwarding
has a two-second connection and six-second read timeout; a slow or failed request may
still deliver an email from the backend, so a visitor should check their inbox before
retrying. The resend cooldown prevents an immediate duplicate email. Tokens are sent
only when SMTP is configured; this module never uses the mailer's print-only demo mode.

This patch captures confirmed consent and sends confirmation emails. It does **not** send
campaigns or automatically mail the subscriber list. There is no public list/export API.
When a campaign sender is added, select only `status='subscribed'`, recheck status at send
time and include the subscriber's signed `/newsletter/unsubscribe?token=…` link. Do not
export or commit subscriber data. Before promotional campaigns, the owner must supply
an appropriate postal address and sender/unsubscribe details; none are invented here.

## Cookies and browser storage: what the controls actually govern

| Item | Role | Choice/lifetime |
| --- | --- | --- |
| `heatahead_account` cookie | Essential sign-in/security, HttpOnly, Secure, SameSite=Lax | Up to 30 days when remembered, otherwise browser session capped at 12 hours; rejecting optional storage doesn't delete it |
| `heatahead_privacy` localStorage | Necessary record of the visitor's storage choice | Versioned, expires after 180 days; if storage is blocked, choice applies in memory for that visit |
| `heatahead_panels` localStorage | Optional dashboard fallback | Off before consent; read/write only after acceptance; removed on rejection or next visit after choice expiry |

Accept all, Reject optional and Settings are equally available. Settings leaves the
optional checkbox off initially and always offers rejection. Reopen from the footer or
privacy page. The dialog supports Escape, focus return and Tab wrapping. There is one
banner on the outer page, never a second banner inside the building-map iframe.

Explicit account preferences still save to the server with the existing authentication
and CSRF checks after optional storage is rejected. If the server is down, choices last
for that visit unless optional local storage was accepted. Rejecting clears any legacy
local panel copy; it doesn't remove saved buildings or account preferences.

No analytics or advertising code was found in `web/`, `api/` or `public/` during the
October 18 review. Do not add pretend analytics toggles. Maps, imagery and address search
still make the existing external requests (unpkg, CARTO, Esri/ArcGIS and NYC GeoSearch).
These providers' own practices are outside the optional dashboard-storage toggle; the
banner/settings and privacy page say so. Re-audit and update consent before adding a
nonessential tracker or embed. This implementation is not a blanket legal-compliance
certification for every jurisdiction or provider.

Official background reviewed October 18, 2026:

- [ICO: storage/access choices and consent](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/how-do-we-comply-with-the-pecr-rules/)
- [FTC: commercial email sender and unsubscribe requirements](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business)

## Checks

```bash
python -m compileall web api
python -m unittest discover -s web/tests -v
node web/tests/test_map.cjs
node web/tests/test_guide.cjs
node web/tests/test_live_monitor.cjs
npm install --prefix /tmp/heatahead-dom jsdom@26
NODE_PATH=/tmp/heatahead-dom/node_modules node web/tests/test_privacy.cjs
```

Python uses the existing pinned authentication test dependencies. JSDOM is a development
dependency for the last test only; it is not bundled with the website. Tests mock all mail
delivery and newsletter upstream calls. They cover opt-in state, scanner-safe GETs, token
expiry/purpose, opt-out/rejoin replay, forwarding to durable SQLite, unavailable services,
input/origin checks, resend/budget limits, default-off storage, rejection, blocked storage,
cross-tab withdrawal, modal keyboard behavior, account saving and form error/retry states.

In the branch preview, check a narrow screen and desktop, first visit and returning visit,
all three cookie buttons, footer contact links and the form's loading/error state. On
production after coordinated rollout, use a team-controlled email to confirm, unsubscribe
and verify that building alerts remain as selected. No automated test sends real mail.
