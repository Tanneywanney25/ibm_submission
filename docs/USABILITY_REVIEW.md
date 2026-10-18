# Small usability update — October 18, 2026

Reviewed the seven public navigation tabs on the production site, an address lookup,
both monitor views, FAQ search and the shared guide. Based on main at `2d18f8d`.

| Tab | Its main job | Decision |
|---|---|---|
| Home | Start with an address | Keep its existing prominent search and current design. |
| Check a building | Understand the risk and choose a next step | Show risk and history before the large photo. Explain address/BBL input, provide a public example and add owner, draft and accuracy shortcuts. |
| Risk map | Compare nearby areas | Keep the existing controls, two-color legend and coverage explanation. No rendering changes in this update. |
| Live monitor | Read recent published reports or explore a past replay | Bound the 100-report list, keep its table headings visible and add section shortcuts. Label the replay heading and saved ranking download clearly. |
| Learn more | Learn how to use the site | Give it that title, link to methods and correct the inspector directions. |
| FAQs | Get a quick answer | Keep the working search/categories; update the shared answers for one account, email links and the two monitor modes. |
| About | Understand the project and its evidence | State this purpose near the top; preserve methods, results and metrics. |

The guide and FAQ still share the same 26 topic IDs. New links use existing routes;
no endpoint, data asset, dependency, model, sign-in configuration or map behavior changes.
T19's separate data assistant remains outside this update.

The example is the existing public record for 330 East 139 Street, Bronx,
BBL `2023010004`, verified through the site's address lookup. It is an example of
using the page, not a recommended inspection or a claim of an active outage.

## Local checks passed

- Python compilation and all 33 existing web tests.
- Guide matching (55 example questions and all 26 FAQ titles), guide DOM interactions,
  monitor rendering/offline retry, and the existing map interaction checks.
- 16 public/signed-in page renders with unique IDs and valid inline JavaScript.
- A fresh LITE server without model files: 24 routes/assets, map-data redirect,
  building records, notice drafts and CSV download.
- The actual building-page script with local fixtures: ranked, unranked, offline,
  address and autocomplete lookups, risk before imagery, owner/accuracy shortcuts,
  lazy map loading, draft generation and out-of-order responses.

The final rebase brought in task documents only; application code stayed the same.

## Preview checks before merging

- In the branch preview, confirm the risk card appears above the photo, the recent
  report list scrolls by mouse and keyboard, and its building-summary shortcut works.
- Check the narrow-screen layout on a real device before merging.

Google and email sign-in were unavailable on the public site during the review;
their provider setup still belongs to the account owner. The review browser reported
WebGL disabled, so live map rendering and frame rate could not be visually assessed.
