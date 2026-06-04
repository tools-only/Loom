# Canvas Co-design Skill

You are working on a freeform whiteboard canvas. Cards are HTML elements with
`data-anc-x/y/w/rot/scale/z` position attributes. The current layout is in
`render_state.canvas_state.cards` (injected into every canvas envelope).

## Op Decision Tree

| Situation | Use |
|-----------|-----|
| User asks to generate new content | `anchor_render(html)` with full canvas-root |
| User asks to update existing card(s) | `anchor_patch({patches:[...]})` |
| User asks to create one new card at a specific spot | `anchor_patch` with a new unique anchor_id |
| User asks to rearrange / reorganize cards | `anchor_emit_event('layout_suggest', {...})` |
| User asks to move one specific card (explicit) | `anchor_patch` updating data-anc-x/y on that card |

## Reading canvas_state

```json
{
  "cards": [
    {"anchor_id": "card-foo", "x": 80, "y": 80, "w": 320, "h": 0, "rot": 0, "scale": 1, "z": 1}
  ],
  "viewport": {"x": 0, "y": 0, "zoom": 1},
  "selection": ["card-foo"]
}
```

- `x/y` — top-left position in canvas pixels (canvas is 3000×2000)
- `w` — card width; `h=0` means auto height
- `rot` — rotation in degrees; `scale` — CSS scale factor
- `selection` — cards the user has highlighted; patch these first for group ops

## canvas_create (new card)

Just call `anchor_patch` with a **new, unique** `anchor_id` — the client auto-creates
new cards when the patch target doesn't exist yet.

Choose position to avoid overlap: check `canvas_state.cards` and find a free area.
Minimum safe gap: 20px between bounding boxes. Default step: 360px x-axis, 280px y-axis
from (80, 80) origin.

```javascript
anchor_patch({ patches: [{
  anchor_id: 'card-counterargument',
  html_fragment: `<div class="anc-card anc-section anc-section--gc"
       data-anc="card-counterargument"
       data-handles="refine,expand,shorten"
       data-anc-x="800" data-anc-y="360"
       data-anc-w="320" data-anc-rot="0" data-anc-scale="1" data-anc-z="1"
       style="position:absolute;left:800px;top:360px;width:320px;transform:rotate(0deg) scale(1);">
    <h2>Counter-argument</h2>
    <p>...</p>
  </div>`
}]})
```

## canvas_arrange (layout suggestion)

When the user wants cards reorganized, **do not patch directly**. Emit a layout
suggestion so the user can preview and Accept/Reject.

```javascript
anchor_emit_event('layout_suggest', {
  suggestion_id: 'sug-' + Date.now(),
  moves: [
    { anchor_id: 'card-foo', x: 80,  y: 80  },
    { anchor_id: 'card-bar', x: 440, y: 80  },
    { anchor_id: 'card-baz', x: 800, y: 80  }
  ]
})
```

Rules:
- Include ALL cards you want to move (omitted cards stay put)
- Only provide `x` and `y`; preserve existing `rot` and `scale` unless the user
  explicitly asked to reset them
- After emitting, say "I've suggested a new layout — please Accept or Reject in the canvas."

## Group patch (multiple cards selected)

When `intent.target_kind === 'group'`, `intent.target_refs` lists the selected card IDs.
Return one patch per card:

```javascript
anchor_patch({ patches: [
  { anchor_id: 'card-a', html_fragment: '...' },
  { anchor_id: 'card-b', html_fragment: '...' },
  { anchor_id: 'card-c', html_fragment: '...' },
]})
```

Content of each card should be thematically consistent with the instruction.
Preserve each card's `data-anc-x/y/rot/scale` exactly (copy from render_state).

## Style Rules (Bloom CSS)

**Every card must be visually designed — never plain text.** Use one of these patterns:

**Concept/Topic card** — colored section + pill + h2 + p + ul:
```html
<div class="anc-card anc-section anc-section--gc anc-section--aurora" data-anc="card-X" ...>
  <div class="anc-pill-row"><span class="anc-pill anc-pill--gen">洞察</span></div>
  <h2>标题</h2><p>正文</p><ul><li><strong>要点</strong> — 说明</li></ul>
</div>
```

**KPI/Data card** — neutral section + anc-kpi-grid with gradient KPIs:
```html
<div class="anc-card anc-section anc-section--gc" data-anc="card-X" ...>
  <h3>指标</h3>
  <div class="anc-kpi-grid">
    <div class="anc-kpi anc-kpi--aurora anc-kpi--center"><div class="kpi-value">42%</div><div class="kpi-label">指标名</div></div>
    <div class="anc-kpi anc-kpi--warm anc-kpi--center"><div class="kpi-value">$1.2T</div><div class="kpi-label">规模</div></div>
  </div>
</div>
```

**Highlight card** — flame/berry/arctic section + pill + blockquote:
```html
<div class="anc-card anc-section anc-section--gc anc-section--flame" data-anc="card-X" ...>
  <div class="anc-pill-row"><span class="anc-pill anc-pill--warn">⚠ 风险</span></div>
  <h2>警示</h2><blockquote>核心内容</blockquote>
</div>
```

Color themes (use variety across cards): `--aurora` `--warm` `--cool` `--berry` `--flame` `--arctic`
Icons: `<i class="ph-bold ph-brain"></i>` `ph-lightning` `ph-trend-up` `ph-warning` `ph-check-circle`
- Never hard-code colors; use Bloom CSS tokens only
