# Librarian: Human-Agent Collaborative Resource Wiki

## Context

Hand agents (market/sentiment/target/position) currently rely on a static `resource_library.json` for their data sources. Users can submit resources via the UI Context Panel, but those submissions go into a separate context registry (`status: 'pending'`) and are never processed by an agent — no summarization, no categorization, no integration into the shared resource library. The library stays static, requiring manual editing.

Karpathy's [llm-wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) describes a pattern where LLM agents incrementally build and maintain a persistent wiki of interlinked markdown files — the human curates sources and directs analysis, the agent handles all bookkeeping. This spec applies that pattern to the Loom resource library.

## Phase 1 Scope (this implementation)

URL submission → Librarian agent processing → resource library enrichment + wiki page creation. Progressive disclosure (intelligent resource suggestion per Hand task) is deferred to Phase 2.

**In scope:**
- New `LibrarianHand` in Python Brain (port 3001)
- Wiki storage (`loom/wiki/<id>.md`, `loom/wiki/index.md`, `loom/wiki/log.md`)
- Enriched `resource_library.json` schema
- Node server endpoints for UI submission and wiki reads
- UI resource form enhancement (notes field, status feedback, wiki display)
- Migration: existing 15 hardcoded resources get wiki pages generated on first access

**Out of scope:**
- Progressive disclosure (Phase 2)
- Lint/health-check (Phase 3)
- Deduplication across user submissions

## Architecture

```
Browser (UI)
  │ POST /loom/resource/submit { name, url, notes }
  │ GET  /loom/wiki/<id>
  │ PUT  /loom/wiki/<id>/human-note
  ▼
Node Server (port 3000)
  ├─ save pending → return { ok, resource_id, status: "pending" }
  ├─ background → POST localhost:3001/librarian/process
  ├─ serves wiki markdown from loom/wiki/
  └─ GET /loom/resource/<id>/status for UI polling
      │
      │ POST /librarian/process { resource_id }
      ▼
Python Brain (port 3001)
  └─ LibrarianHand (loom/hands/librarian.py)
      1. Read pending resource data (name, url, notes)
      2. fetch_resource(url) — LLM tool call to scrape content
      3. LLM generates: summary, tags, domains, tier, wiki narrative
      4. Write to resource_library.json
      5. Create wiki/<id>.md
      6. Update wiki/index.md and wiki/log.md
      7. Remove pending marker
```

## Files

### New files

| File | Purpose |
|------|---------|
| `loom/hands/librarian.py` | `LibrarianHand(BaseHand)` — processes URL submissions, generates wiki content via LLM |
| `loom/hands/prompts/librarian.md` | System prompt for Librarian agent JSON output |
| `loom/wiki/index.md` | Auto-maintained catalog of all wiki pages |
| `loom/wiki/log.md` | Append-only changelog of all Librarian operations |
| `loom/resource_feedback.json` | User like/dislike data (schema ready, used in Phase 2) |

### Modified files

| File | Changes |
|------|---------|
| `loom/hand_registry.py` | Register `librarian` hand with anchor_id `loom-librarian` |
| `loom/brain.py` | New `POST /librarian/process` endpoint; import LibrarianHand |
| `loom/resource_library.json` | Extended schema: add `name`, `url`, `summary`, `tags`, `status`, `last_reviewed`, `added_by` |
| `mcp/server.cjs` | New routes: `POST /loom/resource/submit`, `GET /loom/wiki/:id`, `PUT /loom/wiki/:id/human-note`, `GET /loom/resource/:id/status` |
| `bridge/webview/index.html` | Add notes textarea to resource form; add wiki display panel |
| `bridge/webview/anchor-client.js` | Rewrite `addUserResource` to POST new endpoint; add status polling; add wiki panel rendering |
| `bridge/webview/styles.css` | Wiki display styles |

## Data Schema

### resource_library.json (extended)

```json
{
  "fred": {
    "resource_id": "fred",
    "name": "FRED",
    "description": "FRED 宏观数据 — CPI、利率、就业、货币供应、GDP",
    "url": "https://fred.stlouisfed.org",
    "summary": "FRED (Federal Reserve Economic Data) provides access to a wide range of US macroeconomic time series...",
    "tier": "A",
    "domains": ["macro", "rates", "liquidity"],
    "tags": ["fed", "cpi", "interest_rates"],
    "status": "active",
    "added_by": "system",
    "last_reviewed": "2026-05-29",
    "wiki_page": "fred.md"
  }
}
```

