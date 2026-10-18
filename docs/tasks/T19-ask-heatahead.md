# T19 — Ask HeatAhead: an LLM assistant over our data

## Goal

Replace the raw "latest complaints" list with a chat box where anyone — a
homebuyer, a tenant, a city staffer — asks in plain language and gets a
grounded answer from *our* data: "how risky is 345 E 15th St this winter?",
"which buildings in Bushwick should an inspector see first?", "has this
landlord's stock been getting worse?", "what does 'very high' actually
mean?". The assistant is the fast path to the right building page, map view
or queue — every answer links there.

## Shape

- **Server-side only.** A new endpoint (e.g. `POST /api/ask`) calls the LLM
  (Claude API) with a system prompt + *tools*; the key lives in Vercel env /
  the instance env file, never in the repo or the browser.
- **Tool-calling, not a data dump.** The model gets tools that wrap what the
  site already serves: building lookup by BBL (`/data/b/` records),
  GeoSearch address→BBL (T17), the ranked queue slice by CD/borough, the
  season reliability table, and the methods copy (`docs/about-copy.md`) for
  "what does this number mean" questions. It answers only from tool results.
- **Answers carry receipts**: every claim about a building names its BBL and
  links the building page; aggregate claims name the slice ("top 50 in
  CD 106"). "I don't have that" is a valid answer.
- **UI**: the chat panel takes the complaints-feed slot on the dashboard and
  the landing page; suggested starter questions per audience; streaming
  responses.

## Guardrails (hard, in the system prompt AND enforced in the tool layer)

- Building-level only. Tools never return apartment numbers; the prompt
  forbids speculating about units or tenants.
- Probability language mirrors the site: calibrated, capped at 99%, banded
  above 20% ("roughly 94–99%"), never invented precision. The model quotes
  what the tool returned, never recomputes risk.
- No legal, financial or medical advice; no landlord-shaming beyond what the
  public HPD record says; T5's "drafted, nothing sent" boundary holds.
- Mega-lot honesty from T18: when a tool returns a flagged complex, the
  answer says so ("one lot covering ~90 buildings").
- Rate-limit per IP/session; cap tokens per answer; log Q&A (no PII) on the
  instance for the demo reel.

## Contracts

- Secrets never enter the repo (CLAUDE.md). LITE on Vercel calls the LLM
  API directly; FULL on the instance reads the key from the alerts env file
  pattern.
- Frozen numbers untouched — the assistant *reads* outputs, it never scores.
- Any new URL path or `public/data/` artifact updates VERCEL.md in the same
  commit.
- Vercel function limits apply: stream the response; stay inside the request
  body limit; no new heavy Python deps in `requirements.txt` without checking
  the deploy still builds.

## Steps

1. Tool layer: pure functions over existing data paths (lookup, geosearch
   proxy, queue slice, reliability, methods snippets) with tests — these are
   useful even without the LLM.
2. `POST /api/ask`: Claude tool-use loop, streaming, system prompt in a repo
   file (`web/ask_prompt.md`) so it is reviewable; temperature low.
3. Front end: chat panel component replacing the complaints list; starter
   chips ("Check an address", "Riskiest near me", "How the model works");
   every building mention rendered as a link.
4. Red-team pass: apartment-number fishing, prompt injection via address
   strings, "guarantee my building will fail" phrasing, off-topic requests —
   document the behavior in the task PR.
5. Demo script: three questions (homebuyer, tenant, gov) for the video.

## Acceptance

- [ ] "How risky is <address> this winter?" resolves via GeoSearch and
      answers with the same banded number the building page shows, linked.
- [ ] A question about an apartment or a tenant is declined, building-level
      answer offered instead.
- [ ] Stuy Town-class lots are described as complexes (T18 flag honored).
- [ ] Works on the Vercel deploy (streaming, no key in client bundle) and in
      FULL mode on the instance.
- [ ] Red-team notes in the PR; rate limit verified with curl.
