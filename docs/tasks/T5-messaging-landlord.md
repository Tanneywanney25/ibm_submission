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

- [ ] Building page shows owner + portfolio + (if pulled) agent address
- [ ] Draft button produces the templated notice with correct numbers
- [ ] A landlord-role user sees drafts for THEIR buildings framed as self-audit

**Depends on:** T1. **Feeds:** roadmap slide; landlord role value.
