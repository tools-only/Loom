// Orchestration View - renders Brain dispatch DAG
// Self-mounts on [data-anc="orchestration-snapshot"] via MutationObserver.
// Fetches workspace data for rich hand profiles and artifact quality metrics.

(function () {
  "use strict";

  var BRAIN_URL = "http://127.0.0.1:3002";
  var ATTR = "data-orc-mounted";
  var WS_ATTR = "data-orc-ws-loaded";

  var icons = {
    brain: "ph-bold ph-brain",
    task: "ph-bold ph-check-square",
    hand: "ph-bold ph-hand",
    artifact: "ph-bold ph-file-text",
    review: "ph-bold ph-magnifying-glass",
    source: "ph-bold ph-link"
  };

  function h(str) {
    if (str == null) return "";
    var d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  function formatNum(n) {
    if (n == null || isNaN(n)) return "0";
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return String(n);
  }

  function scoreBar(label, val, lo, hi) {
    var pct = Math.max(0, Math.min(100, ((val - lo) / (hi - lo)) * 100));
    var color = pct >= 70 ? "var(--accent-lime)" : pct >= 40 ? "var(--accent-amber)" : "var(--accent-rose)";
    return '<div class="aq-metric">' +
      '<div class="aq-metric-label">' + h(label) + '</div>' +
      '<div class="aq-metric-bar"><div class="aq-metric-fill" style="width:' + pct.toFixed(0) + '%;background:' + color + '"></div></div>' +
      '<div class="aq-metric-val">' + (typeof val === "number" ? val.toFixed(1) : val) + '</div>' +
      '</div>';
  }

  function nodeCard(n, profiles) {
    var ntype = n.type || "?";
    var nlabel = h((n.label || "?").toString());
    var nid = h((n.id || "").toString());
    var icon = icons[ntype] || "ph-bold ph-circle";

    var meta = "";
    if (ntype === "task" && n.task) {
      meta = '<div class="orc-node-task">' + h(n.task.slice(0, 80)) + '</div>';
    }
    if (ntype === "artifact") {
      var conf = Number(n.confidence) || 0;
      var claims = Number(n.claim_count) || 0;
      var gaps = Number(n.gap_count) || 0;
      var qm = n.quality_metrics || {};
      var confPill = "anc-pill--active";
      if (conf <= 0.4) confPill = "anc-pill--warn";
      else if (conf <= 0.7) confPill = "anc-pill--review";
      meta =
        '<div class="orc-node-meta">' +
        '<span class="anc-pill ' + confPill + '" style="font-size:10px">conf ' + Math.round(conf * 100) + '%</span>' +
        '<span style="font-size:10px;color:var(--ink-3)">' + claims + ' claims</span>' +
        (qm.char_length ? '<span style="font-size:9px;color:var(--ink-3)">' + formatNum(qm.char_length) + ' ch</span>' : "") +
        (gaps ? '<span class="anc-pill anc-pill--warn" style="font-size:10px">' + gaps + ' gaps</span>' : "") +
        '</div>';
    }

    if (ntype === "hand") {
      var hid = (n.id || "").replace(/^hand:/, "");
      meta = '<div class="orc-node-meta orc-hand-meta">';
      if (n.executor_id) meta += '<span style="font-size:9px;color:var(--ink-3)">via ' + h(String(n.executor_id).slice(0, 20)) + '</span>';
      if (hid && profiles) {
        var pi = profiles[hid];
        if (pi) {
          // Inline: show tools/MCPs/skills icons
          var tags = [];
          if (pi.tools && pi.tools.length) tags.push('<span class="orc-inline-tag orc-tag-tool" title="' + h(pi.tools.join(", ")) + '"><i class="ph-bold ph-wrench"></i>' + pi.tools.length + '</span>');
          if (pi.mcp_servers && pi.mcp_servers.length) tags.push('<span class="orc-inline-tag orc-tag-mcp" title="' + h(pi.mcp_servers.join(", ")) + '"><i class="ph-bold ph-plugs"></i>' + pi.mcp_servers.length + '</span>');
          if (pi.skills && pi.skills.length) tags.push('<span class="orc-inline-tag orc-tag-skill" title="' + h(pi.skills.join(", ")) + '"><i class="ph-bold ph-lightning"></i>' + pi.skills.length + '</span>');
          if (tags.length) meta += '<div style="display:flex;gap:3px;margin-top:3px">' + tags.join("") + '</div>';
        }
      }
      meta += '</div>';
    }

    return (
      '<div class="orc-node orc-node--' + ntype + '" data-orc-node="' + nid + '">' +
      '<i class="' + icon + '"></i>' +
      '<span class="orc-node-label">' + nlabel + '</span>' +
      meta +
      '</div>'
    );
  }

  function buildPipeline(nodes, profiles) {
    var groups = { brain: [], task: [], hand: [], artifact: [], review: [] };
    (nodes || []).forEach(function (n) {
      var t = n.type || "";
      if (groups[t]) groups[t].push(n);
    });

    var cols = [];
    var order = [
      ["Brain", "brain"],
      ["Tasks", "task"],
      ["Hands", "hand"],
      ["Artifacts", "artifact"],
      ["Review", "review"]
    ];

    order.forEach(function (pair) {
      var label = pair[0];
      var key = pair[1];
      var list = groups[key];
      if (!list.length) return;
      var cards = list.map(function(n) { return nodeCard(n, profiles); }).join("");
      cols.push(
        '<div class="orc-col">' +
        '<div class="orc-col-label">' + label + '</div>' +
        '<div class="orc-col-cards">' + cards + '</div>' +
        '</div>'
      );
    });

    if (!cols.length) return "";

    var parts = [];
    cols.forEach(function (col, i) {
      parts.push(col);
      if (i < cols.length - 1) {
        parts.push(
          '<div class="orc-connector">' +
          '<i class="ph-bold ph-arrow-right"></i>' +
          '</div>'
        );
      }
    });

    return '<div class="orc-pipeline">' + parts.join("") + '</div>';
  }

  function buildDiagnostics(diags) {
    if (!diags || !diags.length) return "";
    var items = diags.map(function (d) {
      var dtype = d.type || "?";
      var msg = h((d.message || "").toString());
      var ref = h((d.object_ref || "").toString());
      var dicon = dtype === "review_gap" ? "ph-bold ph-magnifying-glass" : "ph-bold ph-warning";
      return (
        '<div class="orc-diag-item">' +
        '<i class="' + dicon + '" style="font-size:14px;color:var(--ink-3)"></i>' +
        '<span class="anc-pill anc-pill--edit" style="font-size:9px">' + ref + '</span>' +
        '<span style="font-size:11px;color:var(--ink-2)">' + msg + '</span>' +
        '</div>'
      );
    }).join("");
    return (
      '<details class="orc-diag-details" open>' +
      '<summary>Diagnostics (' + diags.length + ')</summary>' +
      items +
      '</details>'
    );
  }

  // Rich hand profile card
  function buildRichHandProfile(pid, pi) {
    if (!pi) return "";
    var html = '<div class="orc-hand-profile" data-hand-profile="' + h(pid) + '">';
    html += '<div class="orc-hp-header">';
    html += '<i class="ph-bold ph-robot" style="color:var(--accent-iris);font-size:14px"></i>';
    html += '<span class="orc-hp-label">' + h(pi.label || pi.agent_id || pid) + '</span>';
    if (pi.base_model && pi.base_model !== "unknown") {
      html += '<span class="orc-hp-model">' + h(pi.base_model) + '</span>';
    }
    html += '</div>';
    if (pi.description) {
      html += '<div class="orc-hp-desc">' + h(String(pi.description).slice(0, 160)) + '</div>';
    }
    var hasTags = (pi.tools && pi.tools.length) || (pi.mcp_servers && pi.mcp_servers.length) ||
                  (pi.skills && pi.skills.length) || (pi.capabilities && pi.capabilities.length);
    if (hasTags) {
      html += '<div class="orc-hp-tags">';
      (pi.capabilities || []).slice(0, 6).forEach(function(c) {
        html += '<span class="orc-hp-tag orc-tag-cap">' + h(String(c).slice(0, 24)) + '</span>';
      });
      (pi.tools || []).slice(0, 5).forEach(function(t) {
        html += '<span class="orc-hp-tag orc-tag-tool"><i class="ph-bold ph-wrench"></i> ' + h(String(t).slice(0, 24)) + '</span>';
      });
      (pi.mcp_servers || []).slice(0, 3).forEach(function(m) {
        html += '<span class="orc-hp-tag orc-tag-mcp"><i class="ph-bold ph-plugs"></i> ' + h(String(m).slice(0, 24)) + '</span>';
      });
      (pi.skills || []).slice(0, 3).forEach(function(s) {
        html += '<span class="orc-hp-tag orc-tag-skill"><i class="ph-bold ph-lightning"></i> ' + h(String(s).slice(0, 24)) + '</span>';
      });
      html += '</div>';
    }
    if (pi.task_snippet) {
      html += '<div class="orc-hp-task"><i class="ph-bold ph-check-square" style="font-size:10px"></i> ' + h(String(pi.task_snippet).slice(0, 140)) + '</div>';
    }
    if (pi.system_prompt_snippet) {
      html += '<details class="orc-hp-prompt"><summary>System prompt excerpt</summary>';
      html += '<div class="orc-hp-prompt-body">' + h(String(pi.system_prompt_snippet).slice(0, 600)) + '</div>';
      html += '</details>';
    }
    html += '</div>';
    return html;
  }

  // Artifact quality evaluation
  function buildArtifactQuality(an) {
    var qm = an.quality_metrics || {};
    if (!qm || Object.keys(qm).length === 0) return "";
    var html = '<div class="orc-aq-card" data-artifact-id="' + h(an.id || "") + '">';
    html += '<div class="orc-aq-header"><i class="ph-bold ph-file-text" style="color:var(--accent-iris)"></i> ' + h(an.label || "Artifact") + '</div>';
    html += '<div class="orc-aq-metrics">';
    html += '<div class="orc-aq-metric"><span>Chars</span><strong>' + formatNum(qm.char_length || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Words</span><strong>' + formatNum(qm.estimated_words || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Tokens</span><strong>' + formatNum(qm.estimated_tokens || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Sections</span><strong>' + (qm.section_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Headings</span><strong>' + (qm.heading_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Lists</span><strong>' + (qm.list_item_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Code</span><strong>' + (qm.code_block_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Claims</span><strong>' + (qm.claim_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Evid</span><strong>' + (qm.evidence_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Sources</span><strong>' + (qm.source_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Gaps</span><strong style="color:' + (qm.gap_count > 0 ? "var(--accent-amber)" : "var(--accent-lime)") + '">' + (qm.gap_count || 0) + '</strong></div>';
    html += '<div class="orc-aq-metric"><span>Conf</span><strong>' + ((Number(qm.confidence_score) || 0) * 100).toFixed(0) + '%</strong></div>';
    html += '</div>';
    html += '<div class="orc-aq-scores">';
    html += scoreBar("Richness", Math.min(100, ((qm.section_count || 0) * (qm.heading_count || 0) / Math.max(1, qm.estimated_words || 1)) * 100), 3, 10);
    html += scoreBar("ArgDensity", Math.min(100, ((qm.claim_count || 0) / Math.max(1, qm.estimated_words || 1)) * 1000), 5, 20);
    html += scoreBar("EvidRatio", Math.min(100, ((qm.evidence_count || 0) / Math.max(1, qm.claim_count || 1)) * 100), 50, 200);
    html += scoreBar("Structure", qm.structured_output ? 100 : (qm.heading_count > 0 ? 50 : 20), 40, 80);
    html += scoreBar("Specificity", Math.min(100, (((qm.code_block_count || 0) + (qm.list_item_count || 0)) / Math.max(1, qm.estimated_words || 1)) * 1000), 10, 40);
    html += scoreBar("ConfStab", qm.claim_count > 0 ? Math.max(0, 100 - ((qm.gap_count || 0) / Math.max(1, qm.claim_count)) * 100) : 50, 50, 90);
    html += '</div>';
    html += '<div class="orc-aq-flags">';
    if (qm.structured_output) {
      html += '<span class="orc-aq-flag orc-aq-flag-good">Structured</span>';
    } else {
      html += '<span class="orc-aq-flag orc-aq-flag-info">Free-form</span>';
    }
    var freshClass = qm.freshness_flag === "fresh" ? "orc-aq-flag-good" : qm.freshness_flag === "stale" ? "orc-aq-flag-bad" : "orc-aq-flag-warn";
    html += '<span class="orc-aq-flag ' + freshClass + '">Fresh: ' + h(qm.freshness_flag || "?") + '</span>';
    var consisClass = qm.consistency_flag === "clean" ? "orc-aq-flag-good" : "orc-aq-flag-warn";
    html += '<span class="orc-aq-flag ' + consisClass + '">Consis: ' + h(qm.consistency_flag || "?") + '</span>';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // Load workspace data and enrich
  async function loadWorkspaceAndEnrich(el, epid, data) {
    if (el.hasAttribute(WS_ATTR)) return;
    el.setAttribute(WS_ATTR, "loading");
    try {
      var wsResp = await fetch(BRAIN_URL + "/episodes/" + encodeURIComponent(epid) + "/workspace");
      var ws = await wsResp.json();
      if (!ws.ok) { el.setAttribute(WS_ATTR, "0"); return; }

      var orchestration = ws.orchestration || data.orchestration || data;
      var profiles = orchestration.profiles || {};
      var nodes = orchestration.nodes || [];

      // Render rich hand profiles below the DAG
      var profileKeys = Object.keys(profiles);
      if (profileKeys.length) {
        var hpContainer = document.createElement("div");
        hpContainer.className = "orc-hp-section";
        hpContainer.innerHTML = '<h5 style="margin:10px 0 6px;font-size:12px;color:var(--ink-2)">' +
          '<i class="ph-bold ph-robot"></i> Hand Profiles (' + profileKeys.length + ')</h5>';
        profileKeys.forEach(function(pid) {
          hpContainer.innerHTML += buildRichHandProfile(pid, profiles[pid]);
        });
        var pipelineEl = el.querySelector(".orc-pipeline");
        if (pipelineEl) {
          pipelineEl.insertAdjacentElement("afterend", hpContainer);
        } else {
          el.appendChild(hpContainer);
        }
      }

      // Render artifact quality cards
      var artifactNodes = nodes.filter(function(n) { return n.type === "artifact" && n.quality_metrics; });
      if (artifactNodes.length) {
        var aqContainer = document.createElement("div");
        aqContainer.className = "orc-aq-section";
        aqContainer.innerHTML = '<h5 style="margin:10px 0 6px;font-size:12px;color:var(--ink-2)">' +
          '<i class="ph-bold ph-file-text"></i> Artifact Quality (' + artifactNodes.length + ')</h5>';
        artifactNodes.forEach(function(an) {
          aqContainer.innerHTML += buildArtifactQuality(an);
        });
        el.appendChild(aqContainer);
      }

      // Add Harness Dashboard link
      var harnessLink = document.createElement("div");
      harnessLink.className = "orc-harness-link";
      harnessLink.innerHTML = '<a href="http://127.0.0.1:3002/harness" target="_blank" style="display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:8px;border:1px solid var(--accent-iris);color:var(--accent-iris);text-decoration:none;font-size:11px;font-weight:600;margin-top:10px">' +
        '<i class="ph-bold ph-graph"></i> Open Harness Dashboard</a>';
      el.appendChild(harnessLink);

      el.setAttribute(WS_ATTR, "1");
    } catch (_) {
      el.setAttribute(WS_ATTR, "0");
    }
  }

  function buildProfiles(profiles) {
    if (!profiles || !Object.keys(profiles).length) return "";
    var pills = Object.keys(profiles).map(function (pid) {
      var pinfo = profiles[pid] || {};
      var plabel = h((pinfo.label || pinfo.agent_id || pid).toString());
      var pdesc = h((pinfo.description || "").toString().slice(0, 80));
      return (
        '<div class="orc-profile-pill">' +
        '<i class="ph-bold ph-robot" style="font-size:11px"></i>' +
        '<span>' + plabel + '</span>' +
        (pdesc ? '<span style="opacity:0.5;font-size:10px;margin-left:6px">' + pdesc + '</span>' : "") +
        '</div>'
      );
    }).join("");
    return '<div class="orc-profiles">' + pills + '</div>';
  }

  function renderOrchestration(el, data) {
    var snapshot = data.orchestration || data;
    var nodes = snapshot.nodes || [];
    var diags = snapshot.diagnostics || [];
    var profiles = snapshot.profiles || {};
    var epid = h((snapshot.episode_id || "").toString());
    var goal = h((snapshot.goal || "").toString().slice(0, 80));
    var domain = h((snapshot.domain || "general").toString());
    var mode = h((snapshot.workflow_mode || "").toString());

    el.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">' +
      '<div class="anc-pill-row">' +
      '<span class="anc-pill anc-pill--gen">Orchestration</span>' +
      '<span class="anc-pill anc-pill--review">' + domain + '</span>' +
      (mode ? '<span class="anc-pill anc-pill--draft">' + mode + '</span>' : "") +
      '</div>' +
      '<button class="orc-expand-btn" title="Expand/Collapse" style="background:none;border:1px solid var(--border);border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--ink-3);font-size:14px" ' +
      'onclick="var s=this.closest(\'section\');if(s){s.classList.toggle(\'orc-expanded\');this.innerHTML=s.classList.contains(\'orc-expanded\')?' +
      '\'<i class=ph-bold ph-arrows-in></i>\':\'<i class=ph-bold ph-arrows-out></i>\';}">' +
      '<i class="ph-bold ph-arrows-out"></i></button>' +
      '</div>' +
      '<h3 style="font-size:15px;margin:6px 0 4px">' + goal + '</h3>' +
      buildProfiles(profiles) +
      buildPipeline(nodes, profiles) +
      buildDiagnostics(diags) +
      '<div style="font-size:10px;color:var(--ink-3);margin-top:8px">' + epid + '</div>';

    if (epid) {
      loadWorkspaceAndEnrich(el, epid, data);
    }

    el.setAttribute(ATTR, "1");
  }

  async function refreshFromAPI(el) {
    var epid = el.getAttribute("data-episode-id");
    if (!epid) return;
    try {
      var resp = await fetch(BRAIN_URL + "/orchestration/" + encodeURIComponent(epid));
      var data = await resp.json();
      if (data.ok) {
        renderOrchestration(el, data);
      }
    } catch (_) { /* offline */ }
  }

  function mount(el) {
    if (el.hasAttribute(ATTR)) return;
    var epid = el.getAttribute("data-episode-id");
    if (epid) {
      el.setAttribute(ATTR, "1");
    } else {
      refreshFromAPI(el);
    }
  }

  function mountAll(root) {
    (root || document).querySelectorAll(
      '[data-anc="orchestration-snapshot"]:not([' + ATTR + '])'
    ).forEach(mount);
  }

  var observer = new MutationObserver(function () { mountAll(); });
  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { mountAll(); });
  } else {
    mountAll();
  }

  window.OrchestrationView = {
    refresh: function (el) { return refreshFromAPI(el); },
    mountAll: mountAll
  };
})();
