# Bloom Design System

A theme + component library for **AI-agent-generated structured HTML documents**. Bloom gives generated documents (reports, dashboards, articles, landing pages, decks) a consistent visual identity that feels **young, alive, and quietly futuristic** — without veering into corporate sterility or generic "AI bot" tropes.

> 青春活力 × 未来科技感 — youthful vitality meets future-tech.

The system is the work surface for an AI agent: when it spits out HTML, it should reach into Bloom for color, type, spacing, components, and 3D illustration scaffolding so the result looks designed, not auto-generated.

---

## What's in scope

Bloom is **not** a SaaS product UI kit. It's a styling layer that themes:

1. **Long-form articles / blog-like documents** — hero + body + figures + pull-quotes
2. **Reports & dashboards** — KPI cards, charts, tables, callouts
3. **Marketing / landing pages** — hero, feature grid, CTAs
4. **Slides** — title, content, comparison, big-quote, end card

Each surface uses the same underlying tokens (`colors_and_type.css`) and the same component vocabulary (rounded "pillow" cards, 3D blob illustrations, vibrant accent pills, soft inner shadows).

---

## Sources & inputs

This system was synthesized from two reference moodboards uploaded by the user:

- `uploads/审美提升｜这组国外UI设计建议反复观看_5_行云变变变_来自小红书网页版.jpg` — soft pastel cards, 3D rounded blob illustrations, friendly rounded sans, dark-pill bottom nav, peachy/lavender/mint tints, claymorphic stacks
- `uploads/审美提升｜这组国外UI设计建议反复观看_7_行云变变变_来自小红书网页版.jpg` — sticker-collage layouts on lime green, chunky rounded display type, hot-pink hearts, vibrant rainbow progress gradient on dark mode

The user's explicit direction:
> "icons尽量3D，避免棱角分明，我希望是圆润、流线型、曲度"
> *(Icons should be 3D where possible, avoid sharp angles — I want round, streamlined, curved.)*

No codebase, Figma, or production source was attached. **Everything here is original to Bloom**, derived from the moodboard direction.

---

## Index — what's in this folder

```
README.md                  ← you are here
SKILL.md                   ← agent skill entry point
colors_and_type.css        ← all design tokens (CSS vars) — start here

fonts/                     ← (loaded from Google Fonts — see Typography below)
assets/                    ← logos, 3D blob illustrations, icon sprite
ui_kits/
  article/                 ← long-form HTML document kit
    index.html             ← interactive demo
    *.jsx                  ← React components
  dashboard/               ← report/dashboard kit
    index.html
    *.jsx
slides/                    ← 16:9 slide templates (Title, Content, Quote, etc.)
preview/                   ← Design-System-tab preview cards
```

---

## CONTENT FUNDAMENTALS

Bloom is the voice of an AI that's **smart but not stiff**. Documents generated through Bloom should read like a clever, well-read friend explaining something — not like a research paper or a marketing brochure.

### Voice & tone

- **Direct, warm, curious.** Short sentences. Active verbs. Specific nouns.
- **"You" not "the user".** Address the reader directly. The system is "we" or "Bloom".
- **Confidence without flex.** State the thing. Don't hedge with "we believe" or "it's important to note that…".
- **Curiosity as a default.** Questions are fine in body copy. Em-dashes are encouraged — they keep prose breathing.

### Casing & punctuation

- **Headings: Sentence case.** `Daily challenge`, not `Daily Challenge`, not `DAILY CHALLENGE`. The display font does the visual shouting; the words stay calm.
- **Display posters & hero callouts: ALL CAPS.** Reserved for poster-style hero moments à la `COLLECT REWARDS` / `LEVEL UP`. Never for navigation, body, or buttons.
- **Buttons: Sentence case + verb-led.** `Start plan`, `See routes`, `Open report`. Never `Click here`.
- **No trailing periods on UI labels, captions, list items, headings.** Periods only inside flowing prose.
- **Numbers: digits, not words, for any value ≥ 2.** `2 days ago`, `109 kilometers`.

### Length & rhythm

- **Headlines: ≤ 6 words.** Hero posters can be 1–3 word punches.
- **Subheads: ≤ 14 words.** One full thought.
- **Body paragraphs: 2–4 sentences.** White space carries weight.
- **Lists over paragraphs** when content is enumerable. Use them.

### Emoji & special characters

