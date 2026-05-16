---
name: bloom-design
description: Use this skill to generate well-branded interfaces and assets for Bloom — a theme system for AI-agent-generated structured HTML documents. The Bloom aesthetic is youthful + future-tech: soft pastel pillow cards, 3D rounded blob illustrations, one electric accent per screen, fully rounded corners, and rounded-line Phosphor icons. Use this skill for any throwaway prototype, mock, generated report, article, or dashboard that needs the Bloom look.
user-invocable: true
---

Read `README.md` first — it contains the brand voice, color tokens, type rules, visual foundations, and an index of every other file.

After that, the most important files to know about:

- `colors_and_type.css` — the design tokens. Always include this at the top of any HTML you generate. Use CSS variables (`var(--ink)`, `var(--pastel-lavender)`, etc.) instead of hard-coded values.
- `ui_kits/article/` — long-form article kit. Use for AI-generated reports, write-ups, explainers, briefs.
- `ui_kits/dashboard/` — metrics dashboard kit. Use for status reports, KPI views, data narratives.
- `assets/blobs/` — the signature 3D rounded illustrations. Every hero card should have one.
- `assets/logo-mark.svg`, `assets/logo.svg` — the Bloom logo.

When creating visual artifacts:

1. Copy `colors_and_type.css` and `assets/` into the output folder so it's self-contained.
2. Pick the right kit (article for prose, dashboard for data) and lift components from it. Don't re-invent cards, buttons, or stat blocks.
3. Use Phosphor Bold icons from CDN: `<link rel="stylesheet" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css">` then `<i class="ph-bold ph-house"></i>`.
4. **Stick to one electric accent per screen** (lime, hot pink, iris, or cyan). Everything else should be pastels + warm neutrals.
5. **Round everything.** Cards = 24px+, buttons = pill, inputs = 16px. Never sharp.
6. **Voice rules from README:** sentence case headings, "you" not "the user", no emoji in body copy, no decorative unicode.

When working on production code:

- Read `colors_and_type.css` and use the tokens directly. Don't define your own colors.
- The visual foundations + content fundamentals sections of `README.md` are the source of truth.

If the user invokes this skill with no other guidance, ask what they want to build, ask 3–5 focused follow-up questions about audience / surface / variations, then deliver as HTML artifacts or production code as appropriate.

## Caveats baked into the system

- Fonts: substituted from Google Fonts (Bricolage Grotesque, Plus Jakarta Sans, JetBrains Mono). Swap in licensed files when available.
- 3D blob illustrations: shipped as SVG stand-ins. Replace with real Blender/Spline renders for production.
- This is an original direction — not a recreation of an existing product. If targeting a real product, attach its codebase or Figma and rebind tokens.