New fields vs current:
- `name` — human-readable short name
- `url` — source URL (used by Librarian for fetching)
- `summary` — LLM-generated 1-2 sentence summary (shown in UI tooltip)
- `tags` — fine-grained topic tags for matching
- `status` — `pending` | `processing` | `active` | `error`
- `added_by` — `system` | `librarian` | `user:<user_id>`
- `last_reviewed` — ISO date of last agent processing

### Wiki page format (loom/wiki/<id>.md)

Each resource gets a Markdown wiki page with YAML frontmatter:

```markdown
---
resource_id: "fred"
tier: "A"
domains: [macro, rates, liquidity]
tags: [fed, cpi, interest_rates]
status: active
added_by: system
last_reviewed: 2026-05-29
---

# FRED 宏观数据

## Summary
FRED (Federal Reserve Economic Data) provides access to a wide range of US macroeconomic time series including CPI, interest rates, employment data, money supply, and GDP. It is a primary source for macro regime analysis.

## Key Metrics
- CPI (Consumer Price Index)
- Federal Funds Rate
- Non-farm Payrolls
- M2 Money Supply
- GDP/GDP Nowcast

## Use Cases
- Macro regime assessment (Tier A — primary fact base)
- Rate/liquidity analysis
- Economic indicator tracking

## Human Notes

<!-- User-editable section — updated via PUT /loom/wiki/<id>/human-note -->

## Agent Log
- `2026-05-29`: Initial ingestion by Librarian agent
```

### wiki/index.md

Auto-maintained catalog:

```markdown
# Resource Wiki Index

## Tier A
- [FRED](fred.md) — US macro data (CPI, rates, employment)
- [SEC EDGAR](sec-edgar.md) — Company filings, 8-K, insider trading

## Tier B
- [Finnhub](finnhub.md) — Fundamentals, earnings estimates
- [Yahoo Finance](yahoo-finance.md) — Price, sectors, financials
- ... etc.

## User-Submitted
- [example-resource](example-resource.md) — [User description] (added 2026-05-29)
```

### wiki/log.md

Append-only:

```markdown
## Changelog

- `2026-05-29T10:30:00Z | process | resource/example | Librarian | Created wiki page`
- `2026-05-29T10:30:00Z | index | wiki/index.md | Librarian | Updated catalog`
```

## API Specification

### Node (mcp/server.cjs)

```http
POST /loom/resource/submit
Content-Type: application/json

{ "name": "My Resource", "url": "https://example.com", "notes": "关注其季度数据" }

→ 202
{ "ok": true, "resource_id": "my-resource", "status": "pending" }
```

Side effects:
1. Write pending file to `loom/pending_resources/<id>.json`
2. Fire-and-forget: `POST http://127.0.0.1:3001/librarian/process { resource_id }`
3. The `resource_id` is slugified from name: lowercase, spaces → hyphens, strip non-alphanumeric except hyphens. E.g. "My Resource!" → `my-resource`.
4. UI polls `GET /loom/resource/<id>/status` every 3s until status is `active` or `error`.

```http
GET /loom/resource/<id>/status

→ 200
{ "ok": true, "resource_id": "my-resource", "status": "active"|"pending"|"processing"|"error", "error?": "..." }
```

Reads status from `resource_library.json` (active/error) or `pending_resources/<id>.json` (pending/processing).

```http
GET /loom/wiki/<resource_id>

→ 200
{ "ok": true, "wiki": { "markdown": "...", "frontmatter": { ... }, "html": "..." } }
```

Returns markdown content and parsed frontmatter. HTML rendering is done client-side (marked library auto-included by webview shell).

```http
PUT /loom/wiki/<resource_id>/human-note
Content-Type: application/json

{ "note": "这是一个重要的宏观数据源" }

→ 200
{ "ok": true }
```

Replaces the `## Human Notes` section in the wiki markdown file.

### Brain (loom/brain.py)

```http
POST /librarian/process
Content-Type: application/json

{ "resource_id": "my-resource" }

→ 200
{ "ok": true, "resource_id": "my-resource", "wiki_page": "my-resource.md" }
```

Processing steps within LibrarianHand:
1. Read `loom/pending_resources/<resource_id>.json`
2. Set `resource_library.json[resource_id].status = "processing"` (for UI polling)
3. Create LLM call with `fetch_resource` tool to get URL content
4. Parse LLM response → structured artifact
5. Write entry to `resource_library.json`
6. Write wiki page to `loom/wiki/<resource_id>.md`
7. Update wiki/index.md and wiki/log.md
8. Remove pending file