- **No emoji in body copy.** Bloom replaces them with 3D blob illustrations or icon glyphs.
- **No decorative unicode** (✨, →, ▸) in production text. Use real components.
- **Em-dashes (—) yes. Hyphens for hyphenation only.**

### Example transformations

| Don't | Do |
|---|---|
| "Click here to learn more about our amazing features." | `See what's inside` |
| "Welcome to our platform! We're so excited to have you here. 🎉" | `Hello, Sandra` <br> `Today, 25 Nov.` |
| "It is important to note that the deadline is approaching." | `Plan due before 09:00 AM` |
| "USERS MUST COMPLETE THE FORM" | `Finish your profile to start` |

---

## VISUAL FOUNDATIONS

### Color — the Bloom palette

Two layered systems sit on top of each other:

**Pastel surface palette** — used for cards, sections, illustration backdrops. Always desaturated, milky, never neon.
- Lavender `#D4C5F9`, Peach `#FFC79A`, Mint `#BDE8C9`, Sky `#BFDDEE`, Petal `#F7BFD7`, Butter `#FFE48A`

**Electric accent palette** — used for primary CTAs, progress bars, focal moments, hover/active. Used sparingly — at most one electric per screen.
- Lime `#C9F542`, Hot pink `#FF5BA4`, Iris `#7A5AF8`, Cyan `#3DD3F5`

**Neutrals** — warm, never pure gray.
- Ink `#14152B` (near-black, slight indigo), Smoke `#5B5C72`, Mist `#A8ABB9`, Cloud `#E8E9F0`, Paper `#FBFAF7` (warm off-white), Pure `#FFFFFF`

**Dark mode** flips to a deep near-black (`#0A0A14`) with a single bright accent (usually Iris or Lime) and a rainbow-gradient reserved for progress + data viz.

### Type

Two typefaces do all the work. Both are loaded from Google Fonts.

- **Display: Bricolage Grotesque** (700, 800) — chunky, optically-sized, modern but warm. Used for poster heroes, big numbers, slide titles.
- **Body: Plus Jakarta Sans** (400, 500, 600, 700) — friendly modern geometric sans. Used for everything else.
- **Mono: JetBrains Mono** (400, 500) — for code, data, timestamps.

> ⚠️ **Font substitution flag:** No production font files were supplied. Bloom uses Google Fonts CDN. If your brand has its own display + body face, drop the `.woff2` files into `fonts/` and update `colors_and_type.css`.

### Spacing & rhythm

A 4-px base scale: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96`. All paddings, gaps, and margins resolve to one of these. Card interiors default to 24px on mobile, 32px on desktop.

### Corner radii — **everything is round**

- **Cards & panels: `24px`** (large, pillow-soft)
- **Buttons & pills: `999px`** (fully rounded — this is a Bloom signature)
- **Inputs: `16px`**
- **Avatars & icon bubbles: `999px`**
- **Tiny tags: `12px`**

No sharp corners. Anywhere.

### Backgrounds

- **Default surface: Paper `#FBFAF7`** — a warm off-white, never `#FFFFFF`. White feels sterile; Paper feels printed.
- **Section accents: pastel tints** — colored "pillow" blocks that hold groups of content.
- **Hero / poster sections: pastel + 3D blob illustration** floating in the upper right.
- **Dark mode: Ink `#0A0A14`** with subtle radial color washes (10–20% opacity Iris/Lime) in the corners. Never solid black.
- **Never use:** blue→purple SaaS gradients, mesh gradients with 6 colors, glassmorphism with stark blur, "Inter on white".

### 3D blob illustrations

The strongest signature. Every hero card has a small cluster of 3D rounded shapes — toruses, rounded cubes, capsules, spheres — in the surface's accent color family. They float in the upper-right of the card with a soft drop shadow.

