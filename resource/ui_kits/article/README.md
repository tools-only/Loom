# Article UI Kit

Long-form **AI-generated document** layout — research write-ups, explainer articles, structured reports with prose + figures + pull-quotes + callouts.

## Files

- `index.html` — interactive demo showing a complete article
- `Hero.jsx` — hero with kicker, headline, byline, blob cluster
- `Prose.jsx` — paragraphs, headings, lists, links — all the body content
- `PullQuote.jsx` — large pull-quote with optional attribution
- `Figure.jsx` — image / illustration with caption
- `Callout.jsx` — tinted info / note / warning blocks
- `StatRow.jsx` — pillow KPI row inline in prose
- `EndCard.jsx` — closing CTA card with secondary actions
- `TopBar.jsx` — minimal top bar (logo + reading progress)

## How to use

Open `index.html` to see everything composed. The components are kept tiny and cosmetic — they exist to make AI-generated HTML look designed, not to be a production blog engine.

All styling resolves through `colors_and_type.css` (loaded at the top of `index.html`).