## Librarian Hand Design

### `loom/hands/librarian.py`

Extends `BaseHand` with `hand_id="librarian"`. The `run()` method receives:

```python
context = {
    "resource_id": "my-resource",
    "name": "My Resource",
    "url": "https://example.com",
    "user_notes": "关注其季度数据"
}
```

The prompt (`librarian.md`) instructs the LLM to:
1. Use `fetch_resource(url)` to pull the page content
2. Analyze: what kind of data source is this? What domain does it cover? What tier?
3. Output structured artifact with:
   - `resource_summary` — 1-2 sentence summary
   - `suggested_tags` — fine-grained topic tags
   - `suggested_domains` — matched from existing domain taxonomy
   - `suggested_tier` — A/B/C/E/F
   - `wiki_narrative` — full markdown body for the wiki page
   - `key_claims` — notable insights about the data source

The LibrarianHand overrides `_parse_artifact()` to extract these fields and handle the file I/O (writing to resource_library.json, creating wiki file, updating index/log).

### Why a BaseHand subclass (not standalone)

- Gets LLM access through existing `provider_client.py` (multi-provider)
- Uses same `fetch_resource` tool + `bridge.get_connector_data()` pattern
- Templates identical — same JSON artifact contract
- Slot into existing `/run` routing if needed, but has its own dedicated `/librarian/process` endpoint for simplicity

## UI Changes

### Resource form (index.html)

```html
<div class="resource-form">
  <input type="text" class="resource-name-input" placeholder="Resource name...">
  <input type="url" class="resource-url-input" placeholder="https://...">
  <textarea class="resource-notes-input" placeholder="为什么关注这个资源？它将帮助 Agent 在哪些场景下使用？"></textarea>
  <button class="btn btn--sm btn--brand resource-add-btn">+ Add</button>
</div>
```

### Resource list item states

Each resource in the group list shows:

```
[●] Resource Name (green dot=active, gray spinner=pending)
  ↳ Summary: [LLM-generated one-liner]
  ↳ [View Wiki] (opens wiki content)
```

- `status=pending/processing`: gray spinner animation, disabled selection
- `status=active`: green dot, clickable for wiki expansion
- `status=error`: red dot, hover shows error message

### Wiki display (on resource click)

On clicking an active resource, show a small inline panel within the context sidebar:

```html
<div class="wiki-preview">
  <div class="wiki-preview-header">
    <strong>Resource Name</strong>
    <span class="anc-pill anc-pill--<tier>">Tier A</span>
  </div>
  <div class="wiki-preview-body">
    <p>LLM-generated summary...</p>
    <div class="wiki-tags">
      <span class="anc-pill anc-pill--review">fed</span>
      <span class="anc-pill anc-pill--review">cpi</span>
    </div>
    <details>
      <summary>Human Notes</summary>
      <div class="wiki-human-notes" contenteditable="true">...</div>
      <button class="btn btn--sm btn--ghost">Save</button>
    </details>
    <details>
      <summary>Full Wiki</summary>
      <div class="wiki-full-content">...</div>
    </details>
  </div>
</div>
```

## Migration Strategy

The existing 15 resources in `resource_library.json` need wiki pages. Two options:

**Option A (lazy migration, recommended):** When a Hand first requests a resource via `/data/:connector_id`, check if it has a `wiki_page` in its entry. If not, the Librarian generates one lazily. This adds latency on first access but avoids batch-processing all 15 at once.

**Option B (batch):** On deploy, iterate existing resources and generate wiki pages for each. More predictable but takes LLM time up front.

**Recommended: Option A** — the existing resource entries already have `description` and `domains` fields, so the system works without wiki pages. The Librarian generates them on-demand.

## Verification

1. **Unit test**: Submit URL via `POST /loom/resource/submit` → verify `resource_library.json` updated, `loom/wiki/<id>.md` created, `wiki/index.md` updated
2. **UI test**: Open webview → Context panel → add resource → observe "pending" → "active" transition → click to view wiki
3. **Hand test**: After adding a resource, run a Market Hand task → confirm the new resource appears in resource_menu when relevant
4. **Edge case**: Submit URL twice → same slug → Librarian overwrites with updated info
5. **Edge case**: Submit with empty/invalid URL → Librarian errors gracefully, status becomes "error" with message
