"use strict";

// Top-level detail state. The AI Calls mode remains a separate state owned by app.js.
let detailTab = "current";
const stepToggleModes = new Map();
function getStepModes(stepIndex) {
  return stepToggleModes.get(stepIndex) || new Set(['tokens', 'cost', 'pct']);
}

(function installDetailAuditTabs() {
  // app.js already keeps these references before its grouped-AI monkey patch.
  // Fall back to the currently installed renderers for compatibility with an older build.
  const legacyRenderHeader = typeof oldRenderHeader === "function" ? oldRenderHeader : renderHeader;
  const legacyRenderSteps = typeof oldRenderSteps === "function" ? oldRenderSteps : renderSteps;
  const legacyRenderSelection = renderSelection;
  const legacyRenderAuditPanel = renderAuditPanel;

  function isLegacyTab() {
    return detailTab === "legacy";
  }

  function setVisible(element, visible) {
    if (element) element.hidden = !visible;
  }

  function applyDetailLayout() {
    const legacy = isLegacyTab();
    document.body.dataset.detailTab = legacy ? "legacy" : "current";
    setVisible(document.getElementById("stats"), legacy);
    setVisible(document.querySelector("main.right > .toolbar"), legacy);
    setVisible(document.getElementById("auditPanel"), legacy);

    const groupedExport = document.getElementById("groupedAiCallsExportButton");
    setVisible(groupedExport, !legacy);
    renderDetailTabs();
  }

  function renderDetailTabs() {
    document.querySelectorAll("[data-detail-tab]").forEach(button => {
      const selected = button.dataset.detailTab === detailTab;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
      button.tabIndex = selected ? 0 : -1;
    });
  }

  function renderCurrentHeader() {
    applyDetailLayout();

    const title = document.getElementById("title");
    const meta = document.getElementById("meta");
    const stats = document.getElementById("stats");
    if (stats) stats.innerHTML = "";

    const session = sessionDetailCache;
    if (!session) {
      const selectedSession = currentSession();
      if (title) {
        title.textContent = selectedSession && sessionDetailLoading
          ? "Загрузка сессии..."
          : "Выберите сессию";
      }
      if (meta) meta.textContent = selectedSession ? selectedSession.title : "";
      updateGroupedAiCallsExportButton(null);
      return;
    }

    const source = currentSource();
    const sourceKind = session.source_kind === "live" ? "live" : "архив";
    const summary = session.ai_calls_honest_audit_summary || {};
    const calls = Array.isArray(session.ai_calls) ? session.ai_calls : [];
    const grouping = buildAiCallsGrouping(session);
    const withUsage = summary.ai_calls_with_usage
      ?? calls.filter(call => call?.is_zero_usage !== true).length;
    const zeroUsage = summary.ai_calls_zero_usage
      ?? calls.filter(call => call?.is_zero_usage === true).length;
    const unmapped = summary.ai_calls_unmapped ?? grouping.unmapped.length;

    if (title) title.textContent = session.title || session.id || "Сессия";
    if (meta) {
      meta.textContent = [
        `${source ? source.name : ""} [${sourceKind}]`,
        session.id || "",
        session.date || "",
        session.workdir || "",
        `AI calls: ${withUsage} with usage / ${zeroUsage} zero / ${unmapped} unmapped`,
      ].filter(Boolean).join(" · ");
    }
    updateGroupedAiCallsExportButton(session);
    updateRawDownloadButtons();
  }

  function computeTokenBreakdown(summary) {
    const outputT = summary.usage.output_tokens || 0;
    const reasoningT = summary.usage.reasoning_tokens || 0;
    const nonReasoningT = Math.max(outputT - reasoningT, 0);
    const outputCost = summary.estimated_cost.estimated_output_cost_usd || 0;
    const reasoningCost = outputT > 0 && reasoningT > 0 ? outputCost * (reasoningT / outputT) : 0;

    return [
      { label: 'Cached', tokens: summary.usage.cached_tokens || 0, cost: summary.estimated_cost.estimated_cached_input_cost_usd || 0 },
      { label: 'New input', tokens: summary.usage.non_cached_input_tokens || 0, cost: summary.estimated_cost.estimated_input_cost_usd || 0 },
      { label: 'Reasoning', tokens: reasoningT, cost: reasoningCost },
      { label: 'Output', tokens: nonReasoningT, cost: outputCost - reasoningCost },
    ];
  }

  function renderTokenBreakdown(categories, totalCost) {
    const total = totalCost > 0 ? totalCost : categories.reduce((s, c) => s + c.cost, 0);
    const rows = categories.map(c => {
      const pct = total > 0 ? (c.cost / total * 100) : 0;
      return `<tr>
        <td class="label">${c.label}</td>
        <td class="num">${nf.format(c.tokens)}</td>
        <td class="num strong">$${c.cost.toFixed(5)}</td>
        <td class="num muted">${pct.toFixed(1)}%</td>
      </tr>`;
    }).join('');
    return `<table class="ai-calls-breakdown-table">
      <thead><tr>
        <th>Category</th>
        <th class="num">Tokens</th>
        <th class="num">Cost USD</th>
        <th class="num">%</th>
      </tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  // ── Injected styles for token-type colors ──
  (function injectStepStyles() {
    if (document.getElementById("detail-audit-tabs-step-style")) return;
    const s = document.createElement("style");
    s.id = "detail-audit-tabs-step-style";
    s.textContent = [
      ".ct-cached { color:#7cb8ff }",
      ".ct-input { color:#b3a0ff }",
      ".ct-reasoning { color:#ff9f7c }",
      ".ct-output { color:#7cffa0 }",
      ".ai-calls-metric-toggles { display:flex;gap:4px;flex-wrap:wrap }",
      ".ai-calls-table { border-collapse:collapse }",
      ".ai-calls-table th, .ai-calls-table td { border:1px solid #3a3a3a;padding:2px 4px }",
      ".ai-calls-table thead th { border-bottom:2px solid #555 }",
      ".ai-calls-table th.id-block, .ai-calls-table td.id-block { border-right:2px solid #666 }",
      ".ai-calls-table th.ct-compact, .ai-calls-table td.ct-compact { white-space:nowrap;padding:1px 2px;width:1%;text-align:left }",
      ".ai-calls-table td.num, .ai-calls-table th.num { padding:2px 4px;text-align:right }",
    ].join("\n");
    document.head.appendChild(s);
  })();

  // ── New per-call table for current grouped audit ──
  // Multi-metric: each category cell stacks enabled metrics (tokens / cost / pct)
  // Table structure: # | Time | Model | Cached | New input | Reasoning | Output
  function renderMultiCategoryCells(categories, totalCost, activeModes) {
    const total = totalCost > 0 ? totalCost : categories.reduce((s, c) => s + c.cost, 0);
    const colorClasses = ['ct-cached', 'ct-input', 'ct-reasoning', 'ct-output'];
    const modeOrder = ['tokens', 'cost', 'pct'];
    const activeArr = modeOrder.filter(k => activeModes.has(k));
    const parts = [];
    categories.forEach((c, i) => {
      activeArr.forEach(mode => {
        let val;
        if (mode === 'tokens') val = nf.format(c.tokens);
        else if (mode === 'cost') val = `$${c.cost.toFixed(5)}`;
        else {
          const pct = total > 0 ? (c.cost / total * 100) : 0;
          val = `${pct.toFixed(1)}%`;
        }
        parts.push(`<td class="num ${colorClasses[i]}">${val}</td>`);
      });
    });
    return parts.join('');
  }

  function renderCurrentCallTable(calls, session, stepIndex, activeModes) {
    const list = Array.isArray(calls) ? calls : [];
    if (!list.length) return '';
    if (!activeModes || activeModes.size === 0) activeModes = new Set(['tokens']);
    const stepSummary = aggregateAiCalls(list, session);
    const stepCategories = computeTokenBreakdown(stepSummary);
    const stepTotalCost = stepSummary.estimated_cost.estimated_total_cost_usd || 0;

    const colorClasses = ['ct-cached', 'ct-input', 'ct-reasoning', 'ct-output'];
    const catLabels = ['Cached', 'New input', 'Reasoning', 'Output'];

    const modeOrder = ['tokens', 'cost', 'pct'];
    const activeArr = modeOrder.filter(k => activeModes.has(k));
    const N = activeArr.length;
    const showTime = activeModes.has('time');
    const showModel = activeModes.has('model');

    const subLabels = activeArr.map(k => {
      if (k === 'tokens') return 'токены';
      if (k === 'cost') return '$';
      return '%';
    });

    let theadHtml;
    if (N === 1) {
      theadHtml = `<thead><tr>
        <th class="num id-block" rowspan="1">#</th>
        ${showTime ? '<th class="ct-compact id-block" rowspan="1">Time</th>' : ''}
        ${showModel ? '<th class="ct-compact id-block" rowspan="1">Model</th>' : ''}
        <th class="num id-block" rowspan="1">Стоимость вызова</th>
        <th class="num id-block" rowspan="1">% от шага</th>
        ${catLabels.map((name, i) =>
          `<th class="num ${colorClasses[i]}">${name}</th>`
        ).join('')}
      </tr></thead>`;
    } else {
      theadHtml = `<thead><tr>
        <th class="num id-block" rowspan="2">#</th>
        ${showTime ? '<th class="ct-compact id-block" rowspan="2">Time</th>' : ''}
        ${showModel ? '<th class="ct-compact id-block" rowspan="2">Model</th>' : ''}
        <th class="num id-block" rowspan="2">Стоимость вызова</th>
        <th class="num id-block" rowspan="2">% от шага</th>
        ${catLabels.map((name, i) =>
          `<th class="num ${colorClasses[i]}" colspan="${N}">${name}</th>`
        ).join('')}
      </tr><tr>
        ${catLabels.map((_, i) =>
          subLabels.map(label =>
            `<th class="num xsmall ${colorClasses[i]}">${label}</th>`
          ).join('')
        ).join('')}
      </tr></thead>`;
    }

    const summaryRow = `<tr class="ai-call-table-summary">
      <td class="num id-block">Σ</td>
      ${showTime ? '<td class="ct-compact id-block">—</td>' : ''}
      ${showModel ? `<td class="ct-compact id-block">${formatAiCallNumber(stepSummary.ai_calls_count)} calls</td>` : ''}
      <td class="num id-block">${formatAiCallMoney(stepTotalCost)}</td>
      <td class="num id-block">100%</td>
      ${renderMultiCategoryCells(stepCategories, stepTotalCost, activeModes)}
    </tr>`;
    const callRows = list.map(call => {
      const callSummary = aggregateAiCalls([call], session);
      const callCategories = computeTokenBreakdown(callSummary);
      const callTotalCost = callSummary.estimated_cost.estimated_total_cost_usd || 0;
      const timestamp = call?.timestamp ? new Date(call.timestamp).toLocaleTimeString("ru-RU") : "—";
      const callPct = stepTotalCost > 0 ? `${(callTotalCost / stepTotalCost * 100).toFixed(1)}%` : "—";
      return `<tr class="${call?.is_zero_usage ? 'ai-call-zero' : ''}">
        <td class="num id-block">${formatAiCallNumber(call?.call_index)}</td>
        ${showTime ? `<td class="ct-compact id-block">${escapeHtml(timestamp)}</td>` : ''}
        ${showModel ? `<td class="ct-compact id-block">${escapeHtml(call?.model || "unknown")}</td>` : ''}
        <td class="num id-block">${formatAiCallMoney(callTotalCost)}</td>
        <td class="num id-block">${callPct}</td>
        ${renderMultiCategoryCells(callCategories, callTotalCost, activeModes)}
      </tr>`;
    }).join('');
    return `<div class="ai-calls-table-wrap">
      <table class="ai-calls-table">
        ${theadHtml}
        <tbody>
          ${summaryRow}
          ${callRows}
        </tbody>
      </table>
    </div>`;
  }

  function appendMappedGroup(root, session, stepIndex, calls) {
    const summary = aggregateAiCalls(calls, session);
    const step = (session.steps || []).find(s => Number(s.step_index) === stepIndex);
    const promptLabel = step
      ? (step.user_prompt?.kind === 'system_composed' ? 'System prompt' : 'User prompt')
      : 'Prompt';

    const activeModes = getStepModes(stepIndex);
    const card = document.createElement("section");
    card.className = "box ai-calls-current-group";
    card.dataset.stepIndex = String(stepIndex);
    const callTableHtml = renderCurrentCallTable(calls, session, stepIndex, activeModes);

    const toggleKeys = [
      { key: 'tokens', label: 'Токены' },
      { key: 'cost', label: 'Стоимость' },
      { key: 'pct', label: '% стоимости' },
      { key: 'time', label: 'Время' },
      { key: 'model', label: 'Модель' },
    ];
    const toggleHtml = toggleKeys.map(t =>
      `<button class="ghost small${activeModes.has(t.key) ? ' active' : ''}" data-key="${t.key}">${t.label}</button>`
    ).join('');

    card.innerHTML = `
      <div class="ai-calls-current-group-head">
        <div>
          <h3>Запрос / Step ${escapeHtml(stepIndex)}</h3>
          <div class="muted xsmall">Call-level группа с prompt/answer и разбивкой по типам токенов.</div>
        </div>
        <div class="ai-calls-current-group-actions">
          <span class="pill blue">${formatAiCallNumber(summary.ai_calls_count)} AI calls</span>
          <div class="ai-calls-metric-toggles">${toggleHtml}</div>
        </div>
      </div>
      <div class="ai-call-prompt-actions">
        <button class="ghost small" onclick="openCallTextPopup(${stepIndex},'prompt')">${promptLabel}</button>
        <button class="ghost small" onclick="openCallTextPopup(${stepIndex},'answer')">Assistant answer</button>
      </div>
      <div class="ai-call-group-detail ai-calls-current-table">
        ${callTableHtml}
      </div>`;

    card.querySelectorAll('.ai-calls-metric-toggles button').forEach(btn => {
      btn.addEventListener('click', function () {
        const key = this.dataset.key;
        const si = Number(card.dataset.stepIndex);
        let modes = stepToggleModes.get(si);
        if (!modes) {
          modes = new Set(['tokens', 'cost', 'pct']);
          stepToggleModes.set(si, modes);
        }
        const isMetric = key === 'tokens' || key === 'cost' || key === 'pct';
        const activeMetricCount = [...modes].filter(k => k === 'tokens' || k === 'cost' || k === 'pct').length;
        if (isMetric && activeMetricCount <= 1) return;
        if (modes.has(key)) {
          modes.delete(key);
          this.classList.remove('active');
        } else {
          modes.add(key);
          this.classList.add('active');
        }
        const detail = card.querySelector('.ai-call-group-detail');
        if (detail) {
          detail.innerHTML = renderCurrentCallTable(calls, session, si, modes);
        }
      });
    });

    root.appendChild(card);
  }

  function appendUnmappedGroup(root, session, calls) {
    const summary = aggregateAiCalls(calls, session);
    const card = document.createElement("details");
    card.className = `ai-calls-unmapped-card${calls.length ? "" : " empty-group"}`;
    card.open = true;
    card.innerHTML = `
      <summary>
        <div>
          <b>Unmapped AI calls</b>
          <span class="muted xsmall">Нет доказуемой связи с существующим visible step.</span>
        </div>
        <div class="pills">
          <span class="pill red">${formatAiCallNumber(summary.ai_calls_count)} calls</span>
          <span class="pill">Cost ${formatAiCallMoney(summary.estimated_cost.estimated_total_cost_usd)}</span>
          <span class="pill">${formatAiCallPercent(summary.percent_of_session_total)} session</span>
        </div>
      </summary>
      <div class="ai-calls-unmapped-body">
        ${renderAiCallTable(calls, session, true)}
      </div>`;
    root.appendChild(card);
  }

  function renderCurrentGrouped(root, session) {
    const grouping = buildAiCallsGrouping(session);
    const rendered = new Set();

    (session.steps || []).forEach(step => {
      const stepIndex = Number(step?.step_index);
      if (!Number.isInteger(stepIndex) || stepIndex <= 0 || rendered.has(stepIndex)) return;
      rendered.add(stepIndex);
      appendMappedGroup(root, session, stepIndex, grouping.byStep.get(stepIndex) || []);
    });

    // Defensive compatibility: render a valid mapped bucket even if steps[] is incomplete.
    for (const [stepIndex, calls] of grouping.byStep.entries()) {
      if (rendered.has(stepIndex)) continue;
      rendered.add(stepIndex);
      appendMappedGroup(root, session, stepIndex, calls);
    }

    appendUnmappedGroup(root, session, grouping.unmapped || []);
  }

  function renderCurrentSteps() {
    applyDetailLayout();
    const root = document.getElementById("steps");
    if (!root) return;
    root.innerHTML = "";

    const session = sessionDetailCache;
    if (!session) {
      root.innerHTML = `<div class="loading">${currentSession() && sessionDetailLoading
        ? "Загрузка AI calls..."
        : "Выберите сессию слева"}</div>`;
      updateGroupedAiCallsExportButton(null);
      return;
    }

    updateGroupedAiCallsExportButton(session);
    const overview = renderAiCallsOverview(session);
    root.appendChild(overview);

    const sessionSummary = aggregateAiCalls(session.ai_calls || [], session);
    const sessionCategories = computeTokenBreakdown(sessionSummary);
    const sessionCostBasis = sessionSummary.session_total_cost_usd || sessionSummary.estimated_cost.estimated_total_cost_usd || 0;
    const sessionBreakdown = document.createElement("section");
    sessionBreakdown.className = "box ai-calls-current-group";
    sessionBreakdown.innerHTML = `
      <div class="ai-calls-current-group-head">
        <div>
          <h3>Token breakdown by session</h3>
          <div class="muted xsmall">Cached input / New input / Reasoning / Output.</div>
        </div>
      </div>
      ${renderTokenBreakdown(sessionCategories, sessionCostBasis)}`;
    root.appendChild(sessionBreakdown);

    renderCurrentGrouped(root, session);
  }

  function renderDetailHeader() {
    if (isLegacyTab()) {
      applyDetailLayout();
      legacyRenderHeader();
      return;
    }
    renderCurrentHeader();
  }

  function renderDetailSteps() {
    if (isLegacyTab()) {
      applyDetailLayout();
      legacyRenderSteps();
      return;
    }
    renderCurrentSteps();
  }

  function renderDetailSelection() {
    applyDetailLayout();
    if (isLegacyTab()) legacyRenderSelection();
  }

  function renderDetailAuditPanel() {
    applyDetailLayout();
    if (isLegacyTab()) {
      legacyRenderAuditPanel();
      return;
    }
    const panel = document.getElementById("auditPanel");
    if (panel) panel.innerHTML = "";
  }

  globalThis.setDetailTab = function setDetailTab(nextTab) {
    const normalized = nextTab === "legacy" ? "legacy" : "current";
    if (normalized === detailTab) {
      renderDetailTabs();
      return;
    }
    detailTab = normalized;
    renderDetailHeader();
    renderDetailSteps();
    renderDetailSelection();
    renderDetailAuditPanel();
  };

  globalThis.openCallTextPopup = function openCallTextPopup(stepIndex, kind) {
    const step = (sessionDetailCache?.steps || []).find(s => Number(s.step_index) === Number(stepIndex));
    if (!step) { showToast("Step not found"); return; }
    const block = kind === "answer" ? step.assistant_answer : step.user_prompt;
    if (!block || block.available !== true) { showToast("Текст недоступен"); return; }
    const title = kind === "answer" ? "Assistant answer"
      : (step.user_prompt?.kind === 'system_composed' ? "System prompt (composed)" : "User prompt");
    const text = String(block.text || "");
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center";
    overlay.addEventListener("click", function(e) { if (e.target === this) this.remove(); });
    const dialog = document.createElement("div");
    dialog.style.cssText = "background:#1e1e1e;color:#d4d4d4;border-radius:8px;width:80vw;max-width:900px;max-height:85vh;padding:16px;box-shadow:0 4px 24px rgba(0,0,0,0.6);display:flex;flex-direction:column";
    const head = document.createElement("div");
    head.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px";
    head.innerHTML = `<div><b>${escapeHtml(title)}</b> <span class="muted xsmall">— Step ${escapeHtml(stepIndex)}</span></div>`;
    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:6px";
    const copyBtn = document.createElement("button");
    copyBtn.className = "ghost";
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", function(e) { e.stopPropagation(); copyText(text); });
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.style.cssText = "font-size:18px;border:none;background:none;cursor:pointer";
    closeBtn.addEventListener("click", function() { overlay.remove(); });
    actions.appendChild(copyBtn);
    actions.appendChild(closeBtn);
    head.appendChild(actions);
    const body = document.createElement("div");
    body.style.cssText = "overflow:auto;max-height:calc(85vh - 60px);font-size:12px;line-height:1.42;white-space:pre-wrap;color:var(--soft)";
    body.textContent = text;
    dialog.appendChild(head);
    dialog.appendChild(body);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
  };

  // Replace only the detail renderer entry points used by renderAll() and filters.
  // Legacy implementations remain callable through the captured references above.
  renderHeader = renderDetailHeader;
  renderSteps = renderDetailSteps;
  renderSelection = renderDetailSelection;
  renderAuditPanel = renderDetailAuditPanel;

  applyDetailLayout();
}());
