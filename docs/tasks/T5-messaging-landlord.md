# T5 — Landlord contact + drafted messages (LATER / stretch)

**Goal (end state):** from a building page, see who's responsible (registered
owner/agent from public HPD records) and generate a ready-to-send message — an
AI-drafted email like "Claude-bot" eventually. **Explicitly a stretch feature:
build T1–T4 first; ship T5a only if time remains.**

## Phased

### T5a — show the responsible party (cheap, do if T1–T4 are done)
- `data/second_tier/bbl_landlord.csv` already maps bbl → owner name + portfolio
  size; `web/app.py`'s building payload already includes it
- To add business address / agent: re-pull HPD contacts with more columns
  (dataset feu5-w2e2: `businesshousenumber, businessstreetname, businesscity,
  businessstate, businesszip, type='Agent'`) — same curl pattern as
  `model/00_second_tier.py` documents
- Display on the building page: "Registered owner: X (owns N buildings) ·
  Managing agent: Y, address Z" — all public record, business addresses only

### T5b — template-drafted message (exists as a stub)
- `GET /api/draft_message/<bbl>` in `web/app.py` already returns a templated
  notice (risk %, rank, complaints, the heat-season legal line). Wire a
  "Draft a notice" button on the building page that shows it in a copyable box.
  **Nothing is auto-sent** — the user copies it.

### T5c — AI-drafted, personalized (post-hackathon)
- Swap the template for a Claude API call (model `claude-sonnet-5-5`) fed the
  building payload JSON; same endpoint shape, `note: "draft only"` stays
- Needs: API key handling, rate limits, a human-in-the-loop send step —
  which is why it's post-hackathon. Mention it in the video as roadmap, one line.

## Guardrails (hold even in the demo)

- Public business records only — never personal phones/emails we don't have
- Drafts are framed as notices from the user, not accusations from the system
  ("modeled chance", "we encourage an inspection")
- No auto-send anywhere; a human presses send in their own mail client

## Acceptance (T5a+b)

- [x] Building page shows owner + portfolio + (if pulled) agent address
- [x] Draft button produces the templated notice with correct numbers
- [x] A landlord-role user sees drafts for THEIR buildings framed as self-audit

**Depends on:** T1. **Feeds:** roadmap slide; landlord role value.

## What shipped (October 17, 2026)

**Data (T5a).** `web/build_contacts.py` pulls the 161,136 managing-agent and 125,548
corporate-owner rows of `feu5-w2e2` on the LinuxONE guest (about 30 s) and joins them to the
owner already in `bbl_landlord.csv` through the same registration id, so owner and agent
always describe one filing. It writes `data/second_tier/bbl_contacts.csv` (178,241 lots)
and never touches `hpd_contacts.csv` or `bbl_landlord.csv`, which feed the frozen model.
The pipeline runs from `web/jupyter/T5_landlord_contacts.ipynb` inside the team's
JupyterLab (`datathon-env` kernel), and the executed notebook is committed with its outputs.

| of the 63,727 ranked buildings | share |
|---|---|
| registered owner on file | 94.4% |
| managing agent on file | 84.7% |
| agent business street address (agent files as a company) | 54.0% |
| owner business street address (owner is a corporation) | 75.8% |
| link to the full HPD Online registration | every registered building |

Privacy choices, stricter than the guardrails require: a street address appears only for a
company, because a person's "business" address may be a home, so an agent filed as a
person shows a name and a city and the user follows the HPD Online link for the rest. The
`businessapartment` column is never pulled; a unit typed into a street, city or name field
is cut (`#3A2`, `apt.# 11`), and a sweep of every shipped record finds none left.
Registration end dates are not shown: the Open Data snapshot's newest filing is
2026-07-31, so September renewals look like lapses.

**Drafts (T5b).** `/api/draft_message/<bbl>?as=tenant|landlord&address=` (contract in
`docs/VERCEL.md` section 3). The stub this replaced quoted the wrong season for Building
60119 (2 complaints so far in 2026-27 instead of 127 in 2025-26), rounded the risk unlike
the page and signed as HeatAhead. Now every number is one the building page shows,
`fmt_risk()` reproduces the page's `fmtRisk()` exactly, and the text is the user's own:
a resident's request for a heating check, or the owner's pre-winter self-audit with a
four-step checklist. The building page shows the draft in an editable box with Copy and
"Open in my email app" (a `mailto:` with no recipient; we hold postal addresses only).
The landlord sign-up landing links every portfolio building to its self-audit. The guest
drafts both framings for all 63,727 buildings in about a second (about 110,000 per second).

**T5c** stays roadmap: an AI-written draft would replace `draft_message()` in `web/app.py`
behind the same response shape, with `note: "draft only"` and the human send step kept.