Stored as PNG/WebP in `assets/blobs/`. **Do not draw them inline as SVG** — they need real soft-shadow rendering. (We ship CSS placeholders so generation isn't blocked.)

### Animation

- **Easing: `cubic-bezier(0.32, 0.72, 0, 1)`** — a soft "settle" curve. Spring-like without overshoot.
- **Duration: 200ms** for hover, **280ms** for state changes, **480ms** for layout shifts.
- **Bounce reserved for one moment per page max** — usually the primary CTA on load.
- **Fades are paired with a ~6px translate** — never naked opacity.

### Hover & press

- **Hover:** lift `translateY(-1px)`, shadow grows from `sm` → `md`. Pastel cards saturate ~6%.
- **Press / active:** shrink to `scale(0.97)`, shadow collapses. **No color change** — the scale does the work.
- **Focus:** 2px outer ring in `Iris @ 50%` offset by 2px. Always visible — never `outline:none` without a replacement.

### Shadows — soft, layered, never harsh

```
--shadow-xs: 0 1px 2px rgba(20, 21, 43, 0.04);
--shadow-sm: 0 2px 8px -2px rgba(20, 21, 43, 0.06), 0 1px 2px rgba(20, 21, 43, 0.04);
--shadow-md: 0 8px 24px -8px rgba(20, 21, 43, 0.10), 0 2px 6px -2px rgba(20, 21, 43, 0.06);
--shadow-lg: 0 20px 48px -16px rgba(20, 21, 43, 0.16), 0 4px 12px -4px rgba(20, 21, 43, 0.08);
--shadow-inset-soft: inset 0 1px 0 rgba(255, 255, 255, 0.6);
```

Pastel cards get `--shadow-inset-soft` on top to give them that pillowy, lit-from-above feel.

### Borders

Mostly absent. Bloom relies on **color contrast + shadow** to separate surfaces, not lines. When a border is needed (inputs, dividers in tables), use `1px solid var(--cloud)` — and only ever 1px.

### Transparency & blur

Used **only** for the floating bottom nav (a dark pill with `backdrop-filter: blur(12px)` over content) and for modal scrims (`rgba(20, 21, 43, 0.4)` + 8px blur). Never for cards. Never as a decorative effect.

### Imagery vibe

- **Warm, slightly oversaturated** photography. Golden hour > studio.
- **Real people, real hands, real things.** No stock-photo-meeting-room imagery.
- **No b&w. No film grain.** Bloom is unapologetically colorful.
- **People photos cropped circular** when used as avatars.

### Layout rules

- **Max content width: 720px for prose, 1200px for dashboards.** Long-form should breathe.
- **Hero cards are full-width** within the content column.
- **Bottom nav (on mobile demos) is fixed**, dark pill, 16px from screen edges, with backdrop blur.
- **No fixed top nav** on long-form documents — let the content lead.

---

## ICONOGRAPHY

The user asked for **rounded, flowing, 3D** icons. Bloom uses a two-tier approach:

### Tier 1 — 3D illustrative icons (the hero treatment)

For poster moments, dashboard hero cards, and slide title pages: hand-rendered 3D shapes (PNG/WebP at 2× and 3×). Stored in `assets/blobs/`. These are the **signature** — every hero card has one.

> ⚠️ Real 3D-rendered assets are not bundled. `assets/blobs/` ships **CSS-generated stand-ins** that approximate the look using radial gradients + soft shadows on rounded `<div>` elements. Replace with rendered PNGs as soon as you have them. **Do not** generate them as inline SVG.

### Tier 2 — UI line icons (functional, supporting)

For navigation, list items, buttons, form fields: **Phosphor Icons — Bold variant**, loaded from CDN. Phosphor's Bold variant has fully rounded line endings (`stroke-linecap: round`) and the curvy, organic feel the user asked for — no angular Material/Carbon-style icons.

```html
<script src="https://unpkg.com/@phosphor-icons/web@2.1.1"></script>
<i class="ph-bold ph-house"></i>
```

Reference: https://phosphoricons.com/

### Emoji & unicode glyphs

**Not used.** Bloom never falls back to emoji or unicode chars-as-icons. If an icon is missing, leave the slot empty rather than drop in a `📊` or `→`.

### Logo

The Bloom mark is a clustered 3D blob (`assets/logo.svg`) — three soft shapes overlapping in Iris / Lime / Petal — paired with the wordmark in Bricolage Grotesque 800.

---

## How an agent should use this system

1. Read `colors_and_type.css` and `SKILL.md`.
2. Pick the right UI kit (`article` for long prose, `dashboard` for data, `slides/` for decks).
3. Pull components from that kit; never hand-roll a card or button.
4. Use Phosphor Bold for functional icons; use blob assets for hero illustrations.
5. Default to sentence case and "you"-voice copy.
6. Default to Paper background, pastel section blocks, one electric accent per screen.

---

## Caveats

- **Real fonts:** Google Fonts substitutes flagged above. Swap in licensed files when available.
- **Real 3D blobs:** stand-ins ship with the system. Real Blender/Spline renders should replace them.
- **No source brand:** Bloom is an original direction — there's no existing product to match against. If this is themeing for an existing product, attach its codebase or Figma and we'll re-bind tokens.
