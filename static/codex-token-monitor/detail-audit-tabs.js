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
      updateCurrentAuditExportButton(null);
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
    updateCurrentAuditExportButton(session);
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

  function formatTruthfulStateLabel(state, prefix) {
    const safeState = state === "raw_backed" || state === "inferred" ? state : "unavailable";
    const text = safeState === "raw_backed"
      ? "Подтверждено raw"
      : safeState === "inferred"
        ? "Выведено из команды"
        : "Не удалось связать";
    return `<span class="truth-state truth-state-${safeState}">${escapeHtml(prefix ? `${prefix}: ${text}` : text)}</span>`;
  }

  function getTruthfulLinkState(item) {
    const state = item?.linked_call_linkage?.state;
    return state === "raw_backed" || state === "inferred" || state === "unavailable"
      ? state
      : "unavailable";
  }

  function getTruthfulEvidenceState(item) {
    if (Array.isArray(item?.raw_evidence) && item.raw_evidence.length > 0) return "raw_backed";
    if (item?.tool_evidence?.available === true) return "raw_backed";
    const confidence = String(item?.recognition_confidence || item?.confidence || "").toLowerCase();
    if (confidence === "high" || confidence === "medium" || confidence === "low") return "inferred";
    return "unavailable";
  }

  function getTruthfulCallState(call) {
    const confidence = String(call?.mapping_confidence || "").toLowerCase();
    if (confidence === "high") return "raw_backed";
    if (confidence === "medium" || confidence === "low" || confidence === "fallback_logs_only") return "inferred";
    return "unavailable";
  }

  function getTruthfulCallCost(call) {
    return Number(call?.estimated_cost?.estimated_total_cost_usd || 0);
  }

  function renderTruthfulCallUsage(call) {
    const usage = call?.usage || {};
    return `
      <div class="truth-call-usage" aria-label="Usage and cost for model call">
        <span><b>Input</b> ${nf.format(Number(usage.input_tokens || 0))}</span>
        <span><b>Cached</b> ${nf.format(Number(usage.cached_tokens || 0))}</span>
        <span><b>New input</b> ${nf.format(Number(usage.non_cached_input_tokens || 0))}</span>
        <span><b>Reasoning</b> ${nf.format(Number(usage.reasoning_tokens || 0))}</span>
        <span><b>Output</b> ${nf.format(Number(usage.output_tokens || 0))}</span>
        <span><b>Cost</b> ${formatAiCallMoney(getTruthfulCallCost(call))}</span>
      </div>`;
  }

  function renderTruthfulAction(item) {
    const evidenceState = getTruthfulEvidenceState(item);
    const linkState = getTruthfulLinkState(item);
    const title = item?.display_title_ru || item?.recognized_action_ru || item?.action_type || "Action";
    const object = item?.object_label || item?.path || item?.command || "";
    const notes = Array.isArray(item?.notes_ru) ? item.notes_ru.filter(Boolean) : [];
    return `
      <article class="truth-action">
        <div class="truth-action-head">
          <div>
            <b>${escapeHtml(title)}</b>
            ${object ? `<div class="truth-object mono">${escapeHtml(object)}</div>` : ""}
          </div>
          <div class="truth-badges">
            ${formatTruthfulStateLabel(evidenceState, 'доказательство')}
            ${formatTruthfulStateLabel(linkState, 'связь с вызовом')}
          </div>
        </div>
        <div class="truth-action-meta">
          raw event ${nf.format(Number(item?.event_index || 0))} · ${escapeHtml(item?.row_type || item?.action_type || 'action')}
        </div>
        ${notes.length ? `<div class="truth-note">${notes.map(escapeHtml).join(" ")}</div>` : ""}
        <div class="truth-cost-rule">Tokens and cost remain on the linked model call and are not assigned to this action.</div>
      </article>`;
  }

  function getTruthfulLinkedItems(step, call) {
    const items = step?.agent_activity?.agent_timeline?.items;
    const callIndex = Number(call?.call_index || 0);
    if (!Array.isArray(items) || callIndex <= 0) return [];
    return items.filter(item => Number(item?.linked_call_index || 0) === callIndex);
  }

  function getTruthfulUnlinkedItems(step) {
    const items = step?.agent_activity?.agent_timeline?.items;
    if (!Array.isArray(items)) return [];
    return items.filter(item => !Number(item?.linked_call_index || 0));
  }

  function renderTruthfulCall(step, call) {
    const linkedItems = step ? getTruthfulLinkedItems(step, call) : [];
    const callState = getTruthfulCallState(call);
    const timestamp = call?.timestamp ? new Date(call.timestamp).toLocaleTimeString("ru-RU") : "—";
    return `
      <article class="truth-call">
        <div class="truth-call-head">
          <div>
            <h5>Вызов модели #${formatAiCallNumber(call?.call_index)}</h5>
            <div class="truth-call-meta">${escapeHtml(call?.model || "unknown")} · ${escapeHtml(timestamp)} · event ${nf.format(Number(call?.event_index || 0))}</div>
          </div>
          ${formatTruthfulStateLabel(callState, 'привязка к шагу')}
        </div>
        ${renderTruthfulCallUsage(call)}
        <div class="truth-reasoning-unavailable"><b>Текст reasoning:</b> недоступен в raw telemetry. Показываются только токены reasoning при наличии.</div>
        <div class="truth-actions-title">Связанные действия / доказательства</div>
        ${linkedItems.length
          ? `<div class="truth-actions">${linkedItems.map(renderTruthfulAction).join("")}</div>`
          : `<div class="truth-empty">Нет напрямую связанных действий с этим вызовом.</div>`}
      </article>`;
  }

  function findTruthfulPreviousCall(calls, eventIndex) {
    let found = null;
    for (const call of calls) {
      if (Number(call?.event_index || 0) < eventIndex) found = call;
      else break;
    }
    return found;
  }

  function findTruthfulNextCall(calls, eventIndex) {
    return calls.find(call => Number(call?.event_index || 0) > eventIndex) || null;
  }

  const TOOL_TYPE_LABELS = {
    "opencode": "OpenCode",
    "zworker": "zworker",
    "read": "чтение файла",
    "read_file": "чтение файла",
    "write": "запись файла",
    "write_file": "запись файла",
    "glob": "поиск файлов",
    "search": "поиск",
    "grep": "поиск в файлах",
    "bash": "терминал",
    "run": "запуск команды",
    "http": "HTTP-запрос",
    "fetch": "HTTP-запрос",
    "test": "проверка/тест",
    "check": "проверка/тест",
    "browser": "браузер",
    "click": "клик",
    "type": "ввод текста",
  };
  function getToolHumanType(toolName) {
    if (!toolName) return "";
    const lower = String(toolName).toLowerCase();
    for (const [key, label] of Object.entries(TOOL_TYPE_LABELS)) {
      if (lower.includes(key)) return label;
    }
    return "";
  }
  function renderToolNameWithType(tool) {
    const techName = tool?.tool_name || tool?.title_ru || tool?.classified_action || "Tool";
    const humanType = getToolHumanType(techName);
    if (humanType && techName.toLowerCase() !== humanType.toLowerCase()) {
      return `${escapeHtml(techName)} <span class="truth-tool-type">(${humanType})</span>`;
    }
    return escapeHtml(techName);
  }
  function tryDecodeMojibake(text) {
    if (!text || typeof text !== "string") return null;
    if (/[\u0080-\uFFFF]/.test(text)) {
      try { return decodeURIComponent(escape(text)); } catch { return null; }
    }
    return null;
  }
  function renderToolOutputPreview(tool) {
    const raw = tool?.output_preview;
    if (!raw) return "";
    const decoded = tryDecodeMojibake(raw);
    if (decoded && decoded !== raw) {
      return `<pre class="truth-tool-preview">${escapeHtml(decoded)} <span class="truth-preview-decoded">(декодировано из mojibake)</span></pre>\n<pre class="truth-tool-preview truth-raw-preview">${escapeHtml(raw)} <span class="truth-preview-raw">(raw)</span></pre>`;
    }
    return `<pre class="truth-tool-preview">${escapeHtml(raw)}</pre>`;
  }
  function renderTruthfulToolCall(tool, stepCalls, allCalls) {
    const eventIndex = Number(tool?.event_index || 0);
    const previousCall = findTruthfulPreviousCall(allCalls, eventIndex);
    const nextCall = findTruthfulNextCall(stepCalls, eventIndex);
    const title = tool?.title_ru || tool?.tool_name || tool?.classified_action || "Tool action";
    const hasCallId = !!(tool?.call_id);
    const linkNote = hasCallId
      ? "связано по call_id"
      : "выведено из raw-порядка";
    let callRelation = "";
    if (previousCall) {
      callRelation = ` после вызова #${formatAiCallNumber(previousCall.call_index)}`;
    } else if (nextCall) {
      callRelation = ` → ожидается вызов #${formatAiCallNumber(nextCall.call_index)}`;
    } else {
      callRelation = " (ожидает вызова модели)";
    }
    return `
      <article class="truth-tool-event truth-tool-call">
        <div class="truth-tool-head">
          <b>Вызов инструмента: ${renderToolNameWithType(tool)}</b>
          ${formatTruthfulStateLabel('raw_backed')}
        </div>
        <div class="truth-action-meta">
          raw event ${nf.format(eventIndex)} · ${linkNote}${callRelation}
        </div>
        ${tool?.command ? `<div class="truth-object mono">${escapeHtml(tool.command)}</div>` : ""}
        ${tool?.target_path ? `<div class="truth-object mono">${escapeHtml(tool.target_path)}</div>` : ""}
        ${tool?.output_found === false ? `<div class="truth-next-call">Результат инструмента недоступен в raw данных.</div>` : ""}
        <div class="truth-cost-rule">Стоимость и токены остаются на вызове модели.</div>
      </article>`;
  }

  function renderTruthfulToolResult(tool, stepCalls, eventIndex) {
    const nextCall = findTruthfulNextCall(stepCalls, eventIndex);
    const title = tool?.title_ru || tool?.tool_name || tool?.classified_action || "Tool action";
    const outputAvailable = tool?.output_found === true || tool?.kind === "tool_output";
    let availabilityText = "Результат недоступен в raw данных.";
    if (outputAvailable && nextCall) {
      availabilityText = `Результат был доступен до вызова #${formatAiCallNumber(nextCall.call_index)}. Модель не читала свой будущий результат.`;
    } else if (outputAvailable) {
      availabilityText = "Последующих вызовов модели не обнаружено.";
    }
    return `
      <article class="truth-tool-event truth-tool-result">
        <div class="truth-tool-head">
          <b>Результат инструмента: ${renderToolNameWithType(tool)}</b>
          ${formatTruthfulStateLabel(outputAvailable ? 'raw_backed' : 'unavailable')}
        </div>
        <div class="truth-action-meta">raw event ${nf.format(eventIndex)}</div>
        <div class="truth-next-call">${escapeHtml(availabilityText)}</div>
        ${renderToolOutputPreview(tool)}
        <div class="truth-cost-rule">Стоимость и токены не копируются на результат инструмента.</div>
      </article>`;
  }

  function buildTruthfulOrderedEntries(stepCalls, tools) {
    const entries = [];
    stepCalls.forEach(call => {
      entries.push({ kind: "model_call", eventIndex: Number(call?.event_index || 0), rank: 1, call });
    });
    tools.forEach(tool => {
      const eventIndex = Number(tool?.event_index || 0);
      if (tool?.kind === "tool_output") {
        entries.push({ kind: "tool_result", eventIndex, rank: 3, tool });
        return;
      }
      entries.push({ kind: "tool_call", eventIndex, rank: 2, tool });
      if (tool?.output_found === true && Number(tool?.output_event_index || 0) > 0) {
        entries.push({ kind: "tool_result", eventIndex: Number(tool.output_event_index), rank: 3, tool });
      }
    });
    entries.sort((a, b) => a.eventIndex - b.eventIndex || a.rank - b.rank);
    return entries;
  }

  function renderTruthfulOrderedEntry(entry, step, stepCalls, allCalls) {
    if (entry.kind === "model_call") return renderTruthfulCall(step, entry.call);
    if (entry.kind === "tool_result") return renderTruthfulToolResult(entry.tool, stepCalls, entry.eventIndex);
    return renderTruthfulToolCall(entry.tool, stepCalls, allCalls);
  }

  function renderTruthfulStep(step, stepCalls, allCalls) {
    const tools = Array.isArray(step?.live_tool_events) ? [...step.live_tool_events] : [];
    tools.sort((a, b) => Number(a?.event_index || 0) - Number(b?.event_index || 0));
    const orderedEntries = buildTruthfulOrderedEntries(stepCalls, tools);
    const unlinked = getTruthfulUnlinkedItems(step);
    const promptAvailable = step?.user_prompt?.available === true;
    const answerAvailable = step?.assistant_answer?.available === true;
    return `
      <section class="truth-step">
        <div class="truth-step-head">
          <div>
            <h4>Step ${escapeHtml(step?.step_index)}</h4>
            <div class="truth-step-meta">${escapeHtml(step?.timestamp ? new Date(step.timestamp).toLocaleTimeString("ru-RU") : "—")} · ${escapeHtml(step?.turn_id || "turn id недоступен")}</div>
          </div>
          <div class="truth-badges">
            ${formatTruthfulStateLabel(promptAvailable ? 'raw_backed' : 'unavailable', promptAvailable ? 'prompt доступен' : 'prompt недоступен')}
            ${formatTruthfulStateLabel(answerAvailable ? 'raw_backed' : 'unavailable', answerAvailable ? 'answer доступен' : 'answer недоступен')}
          </div>
        </div>
        <div class="truth-lane">
          <h5>Хронология вызовов модели и инструментов</h5>
          <div class="truth-lane-note">События упорядочены по raw event index. Результаты инструментов показаны отдельно и не привязываются к предшествующему вызову как "прочитанные".</div>
          ${orderedEntries.length
            ? `<div class="truth-sequence">${orderedEntries.map(entry => renderTruthfulOrderedEntry(entry, step, stepCalls, allCalls)).join("")}</div>`
            : `<div class="truth-empty">Нет данных о вызовах модели или tool-событиях для этого шага.</div>`}
        </div>
        ${unlinked.length ? `
          <div class="truth-lane">
            <h5>Несвязанные нормализованные действия</h5>
            <div class="truth-lane-note">Эти действия видны, но глобальный вызов модели для них не определён.</div>
            <div class="truth-actions">${unlinked.map(renderTruthfulAction).join("")}</div>
          </div>` : ""}
      </section>`;
  }

  function renderTruthfulSessionEvents(session) {
    const events = Array.isArray(session?.timeline_events) ? [...session.timeline_events] : [];
    if (!events.length) return '';
    events.sort((a, b) => String(a?.timestamp || '').localeCompare(String(b?.timestamp || '')));
    return `
      <section class="truth-session-events">
        <h4>События сессии</h4>
        ${events.map(event => `
          <div class="truth-session-event">
            ${formatTruthfulStateLabel('raw_backed')}
            <b>${escapeHtml(event?.label || event?.event_type || 'Событие сессии')}</b>
            <span>${escapeHtml(event?.timestamp ? new Date(event.timestamp).toLocaleTimeString("ru-RU") : '—')}</span>
            ${event?.after_step_index ? `<span>после Step ${escapeHtml(event.after_step_index)}</span>` : ''}
          </div>`).join('')}
      </section>`;
  }

  function appendTruthfulTimelineSection(root, session) {
    root.querySelector('#truthfulTimelineSection')?.remove();
    const steps = Array.isArray(session?.steps) ? [...session.steps] : [];
    if (!steps.length) return;
    steps.sort((a, b) => Number(a?.step_index || 0) - Number(b?.step_index || 0));

    const calls = Array.isArray(session?.ai_calls) ? [...session.ai_calls] : [];
    calls.sort((a, b) => Number(a?.event_index || 0) - Number(b?.event_index || 0) || Number(a?.call_index || 0) - Number(b?.call_index || 0));

    const callsByStep = new Map();
    const unmappedCalls = [];
    calls.forEach(call => {
      const stepIndex = Number(call?.step_index || 0);
      if (stepIndex > 0) {
        if (!callsByStep.has(stepIndex)) callsByStep.set(stepIndex, []);
        callsByStep.get(stepIndex).push(call);
      } else {
        unmappedCalls.push(call);
      }
    });

    const mapping = session?.truthful_timeline_mapping || {};
    const section = document.createElement('details');
    section.id = 'truthfulTimelineSection';
    section.className = 'box truthful-timeline';
    section.open = false;
    section.innerHTML = `
      <summary>
        <div>
          <b>Несвязанные вызовы модели</b>
          <span class="muted xsmall">Нет доказуемой связи с видимым шагом.</span>
        </div>
        <div class="truth-badges">
          ${formatTruthfulStateLabel('raw_backed', `${nf.format(Number(mapping.linked_raw_backed || 0))} подтверждено`)}
          ${formatTruthfulStateLabel('inferred', `${nf.format(Number(mapping.linked_inferred || 0))} выведено`)}
          ${formatTruthfulStateLabel('unavailable', `${nf.format(Number(mapping.link_unavailable || 0))} не связано`)}
        </div>
      </summary>
      <div class="truth-intro">
        Этот вид использует существующую raw телеметрию. Он не выдумывает текст reasoning, не разделяет стоимость вызова между действиями, и не предполагает что результат инструмента был прочитан предшествующим вызовом.
      </div>
      ${renderTruthfulSessionEvents(session)}
      <div class="truth-step-list">
        ${steps.map(step => renderTruthfulStep(step, callsByStep.get(Number(step?.step_index || 0)) || [], calls)).join('')}
      </div>
      ${unmappedCalls.length ? `
        <section class="truth-unmapped">
          <h4>Unmapped session model calls</h4>
          <div class="truth-lane-note">These calls remain visible without assigning them to a visible step.</div>
          ${unmappedCalls.map(call => renderTruthfulCall(null, call)).join('')}
        </section>` : ''}`;
    root.appendChild(section);
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
      updateCurrentAuditExportButton(null);
      return;
    }

    updateGroupedAiCallsExportButton(session);
    updateCurrentAuditExportButton(session);
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
    appendTruthfulTimelineSection(root, session);
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

  function updateCurrentAuditExportButton(session) {
    const button = document.getElementById("downloadCurrentAuditButton");
    if (button) button.disabled = !session;
  }

  function buildCurrentAuditMarkdown(session) {
    const source = currentSource();
    const sourceKind = session.source_kind === "live" ? "live" : "архив";
    const summary = session.ai_calls_honest_audit_summary || {};
    const calls = Array.isArray(session.ai_calls) ? session.ai_calls : [];
    const grouping = buildAiCallsGrouping(session);
    const lines = [];

    // Title & session info
    lines.push("# Текущий аудит: " + (session.title || session.id || "Сессия"));
    lines.push("");
    lines.push("## Сессия");
    lines.push("- **Источник:** " + (source ? source.name : "") + " [" + sourceKind + "]");
    lines.push("- **ID сессии:** " + (session.id || ""));
    lines.push("- **Дата:** " + (session.date || ""));
    lines.push("- **Рабочая папка:** " + (session.workdir || ""));
    lines.push("- **Модель:** " + (session.model || ""));
    lines.push("- **Reasoning:** " + (session.reasoning || ""));
    lines.push("");

    // AI calls overview
    const cas = summary;
    const totalCalls = cas.ai_calls_total ?? calls.length;
    const withUsage = cas.ai_calls_with_usage ?? calls.filter(function(c) { return c?.is_zero_usage !== true; }).length;
    const zeroUsage = cas.ai_calls_zero_usage ?? calls.filter(function(c) { return c?.is_zero_usage === true; }).length;
    const mapped = cas.ai_calls_mapped_to_visible_steps ?? (calls.length - grouping.unmapped.length);
    const unmappedCount = cas.ai_calls_unmapped ?? grouping.unmapped.length;
    const totalCost = aiCallFiniteNumber(cas.ai_calls_total_cost_usd);

    lines.push("## AI Calls — сводка");
    lines.push("- **Всего AI calls:** " + formatAiCallNumber(totalCalls));
    lines.push("- **С usage:** " + formatAiCallNumber(withUsage));
    lines.push("- **Zero usage:** " + formatAiCallNumber(zeroUsage));
    lines.push("- **Mapped:** " + formatAiCallNumber(mapped));
    lines.push("- **Unmapped:** " + formatAiCallNumber(unmappedCount));
    lines.push("- **Input:** " + formatAiCallNumber(cas.ai_calls_total_input_tokens));
    lines.push("- **Output:** " + formatAiCallNumber(cas.ai_calls_total_output_tokens));
    lines.push("- **Cost:** " + formatAiCallMoney(totalCost));
    lines.push("");

    // Token breakdown by session
    const sessionSummary = aggregateAiCalls(calls, session);
    const sessionCategories = computeTokenBreakdown(sessionSummary);
    const sessionCostBasis = sessionSummary.session_total_cost_usd || sessionSummary.estimated_cost.estimated_total_cost_usd || 0;
    lines.push("## Token breakdown by session");
    lines.push("| Category | Tokens | Cost USD | % |");
    lines.push("|---:|---:|---:|---:|");
    sessionCategories.forEach(function(cat) {
      var pct = sessionCostBasis > 0 ? (cat.cost / sessionCostBasis * 100) : 0;
      lines.push("| " + cat.label + " | " + nf.format(cat.tokens) + " | $" + cat.cost.toFixed(5) + " | " + pct.toFixed(1) + "% |");
    });
    lines.push("");

    // Grouped AI calls by step
    var steps = Array.isArray(session.steps) ? session.steps.slice().sort(function(a, b) {
      return Number(a.step_index || 0) - Number(b.step_index || 0);
    }) : [];
    lines.push("## Группировка AI calls по шагам");
    lines.push("");

    var byStep = grouping.byStep;
    steps.forEach(function(step) {
      var stepIndex = Number(step.step_index || 0);
      var stepCalls = byStep.get(stepIndex) || [];
      var stepSummary = aggregateAiCalls(stepCalls, session);
      lines.push("### Step " + stepIndex);
      lines.push("- **AI calls:** " + stepSummary.ai_calls_count + " (with usage: " + stepSummary.ai_calls_with_usage_count + ", zero: " + stepSummary.ai_calls_zero_usage_count + ")");
      lines.push("- **Input:** " + formatAiCallNumber(stepSummary.usage.input_tokens));
      lines.push("- **Cached:** " + formatAiCallNumber(stepSummary.usage.cached_tokens));
      lines.push("- **Non-cached:** " + formatAiCallNumber(stepSummary.usage.non_cached_input_tokens));
      lines.push("- **Output:** " + formatAiCallNumber(stepSummary.usage.output_tokens));
      lines.push("- **Reasoning:** " + formatAiCallNumber(stepSummary.usage.reasoning_tokens));
      lines.push("- **Cost:** " + formatAiCallMoney(stepSummary.estimated_cost.estimated_total_cost_usd));
      lines.push("- **% от сессии:** " + formatAiCallPercent(stepSummary.percent_of_session_total));
      lines.push("");

      if (stepCalls.length) {
        lines.push("#### Вызовы");
        lines.push("| # | Time | Model | Input | Cached | Non-cached | Output | Reasoning | Cost |");
        lines.push("|---:|---|---:|---:|---:|---:|---:|---:|---:|");
        stepCalls.forEach(function(call) {
          var ts = call?.timestamp ? new Date(call.timestamp).toLocaleTimeString("ru-RU") : "—";
          var usage = call?.usage || {};
          lines.push("| " + formatAiCallNumber(call?.call_index) + " | " + ts + " | " + (call?.model || "unknown") + " | " + formatAiCallNumber(usage.input_tokens) + " | " + formatAiCallNumber(usage.cached_tokens) + " | " + formatAiCallNumber(aiCallUsageField(call, "non_cached_input_tokens")) + " | " + formatAiCallNumber(usage.output_tokens) + " | " + formatAiCallNumber(usage.reasoning_tokens) + " | " + formatAiCallMoney(aiCallCostField(call, "estimated_total_cost_usd")) + " |");
        });
        lines.push("");
      }
    });

    // Unmapped
    var unmapped = grouping.unmapped || [];
    if (unmapped.length) {
      var unmappedSummary = aggregateAiCalls(unmapped, session);
      lines.push("### Unmapped AI calls");
      lines.push("- **Calls:** " + unmappedSummary.ai_calls_count);
      lines.push("- **Cost:** " + formatAiCallMoney(unmappedSummary.estimated_cost.estimated_total_cost_usd));
      lines.push("- **% от сессии:** " + formatAiCallPercent(unmappedSummary.percent_of_session_total));
      lines.push("");

      lines.push("| # | Time | Model | Input | Cached | Non-cached | Output | Reasoning | Cost |");
      lines.push("|---:|---|---:|---:|---:|---:|---:|---:|---:|");
      unmapped.forEach(function(call) {
        var ts = call?.timestamp ? new Date(call.timestamp).toLocaleTimeString("ru-RU") : "—";
        var usage = call?.usage || {};
        lines.push("| " + formatAiCallNumber(call?.call_index) + " | " + ts + " | " + (call?.model || "unknown") + " | " + formatAiCallNumber(usage.input_tokens) + " | " + formatAiCallNumber(usage.cached_tokens) + " | " + formatAiCallNumber(aiCallUsageField(call, "non_cached_input_tokens")) + " | " + formatAiCallNumber(usage.output_tokens) + " | " + formatAiCallNumber(usage.reasoning_tokens) + " | " + formatAiCallMoney(aiCallCostField(call, "estimated_total_cost_usd")) + " |");
      });
      lines.push("");
    }

    // Truthful timeline (compact)
    if (steps.length) {
      lines.push("## Truthful Timeline");
      lines.push("");

      var allCalls = calls.slice().sort(function(a, b) {
        return (Number(a.event_index || 0) - Number(b.event_index || 0)) || (Number(a.call_index || 0) - Number(b.call_index || 0));
      });

      steps.forEach(function(step) {
        var stIdx = Number(step.step_index || 0);
        var stepCalls = byStep.get(stIdx) || [];
        var tools = Array.isArray(step?.live_tool_events) ? step.live_tool_events.slice().sort(function(a, b) {
          return Number(a.event_index || 0) - Number(b.event_index || 0);
        }) : [];

        lines.push("### Step " + stIdx);
        lines.push("- **Timestamp:** " + (step.timestamp ? new Date(step.timestamp).toLocaleTimeString("ru-RU") : "—"));
        lines.push("");

        // Build ordered entries
        var entries = [];
        stepCalls.forEach(function(call) {
          entries.push({ kind: "model_call", eventIndex: Number(call.event_index || 0), call: call });
        });
        tools.forEach(function(tool) {
          entries.push({ kind: "tool_event", eventIndex: Number(tool.event_index || 0), tool: tool });
        });
        entries.sort(function(a, b) { return a.eventIndex - b.eventIndex; });

        entries.forEach(function(entry) {
          if (entry.kind === "model_call") {
            var c = entry.call;
            lines.push("- **Вызов модели #" + (c?.call_index || "?") + ":** " + (c?.model || "unknown") + " · " + (c?.timestamp ? new Date(c.timestamp).toLocaleTimeString("ru-RU") : "—") + " · Cost: " + formatAiCallMoney(aiCallCostField(c, "estimated_total_cost_usd")));
          } else {
            var t = entry.tool;
            var toolTitle = t?.title_ru || t?.tool_name || t?.classified_action || "Tool";
            lines.push("- **Инструмент:** " + toolTitle);
            if (t?.command) lines.push("  - Команда: `" + t.command + "`");
            if (t?.target_path) lines.push("  - Путь: `" + t.target_path + "`");
          }
        });
        lines.push("");
      });

      // Session events
      var timelineEvents = Array.isArray(session?.timeline_events) ? session.timeline_events : [];
      if (timelineEvents.length) {
        lines.push("### События сессии");
        timelineEvents.forEach(function(evt) {
          lines.push("- " + (evt.label || evt.event_type || "Событие") + " · " + (evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString("ru-RU") : "—") + (evt.after_step_index ? " (после Step " + evt.after_step_index + ")" : ""));
        });
        lines.push("");
      }
    }

    return lines.join("\n");
  }

  globalThis.downloadCurrentAuditMarkdown = function downloadCurrentAuditMarkdown() {
    const session = sessionDetailCache;
    if (!session) {
      showToast("Сначала выберите сессию");
      return;
    }
    const markdown = buildCurrentAuditMarkdown(session);
    const safeId = (session.id || "session").replace(/[^a-zA-Z0-9_-]/g, "_");
    const filename = "current-audit-" + safeId + ".md";
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("Скачан " + filename);
  };

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
})();