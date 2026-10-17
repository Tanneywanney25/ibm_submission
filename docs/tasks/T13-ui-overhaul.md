# T13 — UI overhaul: the Opendoor standard

## Goal

Make the whole site look genuinely good — clean, confident, product-grade — by
stealing the *craft* of opendoor.com directly: generous whitespace, one big
clear headline per screen, soft rounded cards on a near-white background, a
single accent color used sparingly, large friendly form fields, sticky simple
nav, photography-free trust sections. HeatAhead keeps its own identity (the
building-architecture motifs stay), but every page should feel like it shipped
from a design team.

## What already exists

- `docs/design-language.md` — the current building-materials palette and the
  skyline/elevation components (`bldg()`, `litSet()`, `skyline()` in
  `web/templates/base.html`). These are kept, refined, not removed.
- All pages in `web/templates/`; styles live in the base template.
- The deploy contract: `docs/VERCEL.md` §3 (URL paths frozen) and §6 (smoke
  test before any push to main).

## What to take from Opendoor, concretely

- Layout: max-width ~1100px content column, 80–120px vertical rhythm between
  sections, cards with 16–24px radius and barely-there shadows.
- Type: one display size for the hero ("Know which buildings lose heat —
  before the cold arrives"), calm 16–18px body, no more than two weights.
- Color: keep the brick/limestone palette but push backgrounds near-white;
  one warm accent for primary actions only; everything else neutral.
- Components: pill buttons, quiet input fields with floating labels, step
  explainer ("Enter address → see risk → get alerts") like Opendoor's
  how-it-works row, sticky header that shrinks on scroll.
- Tone: short sentences, verbs first, zero jargon above the fold.

## Contracts (never bend)

- **Features and URLs unchanged** — this is a reskin, same rule as the first
  design pass. Any page works identically before/after.
- LITE mode must stay static-friendly: no new build step, no client framework;
  CSS/JS stays inline or in `public/`.
- Update `docs/design-language.md` in the same commit (shared contract).
- Risky visual work goes on a branch; Vercel gives it a preview URL.

## Steps

1. Screenshot-audit every page (desktop + 375px mobile) and list the ten
   worst offenses.
2. Rebuild the shared shell in `base.html`: nav, footer, spacing scale, type
   scale, buttons, cards, form fields — as CSS custom properties.
3. Page passes: landing/hero → building page → dashboard → auth screens.
4. Smoke test per VERCEL.md §6, check the preview URL on mobile, then main.

## Acceptance

- [ ] Every page passes a 375px-width check with no horizontal scroll.
- [ ] One accent color; all CTAs use it; nothing else does.
- [ ] Building motifs still present (hero skyline, elevation card, skybars).
- [ ] `docs/design-language.md` updated in the same commit.
- [ ] VERCEL.md §6 smoke test green before the main push; no deploy break.
