# Help chat and Learn more

## What changed

The separate FAQ page is retired. Help in the navigation, footer and home page opens
Ask HeatAhead on the page the visitor is already using. Inside the chat:

- **Ask a question** answers clear requests and offers nearby published questions when
  wording is unclear or misspelled.
- **Browse questions** holds all 26 original answers plus newsletter, team contact and
  cookie choices: 29 in total. Search accepts nearby spelling; a topic filter narrows
  the list. Choosing a question opens its answer in the conversation.
- Answers keep the existing source links, action shortcuts, follow-up questions and
  valid building BBL. Choosing a suggestion does not submit a complaint, change an
  account, send mail or run a model.

The same catalog lives in web/static/guide-content.json. There is no second copy of
the answer text in the JavaScript or templates. No database, build step or new
production dependency is needed. The newsletter/contact/cookie features remain intact.

## Matching and uncertainty

Clear questions still use the existing published terms and specific intent rules.
Local retrieval also compares meaningful words in titles/keywords, common aliases
(photos/pictures, colors/colours, notifications/alerts) and bounded edit distance for
nearby spelling and swapped letters. The catalog index is cached within the page.

Uncertain spelling produces **Did you mean** options rather than silently answering a
guessed question. Broad requests such as email, risk, contact and unsubscribe present
several relevant choices. For example, "email" can mean building alerts, project updates,
sign-in or drafting a notice; "stop emails" distinguishes building alerts from the
newsletter. Only credible catalog matches are offered, up to four. A single close
spelling match can have one option; unrelated questions get a browse/contact fallback.

This is a local help guide, not an unrestricted generative chatbot. It never invents
building scores, provider-written answers or arbitrary URLs. Obvious no-heat/emergency
questions keep their direct action guidance. General follow-ups can refer to the last
selected help topic. The conversation stays in memory for that page, is bounded to 24
message elements, and clears on navigation or Clear chat. No chat localStorage is used.

## Links and accessibility

- Any site page can use ?help=TOPIC-ID to open that answer, or ?help=1 to open Browse
  questions. Valid topic ids come from the catalog.
- /faq redirects with 302 to /learn-more?help=1. A browser preserves an old #topic-id
  fragment, which the chat recognizes. New site links do not point to /faq.
- Map coverage links open the unranked explanation in place, retaining the current map.
  Building action links retain the selected valid BBL.
- Both tabs support keyboard arrows, Home and End. Escape closes help and returns
  focus; suggestions focus a question for keyboard selection. Closing and reopening
  within the page preserves the conversation.
- The undecided cookie banner temporarily hides while help is open, preventing it from
  covering the chat on small screens. It returns when help closes. This records no
  consent and enables no optional storage, including when a help deep link opens before
  the privacy widget finishes initializing.
- Without JavaScript, Learn more shows the same answers as native details. Contact and
  project-update links still work. The chat itself needs JavaScript.

The unused web/templates/faq.html is deleted in this change. A GitHub file-upload update
may leave the old file in the repository; no route renders it, so the separate page is
still removed. The redirect handles old links without requiring a manual deletion.

## Optional AI matching

The default guide and all 29 questions work with no key. If the owner enables the existing
provider integration, OPENAI_API_KEY and GUIDE_AI_MODEL stay server-side in the current
Vercel project. Choose an active model that supports the Responses API and Structured
Outputs from the official model catalog; no silently assumed model name is included:

- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses

Local matches and ambiguous choices do not call the provider. An otherwise unrecognized
general question may call the existing same-origin POST /api/guide/ask. The provider can
only suggest one allowlisted topic id. It appears as a possible question for the visitor
to choose; it does not automatically become an answer. The API shape remains
{topic, mode}, so an older configured provider endpoint stays compatible.

Only the current cleaned question and previous topic id enter the provider input. Valid
BBLs are redacted; obvious contact/unit details and secrets are rejected. Account identity
and earlier chat messages are not included. The application stores no conversation and
logs no provider errors/questions/keys. store:false does not override provider retention.

The endpoint retains a 400-character cap, a seven-second browser deadline, bounded server
timeout/output and warm-worker limits of five requests/client/minute and 20 total/minute.
These are not distributed quotas or a global spending cap; configure provider/hosting
limits before enabling it. Refusal, invalid topic, timeout, 429 and offline service leave
the local help questions available. Clear chat, Browse questions and newer questions
invalidate pending responses, so late results cannot overwrite the new interaction.

## Content ownership

Edit guide-content.json for question titles, answers, terms, keywords, action links and
follow-ups. Keep all original ids stable for legacy links. New help questions should use
the existing schema and supported public paths. Keep map color/height/coverage explanations
consistent with the map and Learn more. Missing color is not proof of no complaints or
working heat; reported complaints are not confirmed current outages.

Keep accounts and building heat alerts separate from project-update subscriptions.
Dashboard panels do not verify an owner's or inspector's identity. Preserve the published
monitor versus historical replay distinction, honest prediction windows, calibrated display
rules and frozen submission metrics. The guide must never invent a risk score or promise
delivery while an email service is unconfigured.

Heat-action sources remain the official NYC pages:

- https://portal.311.nyc.gov/article/?kanumber=KA-01036
- https://www.nyc.gov/site/hpd/services-and-information/heat-and-hot-water-information.page

## Test and upload

Use the project's Python environment with the pinned requirements/authentication test
dependencies. The DOM tests additionally need development-only jsdom, not a production
dependency:

    python -m compileall web api
    python -m unittest discover -s web/tests -v
    node web/tests/test_guide.cjs
    node web/tests/test_map.cjs
    node web/tests/test_live_monitor.cjs
    npm install --prefix /tmp/heatahead-dom jsdom@26
    NODE_PATH=/tmp/heatahead-dom/node_modules node web/tests/test_chat.cjs
    NODE_PATH=/tmp/heatahead-dom/node_modules node web/tests/test_privacy.cjs

The chat DOM test uses Python/Flask to render the real widget template. If the Python
environment has a different executable, set PYTHON to that interpreter before running it.

Upload the changed web/ and docs/ folders at the repository root on a new branch from
current main. Do not upload the surrounding download folder, keys or test dependencies.
Review the Vercel preview before merging. No new environment setting is needed for local
matching and browsing. Vercel renders its own help pages; restart the instance web process
as well if the team uses its frontend directly.

Preview checks:

1. Help opens Browse questions without leaving the current page. Check every category,
   a typo search, an empty result and selection of an answer.
2. Ask "email", "emial", "risk", "stop emails" and "map colors and heights": see choices.
   Choose one and verify the answer and shortcuts.
3. Ask clear building/map/action questions and an unrelated question. Verify BBL links,
   source links and the absence of invented answers or scores.
4. Open /faq#heights, /learn-more?help=1 and /building?bbl=3000410007&help=alerts.
5. Test keyboard tabs, Escape, focus return, Clear chat and a narrow screen. Cookie
   choices must remain undecided when opening/closing help.
6. With JavaScript disabled, read the answers in Learn more.
7. If AI is configured, verify a proposed topic requires selection; simulate downtime
   and a late response. No key belongs in page source or browser payloads.

Local tests do not prove actual-device layout, map GPU rendering or real provider quality;
those remain preview checks. No automated test sends real mail or files a city complaint.
