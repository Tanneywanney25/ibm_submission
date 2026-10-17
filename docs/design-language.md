# HeatAhead design language — "a winter night in New York"

The graphic-design contract for every page, slide and screenshot. One sentence:
**buildings are the shapes, a lit window is the only warmth, and every number is
dead serious.** This is a civic tool people visit while worried — it borrows its
restraint from government sites (gov.uk, nyc.gov) and modern product sites
(Stripe, Linear): lots of neutral, one accent, color always *means* something.

## 1. The color budget (the most important rule)

A screen is **~90% neutrals, ~8% one warm accent, ~2% status colors.** If a
screenshot looks "colorful," it's wrong. Orange is never decoration, never large
fills, never gradients across sections — it is the lit window: small, warm,
meaningful against the dark.

### Palette — taken from what NYC buildings are actually made of

| token | hex | material | use |
|---|---|---|---|
| `--night` | `#101317` | night sky | page background |
| `--masonry` | `#1a1e24` | dark masonry | panels, cards |
| `--mortar` | `#272c34` | mortar lines | borders, dividers, input strokes |
| `--limestone` | `#e9e6e0` | limestone | primary text (warm off-white, not pure white) |
| `--concrete` | `#9aa0a8` | concrete | secondary text, labels, axes |
| `--slate` | `#5c636d` | slate | disabled, placeholders, grid lines |
| `--brick` | `#b65c3f` | weathered brick | the ONLY brand accent: links, active states, small highlights |
| `--window` | `#ffc46b` | a lit window at night | heat/risk emphasis ONLY: the glow in charts, high-risk markers, the flame mark |

Status (used only beside an icon + word, never color alone):
`--ok #4f9e7a` (tended, muted green) · `--warn #c9973f` (amber) ·
`--alert #c25450` (brick-red, not fire-engine).

Notes:
- `--brick` replaces the current `#ff6b35`: same warmth, desaturated to what a
  real brick wall looks like. The saturated orange reads "AI-generated SaaS";
  weathered brick reads "New York."
- `--window` is reserved for *heat itself*: lit cells in the building graphic,
  the hot end of the risk ramp, the dot on an alerting building. Never buttons,
  never headings.
- Pure white and pure black never appear; everything is slightly warm.

### The one allowed ramp

Risk severity = **slate → brick → window** (cold masonry to lit window). Three
steps max on any surface. No rainbows, no blue-to-red, no third hue anywhere.

## 2. The signature graphic: the building with lit windows

The one piece of art the site owns (hero, empty states, the favicon's spirit):
a **flat-front building elevation** — a simple dark rectangle grid of window
cells in `--mortar`, where **a handful of cells glow `--window`**. The glow is
soft (one subtle outer blur, low spread), like real windows at 11 PM.

- Hero: one wide low skyline band, 2–4 lit windows total across it. Quiet.
- Building page: the looked-up building drawn as its own elevation — height
  from floors, cells lit in proportion to risk ("your building, drawn from
  city records"). Data as picture, not decoration.
- History bars: season bar charts may take flat roofs and faint window grids —
  the skyline IS the chart. Current-season bar tinted brick; the rest masonry.
- Never: animated flames, flickering, mascots, isometric 3D illustration sets,
  stock photos of radiators or shivering people.

## 3. Typography

- One family: the system stack we ship (`"Segoe UI", system-ui`) or Inter in
  Figma. No display font, no serif. Government-plain.
- Hierarchy by size and weight only: 600/700 for headings, 400 for body;
  generous line-height (1.5); max text column ~70ch.
- **Numbers are sacred:** risk %, ranks, counts always in `--limestone` or
  `--brick`, tabular, never italic, never on a patterned background, never
  inside a building graphic. When someone checks their own building, the
  verdict must look like a lab report, not a poster.

## 4. Layout and surfaces

- Flat panels (`--masonry`) with 1px `--mortar` borders and 8–10px radius.
  No glassmorphism, no heavy shadows, no gradient cards — masonry doesn't glow.
- Density like a well-set government form: one column of content, 16–24px
  gaps, whitespace doing the hierarchy work.
- Buttons: primary = `--brick` fill with near-black text; secondary = outline
  on masonry. One primary button per view.
- The map keeps the dark basemap; its columns use the slate→brick→window ramp
  and nothing else.

## 5. Tone pairing (why this works for worried visitors)

The warmth lives in *words and the lit windows*, never in loud color:
"Know before the cold hits" · "we tell you first" · "one email per cold spell,
never more." Copy is warm; chrome is calm; numbers are blunt. A tenant at 2 AM
should read the page as: *competent, on my side, not selling me anything.*

## 6. Hard don'ts (the "looks AI-generated" list)

- No saturated orange floods, purple/blue gradients, neon glows, or more than
  one accent hue per screen
- No emoji in product UI or alert emails; no exclamation points in alerts
- No decorative illustrations of people; no stock imagery
- No color-only meaning (every status color ships with an icon + word)
- No rounded 3D blob art, no confetti, no dark-mode-with-rainbow-charts

## 7. Applying it to what's built (the migration is small)

Current `base.html` tokens → new values: `--bg:#101317`, `--panel:#1a1e24`,
`--line:#272c34`, `--ink:#e9e6e0`, `--muted:#9aa0a8`, `--accent:#b65c3f`,
`--ok:#4f9e7a`, `--bad:#c25450`, plus new `--window:#ffc46b` for chart/glow use
only. Everything else (layout, cards, nav) already complies — the site was
built on these bones. The Figma flow file should adopt the same swap.

## 8. Reference points (steal restraint, not style)

- gov.uk / nyc.gov — one accent, flat surfaces, text-first hierarchy
- Stripe docs / Linear — dark neutrals done quietly, color as meaning
- NYC Planning's PLUTO maps — civic data that trusts its typography
- Edward Hopper's night windows — the entire mood board in one painter
