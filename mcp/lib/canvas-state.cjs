// canvas-state.cjs — in-memory canvas state for loom-human-ag
// Updated by POST /canvas-state after every user interaction.
// Injected as render_state.canvas_state in canvas envelopes so the
// agent knows current card positions without reading the full HTML.
'use strict';

let _state = {
  cards: [],                 // [{anchor_id, x, y, w, h, rot, scale, z}]
  viewport: { x: 0, y: 0, zoom: 1 },
  selection: [],             // selected anchor_ids
  pending_suggestions: []    // [{id, moves:[{anchor_id,x,y,rot,scale}]}]
};

function _attr(tag, name) {
  const m = tag.match(new RegExp(name + '="([^"]*)"'));
  return m ? m[1] : null;
}

function _parseCards(html) {
  const cards = [];
  const re = /<(?:div|section)[^>]+data-anc="([^"]+)"[^>]*>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const id = m[1];
    if (id === 'canvas-root') continue;
    const tag = m[0];
    if (_attr(tag, 'data-anc-x') === null) continue; // skip non-positioned elements
    cards.push({
      anchor_id: id,
      x:     parseFloat(_attr(tag, 'data-anc-x')     || '0'),
      y:     parseFloat(_attr(tag, 'data-anc-y')     || '0'),
      w:     parseFloat(_attr(tag, 'data-anc-w')     || '320'),
      h:     parseFloat(_attr(tag, 'data-anc-h')     || '0'),
      rot:   parseFloat(_attr(tag, 'data-anc-rot')   || '0'),
      scale: parseFloat(_attr(tag, 'data-anc-scale') || '1'),
      z:     parseInt(  _attr(tag, 'data-anc-z')     || '1', 10),
    });
  }
  return cards;
}

function update(payload) {
  if (payload.viewport) _state.viewport = payload.viewport;
  if (Array.isArray(payload.selection)) _state.selection = payload.selection;
  if (payload.html) _state.cards = _parseCards(payload.html);
}

function getSnapshot() {
  return JSON.parse(JSON.stringify(_state));
}

// One active suggestion at a time (MVP).
function addSuggestion(sug) {
  _state.pending_suggestions = [sug];
}

function acceptSuggestion(id) {
  const idx = _state.pending_suggestions.findIndex(s => s.id === id);
  if (idx === -1) return null;
  const [sug] = _state.pending_suggestions.splice(idx, 1);
  // Apply moves so next getSnapshot() reflects new positions
  sug.moves.forEach(mv => {
    const card = _state.cards.find(c => c.anchor_id === mv.anchor_id);
    if (!card) return;
    if (mv.x     !== undefined) card.x     = mv.x;
    if (mv.y     !== undefined) card.y     = mv.y;
    if (mv.rot   !== undefined) card.rot   = mv.rot;
    if (mv.scale !== undefined) card.scale = mv.scale;
  });
  return sug;
}

function rejectSuggestion(id) {
  _state.pending_suggestions = _state.pending_suggestions.filter(s => s.id !== id);
}

module.exports = { update, getSnapshot, addSuggestion, acceptSuggestion, rejectSuggestion };
