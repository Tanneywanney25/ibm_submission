# Learn more, FAQs and Ask HeatAhead

## What ships immediately

- `/learn-more`: purpose, the three-step process, map colors vs heights, prediction
  windows, limitations, tenant/owner/inspector actions, sources and privacy.
- `/faq`: 26 categorized answers, text search, topic filters and openable URL fragments
  such as `/faq#heights`. Native `<details>` work without JavaScript.
- An **Ask HeatAhead** guide on every page: questions, published answers, source links,
  follow-up suggestions and explicit navigation buttons. It preserves the current valid
  building BBL in building-page links and can recognize a typed `BBL 3000410007`.
- Learn more and FAQ navigation links, a home-page entry point and footer links.

No new Python dependency, database, Node build step or key is needed for these features.
The Google login work remains intact and can be configured separately.

## Optional real AI matching

Common questions are answered locally. If the site's owner wants AI to interpret unfamiliar
wording, add these to the **existing** Vercel project's environment:

1. `OPENAI_API_KEY`: a project-scoped API key, entered directly into hosting settings.
2. `GUIDE_AI_MODEL`: the id of an active model in that project that supports the Responses
   API and Structured Outputs. Select from the current model catalog; do not assume an old
   model name is still supported. <https://developers.openai.com/api/docs/models>

Redeploy the preview after setting them. Do not paste a key into chat, a notebook, browser
JavaScript or GitHub. Enabling this public endpoint consumes provider credits. Configure
provider spending/rate limits and hosting controls; the in-app limits are per warm worker,
not distributed or a guarantee against total spend. Leaving both values unset keeps the
working local guide and makes no external AI calls.

The provider sees only the current general question and previous FAQ topic id, with BBLs
redacted. The shared question titles are the classification vocabulary. It selects a
schema-constrained topic id. The response renderer uses the catalog answer and allowlisted
links, never provider-written facts or URLs. Refusal, timeout, malformed output, unrecognized
topics and rate limits fall back to the existing FAQ/shortcut flow. No agent tools or
write permissions exist. There is no conversation persistence or Google identity in this
request. `store:false` does not change the provider's own applicable retention policies.

Official API contract: <https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses>.
The provider path has fixture tests, but a real API-key/model deployment must still be tested.

## Content ownership

Edit `web/static/guide-content.json` to update an answer, its search phrases, links or
follow-ups. Both FAQ and assistant use it. Keep ids stable so bookmarked FAQ anchors work.
Use building-level information, honest prediction windows and existing display rules.
Do not call a reported complaint a confirmed outage. Do not promise that an email will
arrive while the team's alert service is not configured. Roles are view preferences,
not verified owner/inspector credentials. The guide must never invent a risk score.

NYC action guidance was checked against these official pages on October 17, 2026:

- <https://portal.311.nyc.gov/article/?kanumber=KA-01036>
- <https://www.nyc.gov/site/hpd/services-and-information/heat-and-hot-water-information.page>

## Validate and upload

```sh
python -m compileall web api
python -m unittest discover -s web/tests -v
node web/tests/test_guide.cjs
node web/tests/test_map.cjs
```

Use a new branch from current `main`, upload the changed `web/` and `docs/` contents in
their original paths, and review the preview before merging. The zip contains only this
update; it does not re-upload account/map files that were not modified. Do not upload
the surrounding download folder, databases, keys or test dependencies.

Preview checks:

1. Open `/learn-more` and `/faq` from the home page and the shared navigation.
2. Search FAQs for `height`, filter Accounts and alerts, then open `/faq#no-heat` directly.
3. Open the guide by mouse and keyboard. Ask how to check a building, get alerts, draft a
   notice, inspect the queue and interpret map heights/colors. Follow its links.
4. Open a building BBL, ask about its risk, and confirm the shortcut retains that BBL.
5. Ask an unrelated question: get a useful fallback, not a made-up answer. Clear chat and
   confirm it resets; close and reopen within the page to continue the same conversation.
6. Test a narrow phone screen and Escape/focus behavior. Disable JavaScript and verify
   the Learn more and FAQ content remains readable. Check the map and its area panel.
7. If AI is enabled, ask an unfamiliar paraphrase, confirm a grounded FAQ answer and its
   AI-matching status. Simulate an unavailable provider and verify the fallback. No API
   key may be present in page source or browser request payloads.

Live WebGL appearance, actual-device interaction, and a configured provider are preview
checks, not things the local Python/Node fixtures can prove.
