// CardDensity — progressive reveal of L0-L3 information layers
//
// Desktop: Shift + hover peeks L2; Shift + scroll cycles through density levels
// Mobile:  left-swipe (←) drills deeper, right-swipe (→) backs out
// Lock:    click the density indicator dot to pin a level

const DENSITY_LEVELS = ['l3', 'l2', 'l1', 'l0'];

const CardDensity = {
  _shiftActive: false,
  _locked: new Map(),       // anchor_id → level
  _hoveredCard: null,       // current card under mouse
  _hoverLevel: 'l3',        // level during Shift hover
  _swipeState: null,        // { card, startX, startY, ts } for touch

  // ── Bootstrap ─────────────────────────────────────────────────────────
  init() {
    this._bindKeyboard();
    this._bindDesktopHover();
    this._bindWheel();
    this._bindTouch();
    this._bindIndicatorClick();
    this._initCards(document);
  },

  // Call after anchor_patch to wire new cards
  initCards(root) {
    const cards = root.querySelectorAll ? root.querySelectorAll('.anc-density-card') : [];
    cards.forEach(card => {
      if (card.dataset._densityInit === '1') return;
      card.dataset._densityInit = '1';
      this._setLevel(card, 'l3', false);
      // Restore lock if card was previously locked
      const ancId = card.getAttribute('data-anc');
      if (this._locked.has(ancId)) {
        this._setLevel(card, this._locked.get(ancId), true);
        card.classList.add('anc-density--locked');
      }
    });
  },

  // ── Keyboard: track Shift ─────────────────────────────────────────────
  _bindKeyboard() {
    document.addEventListener('keydown', e => {
      if (e.key === 'Shift' && !e.repeat) {
        this._shiftActive = true;
      }
    });
    document.addEventListener('keyup', e => {
      if (e.key === 'Shift') {
        this._shiftActive = false;
        this._releaseHover();
      }
    });
    // Shift can get "stuck" if the keyup fires outside the window
    window.addEventListener('blur', () => {
      this._shiftActive = false;
      this._releaseHover();
    });
  },

  // ── Desktop: Shift + hover ────────────────────────────────────────────
  _bindDesktopHover() {
    document.addEventListener('mouseover', e => {
      if (!this._shiftActive) return;
      const card = e.target.closest('.anc-density-card');
      if (!card || card === this._hoveredCard) return;
      const ancId = card.getAttribute('data-anc');
      if (this._locked.has(ancId)) return;
      // Release previous
      this._releaseHover();
      this._hoveredCard = card;
      this._hoverLevel = 'l2';
      this._setLevel(card, 'l2', true);
    }, true);

    document.addEventListener('mouseout', e => {
      const card = e.target.closest('.anc-density-card');
      if (!card) return;
      // Check if truly leaving the card
      const related = e.relatedTarget;
      if (related && card.contains(related)) return;
      if (card !== this._hoveredCard) return;
      this._releaseHover();
    }, true);
  },

  _releaseHover() {
    if (!this._hoveredCard) return;
    const ancId = this._hoveredCard.getAttribute('data-anc');
    if (!this._locked.has(ancId)) {
      this._setLevel(this._hoveredCard, 'l3', true);
    }
    this._hoveredCard = null;
    this._hoverLevel = 'l3';
  },

  // ── Desktop: Shift + scroll cycles density ────────────────────────────
  _bindWheel() {
    document.addEventListener('wheel', e => {
      if (!this._shiftActive) return;
      const card = e.target.closest('.anc-density-card');
      if (!card) return;
      const ancId = card.getAttribute('data-anc');
      if (this._locked.has(ancId)) return;
      e.preventDefault();

      const current = this._currentLevel(card);
      const idx = DENSITY_LEVELS.indexOf(current);
      if (e.deltaY > 0) {
        // Scroll down → drill deeper
        this._cycleLevel(card, idx + 1);
      } else if (e.deltaY < 0) {
        // Scroll up → back out
        this._cycleLevel(card, idx - 1);
      }
    }, { passive: false });
  },

  _cycleLevel(card, idx) {
    // Skip levels that don't exist in this card
    while (idx >= 0 && idx < DENSITY_LEVELS.length) {
      const layer = card.querySelector(`.anc-density-layer--${DENSITY_LEVELS[idx]}`);
      if (layer) break;
      idx += (idx > DENSITY_LEVELS.indexOf(this._currentLevel(card))) ? 1 : -1;
    }
    if (idx < 0 || idx >= DENSITY_LEVELS.length) return;
    this._setLevel(card, DENSITY_LEVELS[idx], true);
    this._hoverLevel = DENSITY_LEVELS[idx];
  },

  // ── Mobile: touch swipe ───────────────────────────────────────────────
  _bindTouch() {
    document.addEventListener('touchstart', e => {
      const card = e.target.closest('.anc-density-card');
      if (!card) return;
      const touch = e.touches[0];
      this._swipeState = {
        card,
        startX: touch.clientX,
        startY: touch.clientY,
        ts: Date.now(),
      };
    }, { passive: true });

    document.addEventListener('touchend', e => {
      const state = this._swipeState;
      this._swipeState = null;
      if (!state) return;
      const touch = e.changedTouches[0];
      const dx = touch.clientX - state.startX;
      const dy = Math.abs(touch.clientY - state.startY);
      const dt = Date.now() - state.ts;
      // Require: clear horizontal swipe, minimal vertical drift, fast enough
      if (Math.abs(dx) < 40 || dy > Math.abs(dx) * 0.6 || dt > 600) return;

      const ancId = state.card.getAttribute('data-anc');
      if (this._locked.has(ancId)) return;

      const current = this._currentLevel(state.card);
      const idx = DENSITY_LEVELS.indexOf(current);
      if (dx < 0) {
        // Swipe left → deeper
        this._cycleLevel(state.card, idx + 1);
      } else {
        // Swipe right → shallower
        this._cycleLevel(state.card, idx - 1);
      }
    }, { passive: true });
  },

  // ── Indicator: click dot to lock ──────────────────────────────────────
  _bindIndicatorClick() {
    document.addEventListener('click', e => {
      const dot = e.target.closest('[data-density-dot]');
      if (!dot) return;
      e.preventDefault();
      e.stopPropagation();
      const card = dot.closest('.anc-density-card');
      if (!card) return;
      const ancId = card.getAttribute('data-anc');
      const level = dot.dataset.densityDot;

      if (this._locked.has(ancId) && this._locked.get(ancId) === level) {
        // Click active dot again → unlock
        this._locked.delete(ancId);
        card.classList.remove('anc-density--locked');
        this._setLevel(card, 'l3', true);
      } else {
        // Lock to this level
        this._locked.set(ancId, level);
        card.classList.add('anc-density--locked');
        this._setLevel(card, level, true);
      }
    }, true);
  },

  // ── Core: set density level with animation ────────────────────────────
  _setLevel(card, level, animate) {
    const layers = card.querySelectorAll('.anc-density-layer');
    const maxIdx = DENSITY_LEVELS.indexOf(level);

    layers.forEach(layer => {
      const dl = layer.dataset.density;
      const idx = DENSITY_LEVELS.indexOf(dl);
      const visible = idx >= 0 && idx <= maxIdx && this._layerExists(card, dl);

      if (visible) {
        layer.removeAttribute('hidden');
        if (animate) layer.classList.add('anc-density--entering');
        requestAnimationFrame(() => {
          layer.classList.remove('anc-density--entering');
        });
      } else {
        if (animate) {
          layer.classList.add('anc-density--exiting');
          const onEnd = () => {
            layer.removeEventListener('transitionend', onEnd);
            layer.classList.remove('anc-density--exiting');
            layer.setAttribute('hidden', '');
          };
          layer.addEventListener('transitionend', onEnd);
          // Fallback if transition doesn't fire
          setTimeout(() => {
            if (layer.classList.contains('anc-density--exiting')) {
              onEnd();
            }
          }, 400);
        } else {
          layer.setAttribute('hidden', '');
        }
      }
    });

    // Update indicator dots
    const dots = card.querySelectorAll('[data-density-dot]');
    dots.forEach(dot => {
      const dotLevel = dot.dataset.densityDot;
      const active = DENSITY_LEVELS.indexOf(dotLevel) <= maxIdx;
      dot.classList.toggle('active', active);
    });

    // Notify anchor-client about detail expansion
    const anchorId = card.getAttribute('data-anc');
    card.dispatchEvent(new CustomEvent('density-change', {
      bubbles: true,
      detail: { anchorId, level, maxIdx }
    }));
  },

  _currentLevel(card) {
    let max = 'l3';
    const layers = card.querySelectorAll('.anc-density-layer');
    layers.forEach(layer => {
      if (!layer.hasAttribute('hidden') && this._layerExists(card, layer.dataset.density)) {
        const idx = DENSITY_LEVELS.indexOf(layer.dataset.density);
        const curIdx = DENSITY_LEVELS.indexOf(max);
        if (idx > curIdx) max = layer.dataset.density;
      }
    });
    return max;
  },

  _layerExists(card, level) {
    return !!card.querySelector(`.anc-density-layer--${level}`);
  },

  // ── Public API ────────────────────────────────────────────────────────
  // Called from anchor-client.js after patch to re-wire cards
  refresh(root) {
    this.initCards(root || document);
  },

  // Reset all unlocked cards to L3
  collapseAll() {
    document.querySelectorAll('.anc-density-card').forEach(card => {
      const ancId = card.getAttribute('data-anc');
      if (!this._locked.has(ancId)) {
        this._setLevel(card, 'l3', true);
      }
    });
    this._hoveredCard = null;
  }
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = CardDensity;
}
