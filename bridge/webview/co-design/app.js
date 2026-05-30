// ── Co-Design App — Anchor WebSocket client for collaborative slide design ─

(function () {
  'use strict';

  const WS_URL = (location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host;

  let ws = null;
  let pingTimer = null;
  let hasContent = false;

  // ── DOM refs ──────────────────────────────────────────────────────

  const $start     = document.getElementById('codesign-start');
  const $workspace = document.getElementById('codesign-workspace');
  const $content   = document.getElementById('codesign-content');
  const $outline   = document.getElementById('outline-nav');
  const $status    = document.getElementById('status');
  const $prompt    = document.getElementById('codesign-prompt');
  const $submit    = document.getElementById('codesign-submit');
  const $exportBtn = document.getElementById('btn-export');
  const $newBtn    = document.getElementById('btn-new-deck');
  const $toggleOut = document.getElementById('btn-toggle-outline');
  const $outlinePanel = document.getElementById('codesign-outline');

  // ── WebSocket ─────────────────────────────────────────────────────

  function connect() {
    try { ws = new WebSocket(WS_URL); } catch (e) { return; }

    ws.onopen = () => {
      setStatus('connected');
      pingTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) { /* ignore */ }
    };

    ws.onclose = () => {
      clearInterval(pingTimer);
      setStatus('reconnecting...');
      setTimeout(connect, 2000);
    };

    ws.onerror = () => { /* onclose fires next */ };
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
      return true;
    }
    toast('Not connected — waiting...');
    return false;
  }

  function setStatus(text) {
    $status.textContent = text;
  }

  // ── Message handler ───────────────────────────────────────────────

  function handleMessage(msg) {
    switch (msg.type) {
      case 'html':
        renderHtml(msg.content);
        break;
      case 'patch':
        applyPatches(msg.patches);
        break;
    }
  }

  // ── Prompt / Generation ───────────────────────────────────────────

  function submitPrompt(text) {
    if (!text.trim()) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast('Not connected — please wait');
      return;
    }
    showWorkspace();
    showProcessing();

    const slideContract = [
      'Generate a complete slide deck as an Anchor HTML page for the co-design workspace.',
      'CRITICAL: Output ONLY the HTML for the slides (no <!DOCTYPE>, no <html>, no <head>, no <body>).',
      '',
      'Each slide MUST be: <section class="anc-slide anc-slide--TYPE" data-anc="slide-N" data-handles="refine,expand,edit">',
      'Available slide types (set via anc-slide--TYPE):',
      '  anc-slide--title   — title slide (large heading + subtitle + meta)',
      '  anc-slide--content — bullet points, paragraphs, general content',
      '  anc-slide--code    — code snippet with heading + explanation',
      '  anc-slide--table   — data tables or comparison matrices',
      '  anc-slide--diagram — architecture diagram placeholder (use .slide-diagram div)',
      '  anc-slide--conclusion — summary + next steps',
      '',
      'GRADIENT THEMES — add anc-slide--gc PLUS a theme class to each non-title, non-code slide:',
      '  <section class="anc-slide anc-slide--content anc-slide--gc anc-slide--THEME" data-anc="slide-N" data-handles="refine,expand,edit">',
      '  Available themes for anc-slide--THEME (pick one per slide, vary across deck):',
      '    warm   — coral × lavender, warm approachable (best for intro/content)',
      '    cool   — teal × sky blue, calm technical (best for data/technical)',
      '    aurora — indigo × emerald, vibrant primary (best for key insights)',
      '    ocean  — deep blue × coral pink, depth/contrast (best for comparisons)',
      '    berry  — deep purple × wine, premium bold (best for highlights)',
      '    arctic — ice blue × mint, clean info (best for data-heavy slides)',
      '    flame  — orange × deep rose, energetic (best for urgency/warnings)',
      '    sunset — rose × gold, warm emphasis (best for call-to-action)',
      '    forest — pine × sky blue, natural/success (best for positive outcomes)',
      '    dusk   — gray-blue × dusty pink, neutral secondary (best for appendix)',
      '',
      '  Theme assignment guidelines:',
      '  - Title slides: NO anc-slide--gc (keep anc-slide--title styling)',
      '  - Code slides: NO anc-slide--gc (keep anc-slide--code dark styling)',
      '',
      'Rules:',
      '- Use data-anc="slide-N" on each section (N = 1,2,3...)',
      '- Use data-handles="refine,expand,edit" on each element that can be refined',
      '- Use data-anc="slide-N.title", "slide-N.body", "slide-N.code", "slide-N.table", etc. for sub-elements',
      '- Use slide-meta div for author/date/tags on title slides',
      '- Code slides: use <pre><code> with language class',
      '- Table slides: use standard <table>',
      '- Follow Bloom Design System (var(--*) CSS tokens)',
      '- Include 5-8 slides total',
      '- All text in a single language (match the user\'s language)',
    ].join('\n');

    const fullPrompt = slideContract + '\n\nTopic: ' + text;

    send({ type: 'prompt', text: fullPrompt, route: 'co-design' });
    setStatus('generating...');
  }

  // ── Render ────────────────────────────────────────────────────────

  // ── Fallback theme assignment ────────────────────────────────────

  const THEMES = ['warm','cool','aurora','ocean','berry','arctic','flame','sunset','forest','dusk'];

  function assignSlideThemes() {
    // Only auto-assign to slides that don't already have anc-slide--gc
    $content.querySelectorAll('.anc-slide:not(.anc-slide--gc):not(.anc-slide--title):not(.anc-slide--code)').forEach(slide => {
      const theme = THEMES[Math.floor(Math.random() * THEMES.length)];
      slide.classList.add('anc-slide--gc', 'anc-slide--' + theme);
    });
  }

  // ── Render ────────────────────────────────────────────────────────

  function renderHtml(html) {
    $content.innerHTML = html;
    hasContent = true;
    setStatus('ready');
    $exportBtn.disabled = false;

    assignSlideThemes();
    injectHandles();
    buildOutline();
    const first = $content.querySelector('.anc-slide');
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function applyPatches(patches) {
    if (!patches || !patches.length) return;
    for (const p of patches) {
      const el = document.querySelector('[data-anc="' + p.anchor_id + '"]');
      if (el) {
        const tpl = document.createElement('template');
        tpl.innerHTML = p.html_fragment.trim();
        const replacement = tpl.content.firstChild;
        if (replacement) {
          el.replaceWith(replacement);
        }
      }
    }
    assignSlideThemes();
    injectHandles();
    buildOutline();
    toast('Slide updated');
  }

  // ── Handle injection ─────────────────────────────────────────────

  function injectHandles() {
    // Slide-level: handle bar pinned to top-right of each slide
    $content.querySelectorAll('.anc-slide[data-handles]').forEach(slide => {
      if (slide.querySelector('.slide-handle-bar')) return;
      const handles = slide.getAttribute('data-handles').split(',').map(h => h.trim()).filter(Boolean);
      const bar = document.createElement('div');
      bar.className = 'slide-handle-bar is-pinned';
      handles.forEach(op => {
        const btn = document.createElement('button');
        btn.className = 'slide-handle slide-handle--' + op + ' anc-handle-trigger';
        btn.textContent = op;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          refineElement(slide, op);
        });
        bar.appendChild(btn);
      });
      slide.appendChild(bar);
    });

    // Sub-element handles: small inline "+" trigger
    $content.querySelectorAll('[data-anc][data-handles]').forEach(el => {
      if (el.classList.contains('anc-slide')) return;
      if (el.querySelector('.anc-handle')) return;

      const handle = document.createElement('span');
      handle.className = 'anc-handle';
      handle.textContent = '+';
      handle.title = el.getAttribute('data-handles');
      handle.addEventListener('click', (e) => {
        e.stopPropagation();
        const handles = el.getAttribute('data-handles').split(',').map(h => h.trim()).filter(Boolean);
        showRefinePrompt(el, handles);
      });
      el.appendChild(handle);
    });
  }

  function showRefinePrompt(el, handles) {
    const anchorId = el.getAttribute('data-anc');
    const label = (el.textContent || '').slice(0, 50);
    const op = handles[0] || 'refine';
    const instruction = prompt('Refine "' + label + '" (' + op + '):');
    if (!instruction) return;
    sendEnvelope(anchorId, op, instruction);
  }

  function refineElement(el, op) {
    const anchorId = el.getAttribute('data-anc');
    const label = (el.querySelector('h1,h2') || el).textContent.slice(0, 50);
    const instruction = prompt(op + ' "' + label + '":');
    if (!instruction) return;
    sendEnvelope(anchorId, op, instruction);
  }

  function sendEnvelope(targetRef, op, instruction) {
    if (!ws || ws.readyState !== WebSocket.OPEN) { toast('Not connected'); return; }

    const envelope = {
      schema_version: '1.0',
      intent: {
        op: op,
        target_kind: 'anchor',
        target_ref: targetRef,
        instruction: instruction
      },
      provenance: {
        session_id: 'co-design',
        event_id: 'evt_' + Date.now(),
        parent_event_id: null,
        timestamp: new Date().toISOString(),
        client_version: '1.0'
      },
      context_bundle: { subagent_id: null, context_mode: 'standard' },
      render_state: { anchor_tree: [], dom_signature: '' }
    };

    send({ type: 'envelope', envelope: envelope });
    setStatus('refining...');
  }

  function showProcessing() {
    $content.innerHTML = '<div class="codesign-processing"><span class="processing-dot"></span> Generating slides...</div>';
  }

  function showWorkspace() {
    $start.style.display = 'none';
    $workspace.style.display = 'flex';
  }

  function showStart() {
    $start.style.display = '';
    $workspace.style.display = 'none';
    $content.innerHTML = '';
    $outline.innerHTML = '';
    $exportBtn.disabled = true;
    hasContent = false;
  }

  // ── Outline ───────────────────────────────────────────────────────

  function buildOutline() {
    const slides = $content.querySelectorAll('.anc-slide');
    $outline.innerHTML = '';
    slides.forEach((slide, i) => {
      const id = slide.getAttribute('data-anc');
      const h2 = slide.querySelector('h2');
      const h1 = slide.querySelector('h1');
      const label = (h2 || h1 || {}).textContent || 'Slide ' + (i + 1);
      const type = Array.from(slide.classList).find(c => c.startsWith('anc-slide--')) || '';

      const btn = document.createElement('button');
      btn.className = 'outline-item';
      btn.innerHTML = '<span class="outline-num">' + (i + 1) + '</span>' + label.slice(0, 40);
      btn.title = label;
      btn.addEventListener('click', () => {
        slide.scrollIntoView({ behavior: 'smooth', block: 'center' });
        document.querySelectorAll('.outline-item').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
      });
      $outline.appendChild(btn);
    });

    // Highlight first
    const first = $outline.firstChild;
    if (first) first.classList.add('is-active');
  }

  // Observe scroll to update active outline item
  function initScrollSpy() {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const id = entry.target.getAttribute('data-anc');
          document.querySelectorAll('.outline-item').forEach(b => b.classList.remove('is-active'));
          const items = $outline.children;
          const slides = $content.querySelectorAll('.anc-slide');
          const idx = Array.from(slides).indexOf(entry.target);
          if (items[idx]) items[idx].classList.add('is-active');
        }
      });
    }, { rootMargin: '-20% 0px -60% 0px' });

    // Observe slides after each render
    const mo = new MutationObserver(() => {
      $content.querySelectorAll('.anc-slide').forEach(s => observer.observe(s));
    });
    mo.observe($content, { childList: true, subtree: false });
  }

  // ── PPTX Export ────────────────────────────────────────────────────

  function exportPPTX() {
    if (!hasContent) { toast('Nothing to export'); return; }

    const slides = $content.querySelectorAll('.anc-slide');
    if (!slides.length) { toast('No slides found'); return; }

    try {
      const PptxGenJS = window.PptxGenJS;
      if (!PptxGenJS) { toast('PPTX library not loaded'); return; }

      const pptx = new PptxGenJS();
      pptx.defineLayout({ name:'SLIDE', width:'13.333', height:'7.5' });
      pptx.layout = 'SLIDE';

      slides.forEach(slide => {
        const type = Array.from(slide.classList).find(c => c.startsWith('anc-slide--'));
        const h1 = slide.querySelector('h1');
        const h2 = slide.querySelector('h2');
        const heading = (h2 || h1 || {}).textContent || '';
        const paras = slide.querySelectorAll('p');
        const listItems = slide.querySelectorAll('li');
        const codeBlock = slide.querySelector('pre code');
        const table = slide.querySelector('table');
        const meta = slide.querySelector('.slide-meta');

        const s = pptx.addSlide();

        if (type === 'anc-slide--title') {
          // Title slide: centered large heading
          if (heading) s.addText(heading, { x:0.8, y:2.0, w:11.7, h:1.6, fontSize:40, bold:true,
            fontFace:'Bricolage Grotesque', align:'center', color:'1A1A2E' });
          const subtitle = slide.querySelector('p');
          if (subtitle) s.addText(subtitle.textContent, { x:1.5, y:3.6, w:10.3, h:0.8, fontSize:18,
            fontFace:'Plus Jakarta Sans', align:'center', color:'6B7280' });
          if (meta) s.addText(meta.textContent, { x:1.5, y:4.6, w:10.3, h:0.6, fontSize:12,
            fontFace:'Plus Jakarta Sans', align:'center', color:'9CA3AF' });
        } else if (type === 'anc-slide--code' && codeBlock) {
          // Code slide: heading + code
          if (heading) s.addText(heading, { x:0.8, y:0.5, w:11.7, h:0.8, fontSize:24, bold:true,
            fontFace:'Bricolage Grotesque', color:'1A1A2E' });
          s.addText(codeBlock.textContent, { x:0.8, y:1.5, w:11.7, h:5.2, fontSize:11,
            fontFace:'JetBrains Mono', color:'F8FAFC', fill:{color:'1E293B'}, rectRadius:0.15, valign:'top' });
        } else if (type === 'anc-slide--table' && table) {
          // Table slide: heading + table
          if (heading) s.addText(heading, { x:0.8, y:0.5, w:11.7, h:0.8, fontSize:24, bold:true,
            fontFace:'Bricolage Grotesque', color:'1A1A2E' });
          const rows = [];
          table.querySelectorAll('tr').forEach(tr => {
            rows.push(Array.from(tr.querySelectorAll('th,td')).map(c => ({ text: c.textContent.trim() })));
          });
          if (rows.length) {
            s.addTable(rows, { x:0.8, y:1.5, w:11.7, border:{type:'solid', pt:0.5, color:'CFD8E5'},
              rowH:0.4, fontSize:12, fontFace:'Plus Jakarta Sans' });
          }
        } else {
          // Content / conclusion / diagram / generic slides
          if (heading) s.addText(heading, { x:0.8, y:0.5, w:11.7, h:0.8, fontSize:24, bold:true,
            fontFace:'Bricolage Grotesque', color:'1A1A2E' });

          if (listItems.length) {
            const items = Array.from(listItems).map(li => ({ text: li.textContent.trim() }));
            s.addText(items, { x:1.2, y:1.5, w:10.3, h:5.0, fontSize:16,
              fontFace:'Plus Jakarta Sans', color:'4B5563', bullet:true, valign:'top' });
          } else if (paras.length) {
            const text = Array.from(paras).map(p => p.textContent.trim()).join('\n\n');
            s.addText(text, { x:1.2, y:1.5, w:10.3, h:5.0, fontSize:16,
              fontFace:'Plus Jakarta Sans', color:'4B5563', valign:'top' });
          }
        }
      });

      pptx.writeFile({ fileName: 'co-design-deck.pptx' })
        .then(() => toast('PPTX downloaded'))
        .catch(() => toast('Export failed'));
    } catch (e) {
      console.error('[co-design] pptx export error:', e);
      toast('Export error: ' + e.message);
    }
  }

  // ── Toast ──────────────────────────────────────────────────────────

  function toast(message) {
    const el = document.createElement('div');
    el.className = 'codesign-toast';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }

  // ── Event bindings ────────────────────────────────────────────────

  $submit.addEventListener('click', () => submitPrompt($prompt.value));
  $prompt.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitPrompt($prompt.value); }
  });

  $exportBtn.addEventListener('click', exportPPTX);

  $newBtn.addEventListener('click', () => {
    showStart();
    $prompt.value = '';
    $prompt.focus();
  });

  $toggleOut.addEventListener('click', () => {
    $outlinePanel.classList.toggle('is-collapsed');
    const icon = $toggleOut.querySelector('i');
    if (icon) {
      icon.className = $outlinePanel.classList.contains('is-collapsed')
        ? 'ph-bold ph-sidebar-simple'
        : 'ph-bold ph-sidebar';
    }
  });

  // Template buttons
  document.querySelectorAll('[data-template]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tpl = btn.dataset.template;
      const prompts = {
        'tech-arch': 'A technical deck reviewing the current system architecture, identifying bottlenecks, and proposing a new event-driven architecture with clear migration steps.',
        'quarterly': 'An engineering quarterly update deck covering Q2 milestones, key metrics (deployment frequency, incident count, latency), hiring progress, and Q3 roadmap.',
        'proposal': 'A technical proposal for adopting Kubernetes as the standard deployment platform, covering current pain points, alternatives considered, cost analysis, and rollout plan.',
      };
      $prompt.value = prompts[tpl] || '';
      $prompt.focus();
    });
  });

  // ── Init ───────────────────────────────────────────────────────────

  initScrollSpy();
  connect();
  $prompt.focus();
})();
