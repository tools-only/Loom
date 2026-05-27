# Static report content template design

## Goal

Create a reusable static report template inspired by the supplied CPO report screenshot: calm misty surfaces, rounded white content panels, soft pastel metric cards, and strong reading hierarchy. The template is a visual/content artifact only. It must not contain Loom application logic.

## Scope

The deliverable is a new template at `resource/ui_kits/report/index.html`.

In scope:

- A report hero with title, subtitle, metadata, and status pills
- A market-overview section with summary prose and four KPI cards
- Repeatable analysis sections with section title, context copy, stat cards, and an insight callout
- A compact timeline, risk block, conclusion block, and disclaimer footer
- Responsive behavior for desktop and narrow widths
- Placeholder Chinese report content demonstrating replacement points

Out of scope:

- Changes to the existing history HTML files under `branches/market/history/`
- Changes to Loom shell navigation, side tools, routing, state, or content injection
- Anchor protocol attributes such as `data-anc`, `data-handles`, or `data-deps`
- JavaScript, interaction handlers, data fetching, editing controls, or generation logic
- New global theme overrides in `bridge/webview/styles.css`

## Design Direction

The selected visual direction is restrained and content-first. It borrows the host-native feel that the user selected as option A, but remains standalone:

- Warm near-white document background with barely visible blue/lavender ambient washes
- White section surfaces with 20-24px radii and light layered shadows
- KPI cards using muted mint, lavender, peach, and butter gradients
- Dark indigo text, subtle gray-blue supporting text, and small rounded status pills
- Dense enough for an analyst report, while preserving generous spacing between sections

The template should look comfortable and quiet rather than decorative. It does not reproduce the surrounding Loom application frame.

## File And Dependency Strategy

`resource/ui_kits/report/index.html` will be a complete openable HTML document.

- It may link to `../../colors_and_type.css` for existing Bloom typography and color tokens. That stylesheet is a visual resource, not Loom logic.
- Report-specific layout styles remain scoped inside the template file under `.report-template` and `report-*` component classes.
- It uses CSS-only layout and visual treatment. No script tags are required.
- Icons, if shown, use small CSS/SVG presentation elements or existing visual font resources only; no interactive icon behavior is included.

This keeps the artifact easy to preview directly and easy to adapt into future report generators without entangling it with app code.

## Component Structure

### Report canvas

A centered `.report-template` wrapper controls maximum width and vertical rhythm. It holds every visible report component and provides the ambient page background.

### Hero

The top region contains:

- Context label and report title
- One-line subtitle and reporting date
- Three status pills representing thesis, theme, and volatility

The hero remains visually open rather than becoming a heavy card, matching the airy top of the reference.

### Overview panel

A primary white surface contains:

- Section heading and a small category badge
- One compact overview paragraph with emphasized key number
- Four metric cards in a wrapping grid

Metric cards have one label, one dominant value, and one short supporting line. They do not carry long analysis.

### Repeatable analysis panel

One representative industry-layer section demonstrates how future authors repeat sections:

- Numbered section heading and layer badge
- Short contextual statement
- One or more highlight cards
- A neutral insight callout with a colored accent rule

The HTML will include comments identifying this panel as a repeatable block.

### Timeline, risks, and conclusion

The lower part demonstrates secondary report patterns:

- Timeline: date/value pairs stacked for scanability
- Risks: simple risk rows with severity labels
- Conclusion: three small portfolio/action cards or recommendation chips
- Footer: restrained disclaimer text

## Content Replacement Contract

The template contains static sample copy, not live report data. Future reuse replaces:

- Report identity and metadata
- Overview paragraph
- KPI labels, values, and annotations
- Repeatable analysis sections
- Timeline events, risks, and conclusion items

Replacement does not require changing the class system or adding scripts. Classes are visual only and intentionally generic (`report-panel`, `report-kpi`, `report-callout`, and related names).

## Responsiveness And Accessibility

- The content max width targets report reading on desktop while remaining fluid on smaller canvases.
- KPI grids collapse from four columns to two and then one using CSS media queries.
- Font sizes use `clamp()` for headings and key values.
- Contrast remains readable against pastel surfaces.
- Every information-bearing label is text; color is supportive rather than the only signal.
- Motion is limited to optional hover lift and removed under `prefers-reduced-motion`.

## Failure And Edge Cases

- Long Chinese titles and metric values must wrap without clipping or vertical letter stacking.
- A metric card with longer supporting text grows naturally rather than forcing fixed height.
- If the local font import is unavailable, standard CJK-safe fallback fonts remain readable.
- The template must remain coherent when opened directly from disk or through a simple static server.

## Verification

Implementation verification will include:

1. Open the HTML directly or through a local browser preview and confirm it visually matches the chosen calm report direction.
2. Check desktop and narrow browser widths for wrapping and KPI-grid collapse.
3. Inspect the document source to verify that it contains no `data-anc`, `data-handles`, Loom imports, or JavaScript.
4. Confirm that no existing history report or host application style file was changed as part of the template implementation.

