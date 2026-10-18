# HeatAhead design language: bold, bright and civic

The graphic-design contract for every page, slide and screenshot. It replaced the dark
"winter night" theme on October 17, 2026 (branch `ui-redesign-green`). The shared
stylesheet is `web/static/site.css`; page templates add only page-specific rules on top
of it, and they use its tokens rather than hard-coded colors.

The look borrows from two reference sites the team liked. The first gave us the typeface,
the rounded cards and the uppercase pill buttons. The second gave us the bright tints, the
thick dark outline around every card and button, and the hover effect where a solid
diagonal shadow slides out behind a button as it lifts.

## 1. Color

One brand color, a small set of bright tints, and a near-black ink for outlines and text.

| token | value | use |
|---|---|---|
| `--accent` | `#0B7A51` (hsl 158 84% 26%) | the brand green: primary buttons, links, active states, key numbers |
| `--accent-dark` / `--accent-soft` | `#075C3C` / `#DDF3E8` | link hover; tinted panels such as the hero and the lookup card |
| `--ink` | `#072A20` | text, the 3px card and button outlines, the hard hover shadow, the footer |
| `--muted` | `#4A675D` | secondary text (5.9:1 on white) |
| `--bg` / `--panel` / `--well` | `#F4FAF7` / `#FFFFFF` / `#EEF6F1` | page background, cards, inputs and quiet surfaces |
| `--line` | `#D5E6DD` | hairline dividers inside cards |
| `--sun`, `--sky`, `--coral`, `--mint` and their `-soft` versions | `#FFD98F`, `#BDF3F7`, `#FF8A80`, `#B7EBD2` | stat tiles, chips, step badges, the hero's bottom stripe |

The tints are decoration only. Any tint that carries meaning ships with a word beside it,
so color is never the only signal.

### The risk map keeps its own scale

The map's hexagons, property dots and legend keep the fixed pale-blue `rgb(219,239,255)`
to deep-blue `rgb(27,92,180)` scale on the dark basemap (`docs/VERCEL.md` section 10). Only
the controls around the map follow this theme. The Learn more page's map key uses the same
blue ramp so it matches what people see on the map.

The building page shows a building's winter risk on a meter that runs from mint through
sun to coral. The pin sits at the capped calibrated probability, and the banded text from
`fmtRisk()` stays above it, so the display rules in `docs/webapp-spec.md` still hold.

## 2. Type

One family, Bricolage Grotesque (SIL Open Font License), self-hosted from
`web/static/fonts/` so the browser never calls a font CDN (`docs/VERCEL.md` section 6,
rule 1). Headings use weight 800 with slightly tight letter-spacing; body text uses 400 at
16px with a 1.55 line height. Buttons and small labels are uppercase with wide tracking.
Numbers use tabular figures.

## 3. Surfaces and components

- **Cards** are white with a 3px `--ink` outline, an 18px radius and a soft drop shadow.
  Cards people can click or scan lift 4px on hover.
- **Buttons** use the brand green with white text and a 3px ink outline. On hover they move
  up and left by 3px while a solid 5px ink shadow appears behind them; on press they settle
  back. Secondary buttons are white with ink text. Any unclassed `<button>` gets this style
  automatically; utility buttons such as map zoom, FAQ filters and guide follow-ups set
  their own.
- **Inputs** have a 2px outline, a 12px radius and a green focus ring.
- **Header**: white, sticky, ink bottom border, the green house mark, pill-shaped page links,
  the address search and a Sign in button.
- **Footer**: dark ink with site links, the 311 link and the LinuxONE status line. The
  decorative skyline strip that used to sit above the footer is gone.

## 4. What was removed

The lit-window building drawings are gone everywhere: the hero skyline, the footer skyline,
the building-page elevation and the window-grid history bars. The hero now shows the real
held-out result as a grid of 100 dots, 86 of them filled, and the history charts are plain
rounded bars with the latest season in green.

## 5. Tone

Copy stays calm and plain: competent, on the tenant's side, not selling anything. The
bright tints make the site feel friendly; the numbers stay blunt and exactly as measured.
