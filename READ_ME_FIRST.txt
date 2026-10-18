HeatAhead site update — October 18, 2026

Includes the deeper About page, top-50 inspection queue, duplicate account-tab removal,
and FAQ retirement with the helpful answers kept in the chat.

For the existing GitHub upload workflow:
1. Open this extracted folder.
2. At the repository root, upload the three inner folders: web, docs, public.
   Keep those names exactly. Do not upload this outer folder or rename web to web 2.
3. Suggested commit title: Expand About, add top-50 queue and simplify navigation.
4. Review the preview before merging.

After deployment check /about, /inspection-queue, /api/queue.csv?k=50, and /faq.
The logo goes home. Sign-in and saved buildings remain there.
The old /faq URL opens help; it no longer renders a separate FAQ page.

GitHub file upload does not delete old files. An old web/templates/faq.html left
in GitHub is unused by the updated route. It can be deleted through GitHub's
file menu later; that is not needed for the visible FAQ page to disappear.

The CSV is the first 50 records of the saved cold-day inspection ranking.
It is not the map's season-risk ranking, a live forecast or an official HPD schedule.
BBLs can identify lots containing multiple buildings. No new model was trained.

This update was synced with main through f1acaec and committed as d64a389.
It preserves the teammate's new address autocomplete and SMTP setup changes.
Checks passed: 52 backend tests, 24 page renders, 34 LITE route/asset checks,
local links/anchors, published calibration rows, CSV order, CSS parsing and
help/map/privacy regressions. Device visual review remains on the preview.
