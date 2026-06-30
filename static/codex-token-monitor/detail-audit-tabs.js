"use strict";

// Top-level detail state. The AI Calls mode remains a separate state owned by app.js.
let detailTab = "current";

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
  }

  function appendMappedGroup(root, session, stepIndex, calls) {
    const summary = aggregateAiCalls(calls, session);
    const card = document.createElement("section");
    card.className = "box ai-calls-current-group";
    card.dataset.stepIndex = String(stepIndex);
    card.innerHTML = `
      <div class="ai-calls-current-group-head">
        <div>
          <h3>Запрос / Step ${escapeHtml(stepIndex)}</h3>
          <div class="muted xsmall">Call-level группа по step_index. Legacy step card и prompt/answer здесь не строятся.</div>
        </div>
        <span class="pill blue">${formatAiCallNumber(summary.ai_calls_count)} AI calls</span>
      </div>
      ${renderAiCallsGroupSummary(summary)}
      <div class="ai-call-group-detail ai-calls-current-table">
        ${renderAiCallTable(calls, session, false)}
      </div>`;
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

    if (aiCallsViewMode === "flat") {
      renderFlatAiCallsAudit(root, session, overview);
      return;
    }

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

  // Replace only the detail renderer entry points used by renderAll() and filters.
  // Legacy implementations remain callable through the captured references above.
  renderHeader = renderDetailHeader;
  renderSteps = renderDetailSteps;
  renderSelection = renderDetailSelection;
  renderAuditPanel = renderDetailAuditPanel;

  applyDetailLayout();
}());
