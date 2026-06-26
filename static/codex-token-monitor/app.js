"use strict";

// ── State ──
let currentSourceId = "";
let currentSessionId = "";
let selected = new Set();
let autoRefresh = true;
let stopped = false;
let showArchived = false;
let refreshTimer = null;
let refreshPromise = null;
const MIN_VISIBLE_SESSION_DATE_MS = Date.parse("2026-06-04T00:00:00Z");
const ALL_WORKDIRS_VALUE = "";

// ── Data caches ──
let sourcesCache = [];
let sessionsCache = [];
let sessionDetailCache = null;
let sessionDetailLoading = false;
let statusCache = { collector: "unknown", prompt_logging: true, last_update: "" };
let currentWorkdirFilter = ALL_WORKDIRS_VALUE;
// Track expanded step details across re-renders (auto-refresh)
let expandedSteps = new Set();
let openTextBlocks = new Set();

// ── Formatters ──
const nf = new Intl.NumberFormat("ru-RU");
const money = n => "$" + Number(n || 0).toFixed(5);
const moneyOrNA = n => (n != null) ? "$" + Number(n).toFixed(5) : "—";
const pct = n => (Number(n || 0) * 100).toFixed(1) + "%";
const numOrNA = n => (n != null && n !== 0) ? nf.format(n) : (n === 0 ? "0" : "—");
const numWithSign = n => (n != null) ? ((n >= 0 ? "+" : "") + nf.format(n)) : "—";

// ── API helpers ──
async function api(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return res.json();
  } catch (e) {
    return null;
  }
}

async function apiPost(path, body) {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      // Try to read error body for debugging
      try {
        const err = await res.json();
        return { error: err.error || ("HTTP " + res.status), _http_status: res.status };
      } catch (_) {
        return { error: "HTTP " + res.status, _http_status: res.status };
      }
    }
    return res.json();
  } catch (e) {
    return null;
  }
}

// ── Data loading ──
async function loadSources() {
  const data = await api("/api/sources");
  if (data && data.sources) {
    sourcesCache = data.sources;
    if (!currentSourceId && data.default_source_id) {
      currentSourceId = data.default_source_id;
    }
    if (!currentSourceId && sourcesCache.length > 0) {
      currentSourceId = sourcesCache[0].id;
    }
  }
  if (sourcesCache.length > 0 && !currentSourceId) {
    currentSourceId = sourcesCache[0].id;
  }
}

function currentSource() {
  return sourcesCache.find(s => s.id === currentSourceId) || sourcesCache[0] || null;
}

function normalizeWorkdir(raw) {
  let text = String(raw || "").trim();
  if (!text) return "";
  if (text.startsWith("\\\\?\\")) text = text.slice(4);
  return text.replaceAll("/", "\\");
}

function projectLabelFromWorkdir(raw) {
  const workdir = normalizeWorkdir(raw);
  if (!workdir) return "Без папки";
  const parts = workdir.split("\\").filter(Boolean);
  return parts[parts.length - 1] || workdir;
}

function sessionTimestampMs(session) {
  const raw = session?.date;
  if (typeof raw === "number") return raw > 1_000_000_000_000 ? raw : raw * 1000;
  const num = Number(raw);
  if (Number.isFinite(num) && raw !== "" && raw != null) {
    return num > 1_000_000_000_000 ? num : num * 1000;
  }
  const parsed = Date.parse(String(raw || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatSessionDate(session) {
  const ts = sessionTimestampMs(session);
  if (!ts) return "дата неизвестна";
  return new Date(ts).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function workdirChoices() {
  const seen = new Map();
  sessionsCache.forEach(session => {
    const value = normalizeWorkdir(session.workdir);
    if (!value || seen.has(value)) return;
    seen.set(value, {
      value,
      label: projectLabelFromWorkdir(value),
    });
  });
  return [...seen.values()].sort((a, b) => a.label.localeCompare(b.label, "ru"));
}

function preferredSessionId(list) {
  const sessions = list || [];
  const withSteps = sessions.find(s => Number(s.step_count || 0) > 0);
  return (withSteps || sessions[0] || {}).id || "";
}

async function loadSessions() {
  if (!currentSourceId) { sessionsCache = []; return; }
  const data = await api("/api/sessions?source_id=" + encodeURIComponent(currentSourceId) +
    "&show_archived=" + (showArchived ? "1" : "0"));
  if (data && data.sessions) {
    sessionsCache = data.sessions;
  } else {
    sessionsCache = [];
  }
  if (sessionsCache.length > 0 && !currentSessionId) {
    currentSessionId = preferredSessionId(sessionsCache);
  }
  if (!sessionsCache.find(s => s.id === currentSessionId)) {
    currentSessionId = preferredSessionId(sessionsCache);
  }
}

async function loadSessionDetail() {
  if (!currentSourceId || !currentSessionId) {
    sessionDetailCache = null;
    sessionDetailLoading = false;
    return;
  }
  sessionDetailLoading = true;
  const data = await api("/api/session?source_id=" + encodeURIComponent(currentSourceId) +
    "&session_id=" + encodeURIComponent(currentSessionId));
  sessionDetailCache = data;
  sessionDetailLoading = false;
}

async function loadStatus() {
  const data = await api("/api/status");
  if (data) {
    statusCache.collector = data.collector || "unknown";
    statusCache.prompt_logging = data.prompt_logging !== false;
    statusCache.last_update = data.last_update || "";
  }
}

async function refreshAll() {
  if (refreshPromise) {
    return refreshPromise;
  }
  refreshPromise = (async () => {
    await loadSources();
    initSources();
    await loadSessions();
    if (!sessionDetailCache) {
      const preferredId = preferredSessionId(sessionsCache);
      if (preferredId) currentSessionId = preferredId;
    }
    await loadStatus();
    populateWorkdirFilter();
    populateModelFilter();
    if (!sessionDetailCache || sessionDetailCache.id !== currentSessionId) {
      sessionDetailCache = null;
    }
    renderAll();
    await loadSessionDetail();
    renderAll();
  })();
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function refreshData() {
  await apiPost("/api/refresh", { source_id: currentSourceId, session_id: currentSessionId });
  document.getElementById("lastUpdate").textContent = new Date().toLocaleTimeString("ru-RU");
  showToast("Данные обновлены");
  await refreshAll();
}

// ── Archive ──
async function toggleArchive(sessionId) {
  const detail = await api("/api/session?source_id=" + encodeURIComponent(currentSourceId) +
    "&session_id=" + encodeURIComponent(sessionId));
  const isArchivedNow = detail && detail.archived;
  await apiPost(isArchivedNow ? "/api/unarchive" : "/api/archive", {
    source_id: currentSourceId,
    session_id: sessionId,
  });
  await loadSessions();
  renderAll();
}

function toggleArchivedVisibility() {
  showArchived = !showArchived;
  localStorage.setItem("ctm_show_archived", showArchived ? "1" : "0");
  refreshAll();
}

// ── Shutdown ──
function openShutdown() { document.getElementById("shutdownModal").style.display = "flex"; }
function closeShutdown() { document.getElementById("shutdownModal").style.display = "none"; }
async function confirmShutdown() {
  stopped = true;
  autoRefresh = false;
  if (refreshTimer) clearInterval(refreshTimer);
  closeShutdown();
  await apiPost("/api/shutdown", {});
  renderStatus();
  showToast("Монитор остановлен");
}

// ── Session helpers ──
function filteredSessions() {
  const q = (document.getElementById("q")?.value || "").toLowerCase();
  const mf = (document.getElementById("modelFilter")?.value || "");
  const rf = (document.getElementById("riskFilter")?.value || "");
  const sortMode = (document.getElementById("sortFilter")?.value || "date_desc");
  const workdirFilter = normalizeWorkdir(document.getElementById("workdirFilter")?.value || currentWorkdirFilter || "");
  const list = sessionsCache.filter(s => {
    const ts = sessionTimestampMs(s);
    if (ts && ts < MIN_VISIBLE_SESSION_DATE_MS) return false;
    const sessionWorkdir = normalizeWorkdir(s.workdir);
    const txt = (s.title + " " + s.id + " " + s.model + " " + s.reasoning + " " + s.workdir).toLowerCase();
    const hasWarn = s.warnings_count > 0;
    return txt.includes(q) &&
      (!workdirFilter || sessionWorkdir === workdirFilter) &&
      (!mf || s.model === mf) &&
      (!rf || (rf === "warnings" ? hasWarn : !hasWarn));
  });
  list.sort((a, b) => {
    const aDate = sessionTimestampMs(a);
    const bDate = sessionTimestampMs(b);
    const aCost = Number(a.total_cost_usd || 0);
    const bCost = Number(b.total_cost_usd || 0);
    switch (sortMode) {
      case "date_asc":
        return aDate - bDate;
      case "cost_desc":
        return bCost - aCost || bDate - aDate;
      case "cost_asc":
        return aCost - bCost || bDate - aDate;
      case "date_desc":
      default:
        return bDate - aDate;
    }
  });
  return list;
}

function currentSession() {
  return filteredSessions().find(s => s.id === currentSessionId) || filteredSessions()[0] || null;
}

function totals(steps) {
  return steps.reduce((a, t) => {
    // Only sum per-step usage when available (not ambiguous/cumulative)
    const u = t.usage || {};
    if (u.available !== false) {
      a.input += u.input_tokens || 0;
      a.cached += u.cached_tokens || 0;
      a.non += u.non_cached_input_tokens || 0;
      a.output += u.output_tokens || 0;
      a.reasoning += u.reasoning_tokens || 0;
      a.tool += u.tool_tokens || 0;
      a.cost += u.estimated_total_cost_usd || 0;
    }
    a.warnings += (t.warnings || []).length;
    return a;
  }, { input: 0, cached: 0, non: 0, output: 0, reasoning: 0, tool: 0, cost: 0, warnings: 0 });
}

function metricsForSession(session) {
  const summary = session?.summary || null;
  if (summary && (
    summary.total_input_tokens ||
    summary.total_cached_tokens ||
    summary.total_output_tokens ||
    summary.estimated_total_cost_usd
  )) {
    return {
      input: summary.total_input_tokens || 0,
      cached: summary.total_cached_tokens || 0,
      non: summary.total_non_cached_input_tokens || 0,
      output: summary.total_output_tokens || 0,
      reasoning: summary.total_reasoning_tokens || 0,
      tool: summary.total_tool_tokens || 0,
      cost: summary.estimated_total_cost_usd || 0,
      warnings: (summary.warnings || []).length,
      ratio: summary.average_cached_ratio || 0,
      turnCount: summary.turn_count || 0,
    };
  }
  const z = totals(session?.steps || []);
  return {
    ...z,
    ratio: z.input ? z.cached / z.input : 0,
    turnCount: (session?.steps || []).length,
  };
}

// ── Render: left panel ──
function initSources() {
  const sel = document.getElementById("sourceSelect");
  if (!sel) return;
  sel.innerHTML = sourcesCache.map(s =>
    `<option value="${s.id}">${s.name} (${s.kind === 'live' ? 'live' : 'архив'})</option>`
  ).join("");
  sel.value = currentSourceId;
}

function renderSourceInfo() {
  const s = currentSource();
  const selectedPath = currentWorkdirFilter || "";
  const fallback = s ? (s.kind === "live" ? "C:/Users/andre/.codex" : "D:/Codex+Kilocode/projects/sword-of-rome-web/_local/codex-token-debugger") : "";
  document.getElementById("sourcePath").textContent = selectedPath || fallback;
}

function populateWorkdirFilter() {
  const sel = document.getElementById("workdirFilter");
  if (!sel) return;
  const previousValue = currentWorkdirFilter || sel.value || ALL_WORKDIRS_VALUE;
  const choices = workdirChoices();
  sel.innerHTML = `<option value="${ALL_WORKDIRS_VALUE}">Все проекты / папки</option>`;
  choices.forEach(choice => {
    sel.innerHTML += `<option value="${escapeHtml(choice.value)}">${escapeHtml(choice.label)}</option>`;
  });
  const valid = new Set([ALL_WORKDIRS_VALUE, ...choices.map(choice => choice.value)]);
  currentWorkdirFilter = valid.has(previousValue) ? previousValue : ALL_WORKDIRS_VALUE;
  sel.value = currentWorkdirFilter;
}

function renderSessions() {
  const list = filteredSessions();
  const root = document.getElementById("sessions");
  document.getElementById("sessionCount").textContent = `${list.length}/${sessionsCache.length}`;
  document.getElementById("archivedToggleBtn").style.borderColor = showArchived ? "rgba(124,156,255,.75)" : "";
  root.innerHTML = "";

  if (!list.length) {
    root.innerHTML = `<div class="empty small">Нет подходящих сессий</div>`;
    return;
  }

  if (!list.find(s => s.id === currentSessionId)) currentSessionId = preferredSessionId(list);

  list.forEach(s => {
    const costText = s.total_cost_usd == null ? "—" : money(s.total_cost_usd);
    const stepText = s.step_count == null ? "—" : nf.format(s.step_count);
    const el = document.createElement("div");
    const sourceKind = s.source_kind || "archive";
    const badgeCls = sourceKind === "live" ? "green" : "purple";
    const sourceLabel = sourceKind === "live" ? "live" : "архив";

    // Confirmation badges
    const cbadges = (s.confirmation_badges || []).map(b => `<span class="pill yellow">${b}</span>`).join("");

    el.className = "session" + (s.id === currentSessionId ? " active" : "");
    el.onclick = async () => {
      currentSessionId = s.id;
      selected.clear();
      expandedSteps.clear();
      openTextBlocks.clear();
      sessionDetailCache = null;
      sessionDetailLoading = true;
      renderAll();
      await loadSessionDetail();
      renderAll();
    };
    el.innerHTML = `
      <div class="session-head">
        <div>
          <div class="session-title">${escapeHtml(s.title)}</div>
          <div class="session-id muted xsmall mono">${escapeHtml(s.id)}</div>
          <div class="session-date">${escapeHtml(formatSessionDate(s))}</div>
        </div>
        <div class="row-actions">
          <button class="icon ghost" title="Архивировать/Вернуть" onclick="event.stopPropagation();toggleArchive('${s.id}')">🗄</button>
          <span class="pill blue">${stepText}</span>
        </div>
      </div>
      <div class="pills">
        <span class="pill ${badgeCls}">${sourceLabel}</span>
        <span class="pill">${escapeHtml(s.model)}</span>
        <span class="pill purple">${escapeHtml(s.reasoning)}</span>
        <span class="pill ${s.warnings_count ? 'yellow' : 'green'}">${s.warnings_count} warn</span>
        ${cbadges}
        ${s.has_normalized ? '<span class="pill green">normalized</span>' : (s.has_parsed ? '<span class="pill">parsed</span>' : '')}
      </div>
      <div class="compact-metrics">
        <div class="cmini"><span>Cost</span><b>${costText}</b></div>
        <div class="cmini"><span>Steps</span><b>${stepText}</b></div>
        <div class="cmini"><span>Model</span><b>${escapeHtml(s.model)}</b></div>
      </div>`;
    root.appendChild(el);
  });
}

// ── Render: header ──
function stat(label, value, cls) {
  return `<div class="stat ${cls || ""}"><label>${label}</label><b>${value}</b></div>`;
}

function usageNumber(usage, key) {
  if (!usage || usage.available === false) return "—";
  return nf.format(usage[key] || 0);
}

function usageMoney(usage, key) {
  if (!usage || usage.available === false) return "—";
  const value = usage[key];
  return value == null ? "—" : money(value);
}

function usagePercent(usage, key) {
  if (!usage || usage.available === false) return "—";
  return pct(usage[key] || 0);
}

function renderHeader() {
  const s = sessionDetailCache;
  if (!s) {
    document.getElementById("title").textContent = "Выберите сессию";
    const selectedSession = currentSession();
    document.getElementById("title").textContent = selectedSession ? "Загрузка сессии..." : document.getElementById("title").textContent;
    document.getElementById("meta").textContent = selectedSession ? selectedSession.title : "";
    document.getElementById("stats").innerHTML = "";
    return;
  }
  const z = metricsForSession(s);
  const src = currentSource();
  const sourceKind = s.source_kind || "archive";
  const kindLabel = sourceKind === "live" ? "live" : "архив";

  const hasAmbiguousLiveSteps = sourceKind === "live" && (s.steps || []).some(t => t?.usage?.available === false);
  const usageNote = hasAmbiguousLiveSteps ? " · часть шагов без точной per-step разбивки" : "";

  // v2.8: call-level audit stats as primary truth
  const cas = s.ai_calls_honest_audit_summary || {};
  const callAuditNote = cas.ai_calls_total
    ? ` · AI calls: ${cas.ai_calls_with_usage || 0} с usage / ${cas.ai_calls_zero_usage || 0} zero / ${cas.ai_calls_unmapped || 0} unmapped`
    : "";

  document.getElementById("title").textContent = s.title;
  document.getElementById("meta").textContent = `${src ? src.name : ""} [${kindLabel}] · ${s.id} · ${s.date} · ${s.workdir}${usageNote}${callAuditNote}`;
  document.getElementById("stats").innerHTML = [
    stat("Cost", money(z.cost), "good"),
    stat("Input", nf.format(z.input), "blue"),
    stat("Cached", nf.format(z.cached), "good"),
    stat("Non-cached", nf.format(z.non), "warn"),
    stat("Cache", pct(z.ratio), "blue"),
    stat("Output", nf.format(z.output)),
  ].join("");
}

// ── Render: steps ──
function metric(label, value) { return `<div class="metric"><span>${label}</span><b>${value}</b></div>`; }
function kv(k, v) { return `<div class="kv"><span class="muted">${k}</span><span class="mono">${String(v)}</span></div>`; }
function escapeHtml(t) { return String(t || "").replace(/[&<>\"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;" }[m])); }
function ellipsis(text, n) {
  text = String(text || "");
  return text.length > n ? text.slice(0, n - 1) + "\u2026" : text;
}
function textBlock(title, kind, available, text, stepIndex) {
  return `<div class="text-block" id="${kind}-${stepIndex}">
    <div class="text-head" onclick="toggleText('${kind}-${stepIndex}')">
      <div><b>${title}</b> <span class="muted xsmall">${available ? 'hidden by default' : 'not available'}</span></div>
      <button class="ghost" onclick="event.stopPropagation();toggleText('${kind}-${stepIndex}')">${available ? 'Показать' : '—'}</button>
    </div>
    <div class="text-body">${available ? escapeHtml(text) : "Текст отсутствует в telemetry/log source."}</div>
  </div>`;
}

function wideBlock(label, suffix, content, stepIdx) {
  const id = suffix + '-' + stepIdx;
  return `<div class="text-block" id="${id}">
    <div class="text-head" onclick="toggleText('${id}')">
      <div><b>${label}</b></div>
      <button class="ghost" onclick="event.stopPropagation();toggleText('${id}')">Показать</button>
    </div>
    <div class="text-body">${content}</div>
  </div>`;
}

function renderTimelineEvent(evt) {
  const ids = [];
  if (evt.compaction_task_id) ids.push(`task: ${escapeHtml(evt.compaction_task_id)}`);
  if (evt.after_step_turn_id) ids.push(`step turn: ${escapeHtml(evt.after_step_turn_id)}`);
  return `
    <div class="timeline-event">
      <div class="timeline-head">
        <span class="pill yellow">timeline</span>
        <b>${escapeHtml(evt.label || evt.event_type || "event")}</b>
        <span class="muted">${evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString("ru-RU") : ""}</span>
      </div>
      <div class="timeline-body">
        <span class="muted">После шага ${evt.after_step_index || "?"}</span>
        ${ids.length ? `<span class="mono">${ids.join(" · ")}</span>` : ""}
      </div>
    </div>`;
}

function renderSteps() {
  const root = document.getElementById("steps");
  root.innerHTML = "";
  const s = sessionDetailCache;
  if (!s || !s.steps || !s.steps.length) {
    root.innerHTML = `<div class="loading">${currentSession() ? "Загрузка шагов..." : "Нет данных по шагам"}</div>`;
    return;
  }

  // Source kind indicator
  const sourceKind = s.source_kind || "archive";
  const hasAmbiguousLiveSteps = sourceKind === "live" && s.steps.some(t => t?.usage?.available === false);
  const usageWarning = hasAmbiguousLiveSteps
    ? `<div class="empty small" style="margin-bottom:8px">⚠ Для части live-шагов точная per-step разбивка не подтверждена. В таких местах смотри totals всей сессии.</div>`
    : "";

  if (usageWarning) {
    const warnEl = document.createElement("div");
    warnEl.innerHTML = usageWarning;
    root.appendChild(warnEl);
  }

  // v2.8: Call-level audit — AI calls summary as primary truth above steps
  if (s.ai_calls && s.ai_calls.length > 0) {
    const cas = s.ai_calls_honest_audit_summary || {};
    const buckets = cas.ai_calls_usage_buckets_by_input || {};
    const isFallback = cas.degraded_from_fallback || false;
    const callsSection = document.createElement("div");
    callsSection.className = "ai-calls-section";
    callsSection.innerHTML = `
      <div class="box" style="margin-top:0">
        <h3>AI Calls — честный call-level аудит (primary truth)${isFallback ? ' <span style="color:#c09853;font-weight:400">[DEGRADED: fallback]</span>' : ''}</h3>
        <div class="muted xsmall" style="margin-bottom:6px">${isFallback
          ? '<span style="color:#c09853;font-weight:600">ДЕГРАДАЦИЯ: rollout JSONL не найден.</span> Call-level модель восстановлена из logs_2.sqlite (fallback). Per-request usage отсутствует, все вызовы помечены zero-usage. Данные о стоимости недоступны. Это <b>не</b> raw request-level truth.'
          : 'Каждый AI-вызов с live last_token_usage. Zero-usage посчитаны отдельно. Unmapped помечены явно.'}</div>
        ${isFallback ? '<div class="warning-banner" style="background:#3a2a00;border:1px solid #c09853;color:#c09853;padding:6px 10px;margin-bottom:8px;border-radius:4px;font-size:12px">Сессия без rollout: call-level данные деградированы и не отражают реальную per-request стоимость.</div>' : ''}
        <div class="metrics" style="margin-bottom:6px">
          ${metric("Всего AI calls", nf.format(cas.ai_calls_total || 0))}
          ${metric("С usage", nf.format(cas.ai_calls_with_usage || 0))}
          ${metric("Zero usage", nf.format(cas.ai_calls_zero_usage || 0))}
          ${metric(isFallback ? "Fallback" : "Unmapped", isFallback ? nf.format(cas.ai_calls_total || 0) : nf.format(cas.ai_calls_unmapped || 0))}
          ${metric("Input (calls)", nf.format(cas.ai_calls_total_input_tokens || 0))}
          ${metric("Output (calls)", nf.format(cas.ai_calls_total_output_tokens || 0))}
          ${metric("Cost (calls)", (cas.ai_calls_total_cost_usd != null) ? money(cas.ai_calls_total_cost_usd) : "—")}
        </div>
        ${(() => {
          let buckHtml = '<div class="muted xsmall" style="margin-top:4px">Buckets (по input_tokens):</div><div class="pills" style="flex-wrap:wrap">';
          Object.entries(buckets).forEach(([k, v]) => {
            const label = k.replace(/_/g, ' ');
            buckHtml += '<span class="pill">' + label + ': ' + v.count + '</span>';
          });
          buckHtml += '</div>';
          return buckHtml;
        })()}
        <button class="small" style="margin-top:6px" onclick="var el=document.getElementById('aiCallsTable');el.style.display=el.style.display==='none'?'block':'none'">Показать таблицу AI calls</button>
        <div id="aiCallsTable" style="display:none;max-height:400px;overflow:auto;margin-top:6px">
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <thead><tr style="background:#2a2a2a">
              <th style="text-align:right;padding:2px 4px">#</th>
              <th style="text-align:left;padding:2px 4px">Model</th>
              <th style="text-align:right;padding:2px 4px">Step</th>
              <th style="text-align:right;padding:2px 4px">Input</th>
              <th style="text-align:right;padding:2px 4px">Cached</th>
              <th style="text-align:right;padding:2px 4px">Output</th>
              <th style="text-align:right;padding:2px 4px">Reasoning</th>
              <th style="text-align:right;padding:2px 4px">Cost</th>
              <th style="text-align:center;padding:2px 4px">Zero?</th>
              <th style="text-align:center;padding:2px 4px">Map conf</th>
            </tr></thead><tbody>
            ${s.ai_calls.map(function(c) {
              const cost = c.estimated_cost || {};
              const usage = c.usage || {};
              const zeroMark = c.is_zero_usage ? '<span style="color:#c09853">zero</span>' : '<span style="color:#6a6">usage</span>';
              const mapColor = c.mapping_confidence === 'unmapped' ? '#c44' : (c.mapping_confidence === 'medium' ? '#cc4' : (c.mapping_confidence === 'fallback_logs_only' ? '#c09853' : '#4a4'));
              return '<tr style="' + (c.is_zero_usage ? 'opacity:0.5' : '') + '">' +
                '<td style="text-align:right;padding:1px 4px">' + c.call_index + '</td>' +
                '<td style="padding:1px 4px">' + escapeHtml(c.model) + '</td>' +
                '<td style="text-align:right;padding:1px 4px">' + (c.step_index || '—') + '</td>' +
                '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.input_tokens || 0) + '</td>' +
                '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.cached_tokens || 0) + '</td>' +
                '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.output_tokens || 0) + '</td>' +
                '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.reasoning_tokens || 0) + '</td>' +
                '<td style="text-align:right;padding:1px 4px;font-weight:600">' + (cost.estimated_total_cost_usd != null ? money(cost.estimated_total_cost_usd) : '—') + '</td>' +
                '<td style="text-align:center;padding:1px 4px">' + zeroMark + '</td>' +
                '<td style="text-align:center;padding:1px 4px;color:' + mapColor + '">' + escapeHtml(c.mapping_confidence) + '</td>' +
                '</tr>';
            }).join("")}
            </tbody></table>
          </div>
      </div>`;
    root.appendChild(callsSection);
  }

  // ── v2.9: honesty warnings — session-level ──
  var honestyWarnings = [];
  var summaryWarnings = (s.summary && s.summary.warnings) || [];
  summaryWarnings.forEach(function(w) {
    var msg = typeof w === 'string' ? w : (w && w.message) ? w.message : '';
    if (msg && (msg.indexOf('call-level') >= 0 || msg.indexOf('unmapped/internal') >= 0 ||
        msg.indexOf('unmapped') >= 0 || msg.indexOf('zero') >= 0)) {
      honestyWarnings.push(msg);
    }
  });
  // Count reported_by_agent items across all steps
  var totalReported = 0;
  (s.steps || []).forEach(function(step) {
    var items = (step.agent_activity && step.agent_activity.activity_items) || [];
    items.forEach(function(it) {
      if (it && it.status === 'reported_by_agent') totalReported++;
    });
  });
  if (honestyWarnings.length > 0 || totalReported > 0) {
    var hwEl = document.createElement('div');
    var hwLines = '<div class="box yellow-box" style="margin-bottom:8px;border-left:3px solid #c09853">';
    hwLines += '<h3 style="color:#c09853">⚠ Честные предупреждения (honesty warnings)</h3>';
    hwLines += '<div class="muted xsmall" style="margin-bottom:4px">Эти предупреждения основаны на строгих проверках имеющихся данных.</div>';
    honestyWarnings.forEach(function(w) {
      hwLines += '<div class="muted xsmall" style="margin-bottom:2px">• ' + escapeHtml(w) + '</div>';
    });
    if (totalReported > 0) {
      hwLines += '<div class="muted xsmall" style="margin-bottom:2px">• ' + totalReported + ' упоминаний файлов/команд только со слов агента (reported_by_agent, без подтверждения в raw tool events).</div>';
    }
    hwLines += '</div>';
    hwEl.innerHTML = hwLines;
    root.appendChild(hwEl);
  }

  const timelineByStep = new Map();
  (s.timeline_events || []).forEach(evt => {
    const key = Number(evt.after_step_index || 0);
    if (!timelineByStep.has(key)) timelineByStep.set(key, []);
    timelineByStep.get(key).push(evt);
  });

  s.steps.forEach(t => {
    const el = document.createElement("div");
    const idx = t.step_index;
    el.className = "step" + (selected.has(idx) ? " selected" : "");
    el.id = "step-" + idx;
    const u = t.usage || {};
    const env = t.environment || {};
    const usageAvail = u.available !== false;
    const usageNote = (!usageAvail && u.note) ? `<span class="muted xsmall"> (${u.note})</span>` : "";
    const postBadges = (t.post_step_badges || []).map(b => `<span class="pill yellow">${escapeHtml(b)}</span>`).join("");

    el.innerHTML = `
      <div class="step-head" onclick="toggleDetails(${idx})">
        <input type="checkbox" ${selected.has(idx) ? "checked" : ""} onclick="event.stopPropagation()" onchange="toggleSelect(${idx})">
        <div>
          <div class="step-title">
            <b>Step ${idx}</b>
            <span class="pill blue">${escapeHtml(t.model)}</span>
            <span class="pill purple">${escapeHtml(t.reasoning_effort)}</span>
            ${usageAvail ? '' : '<span class="pill yellow" title="Для этого шага нет подтвержденной per-step token delta">usage⚠</span>'}
            <span class="pill ${(t.warnings || []).length ? 'yellow' : 'green'}">${(t.warnings || []).length} warn</span>
            ${postBadges}
          </div>
          <div class="metrics">
            ${metric("Cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${metric("Input", usageNumber(u, "input_tokens"))}
            ${metric("Cached", usageNumber(u, "cached_tokens"))}
            ${metric("Non-cached", usageNumber(u, "non_cached_input_tokens"))}
            ${metric("Cache", usagePercent(u, "cached_ratio"))}
            ${metric("Output", usageNumber(u, "output_tokens"))}
            ${metric("Reasoning", usageNumber(u, "reasoning_tokens"))}
            ${metric("MCP", nf.format(env.observed_mcp_server_count))}
          </div>
          <div class="preview-row">
            <div class="preview">
              <span class="label">${t.user_prompt.kind === 'system_composed' ? 'System prompt' : 'Prompt'}</span>
              <div class="text">${t.user_prompt.available ? escapeHtml(ellipsis(t.user_prompt.text, 90)) : "—"}</div>
            </div>
            <div class="preview">
              <span class="label">Answer</span>
              <div class="text">${t.assistant_answer.available ? escapeHtml(ellipsis(t.assistant_answer.text, 90)) : "—"}</div>
            </div>
          </div>
        </div>
        <div class="row-actions">
          <button class="icon" onclick="event.stopPropagation();openStepPopup(${idx})">Подробно</button>
          <button class="icon" onclick="event.stopPropagation();copyStepSummary(${idx})">Copy</button>
        </div>
      </div>
      <div class="detail">
        ${textBlock(t.user_prompt.kind === 'system_composed' ? "System prompt (composed)" : "User prompt", "prompt", t.user_prompt.available, t.user_prompt.text, idx)}
        ${textBlock("Assistant answer", "answer", t.assistant_answer.available, t.assistant_answer.text, idx)}
        <div class="detail-grid">
          <div class="box">
            <h3>Tokens${usageNote}</h3>
            ${kv("input_tokens", usageNumber(u, "input_tokens"))}
            ${kv("cached_tokens", usageNumber(u, "cached_tokens"))}
            ${kv("non_cached", usageNumber(u, "non_cached_input_tokens"))}
            ${kv("cached_ratio", usagePercent(u, "cached_ratio"))}
            ${kv("output_tokens", usageNumber(u, "output_tokens"))}
            ${kv("reasoning_tokens", usageNumber(u, "reasoning_tokens"))}
            ${kv("tool_tokens", usageNumber(u, "tool_tokens"))}
          </div>
          <div class="box">
            <h3>Cost</h3>
            ${kv("input_cost", usageMoney(u, "estimated_input_cost_usd"))}
            ${kv("cached_cost", usageMoney(u, "estimated_cached_input_cost_usd"))}
            ${kv("output_cost", usageMoney(u, "estimated_output_cost_usd"))}
            ${kv("total_cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${kv("pricing", "config/token_pricing.json")}
          </div>
          <div class="box">
            <h3>Environment</h3>
            ${kv("thread_id", env.thread_id)}
            ${kv("turn_id", t.turn_id)}
            ${kv("MCP servers", (env.observed_mcp_servers || []).join(", ") || "none")}
            ${kv("plugins_count", env.enabled_plugins_count)}
            ${kv("skills_count", env.enabled_skills_count)}
            ${kv("repo_context", env.repo_context_status)}
            ${kv("warnings", (t.warnings || []).join(", ") || "none")}
          </div>
        </div>
        <div class="box" style="margin-top:8px">
          <h3>Стоимость шага (full step cost vs request cost)</h3>
          ${buildStepCostBlock(t)}
        </div>
      </div>`;
    root.appendChild(el);
  });
}

function selectedSteps() {
  if (!sessionDetailCache || !sessionDetailCache.steps) return [];
  return sessionDetailCache.steps.filter(t => selected.has(t.step_index));
}

function renderSelection() {
  const z = totals(selectedSteps());
  const ratio = z.input ? z.cached / z.input : 0;
  document.getElementById("selCount").textContent = `Selected: ${selectedSteps().length}`;
  document.getElementById("selCost").textContent = money(z.cost);
  document.getElementById("selNon").textContent = `Non-cached: ${nf.format(z.non)}`;
  document.getElementById("selCache").textContent = `Cache: ${pct(ratio)}`;
  updateRawDownloadButtons();
}

function renderStatus() {
  const collectorLabel = statusCache.collector || "unknown";
  const collectorDot = collectorLabel === "running" ? "" : (collectorLabel === "stopped" ? "red" : "warn");
  document.getElementById("collectorStatus").innerHTML = `<i class="dot ${collectorDot}"></i>${collectorLabel}`;

  const plEl = document.getElementById("promptLoggingStatus");
  if (plEl) {
    const plOn = statusCache.prompt_logging !== false;
    plEl.innerHTML = `<i class="dot ${plOn ? '' : 'warn'}"></i>${plOn ? 'ON' : 'OFF'}`;
  }

  document.getElementById("lastUpdate").textContent = statusCache.last_update
    ? new Date(statusCache.last_update).toLocaleTimeString("ru-RU")
    : "\u2014";
  document.getElementById("autoStatus").innerHTML = `<i class="dot ${autoRefresh && !stopped ? '' : 'warn'}"></i>${autoRefresh && !stopped ? 'ON \u00B7 3s' : 'OFF'}`;
  document.getElementById("autoBtn").textContent = "Auto: " + (autoRefresh ? "ON" : "OFF");
}

function populateModelFilter() {
  const seen = new Set();
  seen.add("mixed");
  sessionsCache.forEach(s => {
    if (s.model && s.model !== "unknown") seen.add(s.model);
  });
  const sel = document.getElementById("modelFilter");
  const currentValue = sel.value;
  sel.innerHTML = `<option value="">Все модели</option>`;
  [...seen].sort().forEach(m => {
    sel.innerHTML += `<option value="${m}">${m}</option>`;
  });
  sel.value = currentValue || "";
}

function renderAll() {
  renderSourceInfo();
  renderSessions();
  renderHeader();
  renderSteps();
  renderSelection();
  renderAuditPanel();
  renderStatus();
}

// ── Interactions ──
function toggleDetails(i) {
  const el = document.getElementById("step-" + i);
  if (el) {
    el.classList.toggle("open");
    if (el.classList.contains("open")) {
      expandedSteps.add(i);
    } else {
      expandedSteps.delete(i);
    }
  }
}

function toggleText(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.toggle("open");
    if (el.classList.contains("open")) {
      openTextBlocks.add(id);
    } else {
      openTextBlocks.delete(id);
    }
  }
}

function toggleSelect(i) {
  selected.has(i) ? selected.delete(i) : selected.add(i);
  renderSteps();
  renderSelection();
}

function selectAll() {
  if (!sessionDetailCache || !sessionDetailCache.steps) return;
  sessionDetailCache.steps.forEach(t => selected.add(t.step_index));
  renderSteps();
  renderSelection();
}

function clearSel() {
  selected.clear();
  renderSteps();
  renderSelection();
}

// ── Copy ──
function showToast(msg) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.style.display = "block";
  setTimeout(() => { toast.style.display = "none"; toast.textContent = "Скопировано"; }, 1100);
}

function copyText(txt) {
  navigator.clipboard.writeText(txt);
  showToast("Скопировано");
}

function copySourcePath() {
  const s = currentSource();
  const selectedPath = currentWorkdirFilter || "";
  copyText(selectedPath || (s ? (s.kind === "live" ? "C:/Users/andre/.codex" : "D:/Codex+Kilocode/projects/sword-of-rome-web/_local/codex-token-debugger") : ""));
}

function usageConfirmationLabel(usage) {
  if (!usage) return "нет данных";
  if (usage.confirmation_status === "confirmed_request_usage") return "подтверждено: request-level last_token_usage";
  if (usage.confirmation_status === "missing_request_usage") return "не подтверждено";
  return usage.available === false ? "не подтверждено" : "доступно";
}

function buildTelemetryWarnings(session, step) {
  const warnings = [];
  const summaryWarnings = session?.summary?.warnings || [];
  summaryWarnings.forEach(w => {
    if (typeof w === "string") warnings.push(w);
    else if (w && w.message) warnings.push(w.message);
  });

  if (session?.source_kind === "live") {
    warnings.push("В live-чате высокий cached input может относиться к переиспользованному скрытому контексту текущего запроса, а не только к видимому prompt.");
  }

  if (step) {
    const usage = step.usage || {};
    if (usage.note) warnings.push(`Usage note: ${usage.note}`);
    (step.warnings || []).forEach(w => warnings.push(`Step warning: ${w}`));
  }

  return [...new Set(warnings.filter(Boolean))];
}

function buildTimelineContext(session, step) {
  if (!session || !step) return [];
  return (session.timeline_events || [])
    .filter(evt => Number(evt.after_step_index || 0) === Number(step.step_index || 0))
    .map(evt => ({
      event_type: evt.event_type || "",
      label: evt.label || evt.event_type || "",
      timestamp: evt.timestamp || "",
      after_step_index: evt.after_step_index || 0,
      compaction_task_id: evt.compaction_task_id || null,
      after_step_turn_id: evt.after_step_turn_id || null,
    }));
}

function _humanConfLabel(conf) {
  if (conf === 'high') return 'high / raw';
  if (conf === 'low') return 'low / approx';
  if (conf === 'medium') return 'medium';
  return conf || 'not_verified';
}

function buildAgentActivityMarkdown(step) {
  const aa = step.agent_activity || {};
  if (!aa.available) return ["- данные недоступны"];
  const ac = aa.activity_counts || {};
  const lines = [];

  // ── v2.6: Главное резюме first ──
  const hsum = aa.human_summary_ru || {};
  if (hsum.available && hsum.text) {
    lines.push("### Главное резюме");
    lines.push("");
    lines.push(hsum.text);
    lines.push("");
  } else {
    // Fallback to old summary if human_summary_ru not available
    const summaryLines = aa.activity_summary_ru || [];
    if (summaryLines.length) {
      lines.push("### Главное резюме");
      lines.push("");
      summaryLines.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
      lines.push("");
    }
  }

  const sia = aa.step_internal_actions || [];
  const rwu = aa.requests_with_usage || 0;
  const mre = aa.model_related_events || 0;

  // ── Хронология работы ──
  const tl = aa.agent_timeline || {};
  const tlItems = tl.items || [];
  if (tlItems.length > 0) {
    lines.push("### Хронология работы");
    lines.push("");
      lines.push("| # | Время | Действие | Объекты | AI | Cost | Нов. input | Cached | Output | Reasoning | Δt | Увер. |");
      lines.push("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|");
      tlItems.forEach(it => {
        const lu = it.linked_request_usage || {};
        const lc = it.linked_cost || {};
        const dur = it.duration || {};
        const ts = it.timestamp ? new Date(it.timestamp).toLocaleTimeString('ru-RU') : '';
        const dt = dur.available ? (dur.seconds_since_previous_item >= 60 ? Math.round(dur.seconds_since_previous_item / 60) + 'm' : '+' + Math.round(dur.seconds_since_previous_item) + 's') : '';
        const displayTitle = it.display_title_ru || it.recognized_action_ru || '—';
        const aiLabel = it.linked_model_request_index ? '#' + it.linked_model_request_index : '—';
        const nonCached = lu.available ? (lu.non_cached_input_tokens || 0) : 0;
        const cached = lu.available ? (lu.cached_tokens || 0) : 0;
        const reasoning = lu.available ? (lu.reasoning_tokens || 0) : 0;
        const confLabel = _humanConfLabel(it.confidence || it.recognition_confidence);
        lines.push('| ' + it.index + ' | ' + ts + ' | ' + displayTitle.substring(0, 45) + ' | ' + (it.object_label || '').substring(0, 35) + ' | ' + aiLabel + ' | ' + (lc.total_usd != null ? '$' + Number(lc.total_usd).toFixed(5) : '—') + ' | ' + (lu.available ? nf.format(nonCached) : '—') + ' | ' + (lu.available ? nf.format(cached) : '—') + ' | ' + (lu.available ? nf.format(lu.output_tokens || 0) : '—') + ' | ' + (lu.available ? nf.format(reasoning) : '—') + ' | ' + dt + ' | ' + confLabel + ' |');
    });
    lines.push("");
    lines.push("### Что означает AI #");
    lines.push("");
    lines.push("AI # — это техническое скрытое обращение Codex к модели, по которому известны токены и стоимость.");
    lines.push("В хронологии оно используется как источник cost/usage для человеческого действия.");
    lines.push("");

    // ── v2.7: Детализация этапов ──
    var hasDetails = tlItems.some(function(it) { return (it.files && it.files.length) || (it.commands && it.commands.length) || (it.details && it.details.available); });
    if (hasDetails) {
      lines.push("### Детализация этапов");
      lines.push("");
      tlItems.forEach(function(it) {
        var fullTitle = it.full_title_ru || it.display_title_ru || '';
        var lc = it.linked_cost || {};
        var lu = it.linked_request_usage || {};
        var lai = it.linked_ai_call;
        var confLabel = _humanConfLabel(it.recognition_confidence || it.confidence);
        lines.push('<details>');
        lines.push('<summary>#' + it.index + ' ' + fullTitle + ' — ' + (lc.total_usd != null ? '$' + Number(lc.total_usd).toFixed(5) : '—') + '</summary>');
        lines.push('');
        if (lai) lines.push('**AI:** #' + lai.ai_index + '  ');
        lines.push('**Уверенность:** ' + confLabel + '  ');
        if (lc.total_usd != null) lines.push('**Cost:** $' + Number(lc.total_usd).toFixed(5) + '  ');
        if (lu.available || lai) {
          lines.push('');
          lines.push('**Статистика:** Input: ' + nf.format(lai?lai.input_tokens:(lu.input_tokens||0)) + ' | New input: ' + nf.format(lai?lai.non_cached_input_tokens:(lu.non_cached_input_tokens||0)) + ' | Cached: ' + nf.format(lai?lai.cached_tokens:(lu.cached_tokens||0)) + ' | Output: ' + nf.format(lai?lai.output_tokens:(lu.output_tokens||0)) + ' | Reasoning: ' + nf.format(lai?lai.reasoning_tokens:(lu.reasoning_tokens||0)));
        }
        lines.push('');

        // ── v2.13: Context contribution table (moved to technical section) ──
        var isServiceAction = (it.display_title_ru||'').indexOf('Обновил план') >= 0 || (it.display_title_ru||'').indexOf('Выполнил служебное') >= 0;
        var hasContextObjects = false;
        var allCtxObjects = [];
        (it.files||[]).forEach(function(f) {
          var cc = f.context_contribution || {};
          if (cc.output_length_chars || cc.estimated_text_tokens) { hasContextObjects = true; }
          allCtxObjects.push({kind:'file',obj:f,cc:cc});
        });
        (it.commands||[]).forEach(function(c) {
          if (c.classified_action !== 'file_read' && c.classified_action !== 'file_read_batch') {
            var cc = c.context_contribution || {};
            if (cc.output_length_chars || cc.estimated_text_tokens) { hasContextObjects = true; }
            allCtxObjects.push({kind:'command',obj:c,cc:cc});
          }
        });
        if (hasContextObjects && allCtxObjects.length > 0) {
          lines.push('**Вклад файлов и команд в New input:**');
          lines.push('');
          lines.push('| Объект | Тип | Размер | ~New input tokens | Доля | ~Вклад в New input cost |');
          lines.push('|---|---:|---:|---:|---:|---:|');
          var ncTokens = lai ? lai.non_cached_input_tokens : (lu.non_cached_input_tokens || 0);
          allCtxObjects.forEach(function(ao) {
            var cc = ao.cc;
            var obj = ao.obj;
            var name = ao.kind==='file' ? (obj.display_name||obj.path||'?').split('\\').pop().split('/').pop() : (obj.command||'').substring(0,50);
            var type = ao.kind==='file' ? (obj.operation||'read') : (obj.classified_action||'cmd');
            if (ao.kind==='file' && obj.read_count > 1) name += ' (' + obj.read_count + ' фрагм.)';
            var share = cc.share_of_tool_output_text;
            var estTokens = (share != null && ncTokens > 0) ? Math.round(share * ncTokens) : null;
            var estCost = cc.estimated_new_input_cost_usd;
            lines.push('| ' + name + ' | ' + type + ' | ' + (cc.output_length_chars ? nf.format(cc.output_length_chars) : '—') + ' | ' + (estTokens != null ? '~'+nf.format(estTokens) : '—') + ' | ' + (share != null ? Number(share*100).toFixed(0)+'%' : '—') + ' | ' + (estCost != null ? '~$'+Number(estCost).toFixed(6) : '—') + ' |');
          });
          lines.push('');
          lines.push('> Это оценка. Raw telemetry даёт точную стоимость только на уровне AI-call целиком. Cached, Output и Reasoning не распределяются по отдельным файлам/командам.');
          lines.push('');
        }

        // ── v2.10: per-action-kind details ──
        var apd = it.apply_patch_data;
        var pud = it.plan_update_data;
        var isPlanUpdate = pud && pud.available;
        var isApplyPatch = apd && apd.available;
        var isModelOnly = it.row_type === 'ai_call_only';
        var files = it.files;
        var cmds = it.commands;

        if (isPlanUpdate) {
          lines.push('**План работы**');
          lines.push('');
          lines.push(pud.note_ru || '');
          lines.push('');
          if (pud.explanation) {
            lines.push('Explanation: ' + pud.explanation);
            lines.push('');
          }
          if (pud.plan_items && pud.plan_items.length) {
            lines.push('План:');
            pud.plan_items.forEach(function(pi, i) { lines.push((i+1) + '. ' + String(pi)); });
            lines.push('');
          }
        } else if (isApplyPatch) {
          lines.push('**Patch-действие**');
          lines.push('');
          if (apd.patch_status) lines.push('- Статус: ' + apd.patch_status);
          if (files && files.length) {
            files.forEach(function(f) {
              lines.push('- Файл: `' + f.path + '`');
              if (f.operation) lines.push('  Роль: ' + f.operation);
            });
          }
          if (apd.patch_input_chars) lines.push('- Patch input: ' + nf.format(apd.patch_input_chars) + ' chars (~' + nf.format(apd.estimated_patch_tokens||0) + ' ток.)');
          if (apd.output_length) lines.push('- Tool output: ' + nf.format(apd.output_length) + ' chars (~' + nf.format(apd.estimated_tool_output_tokens||0) + ' ток.)');
          lines.push('');
          if (apd.cost_note_ru) lines.push(apd.cost_note_ru);
          lines.push('');
        } else if (isModelOnly) {
          var isFinalReport = (it.display_title_ru||'').indexOf('Сформулировал') >= 0;
          if (isFinalReport) {
            var amd = it.assistant_message_data;
            lines.push('**Финальный ответ агента**');
            lines.push('');
            if (amd && amd.available) {
              if (amd.cost_explanation_ru) { lines.push(amd.cost_explanation_ru); lines.push(''); }
              if (amd.message_length_chars) lines.push('- Размер ответа: ' + nf.format(amd.message_length_chars) + ' симв.');
              if (amd.message_text_location_ru) lines.push('- ' + amd.message_text_location_ru);
              if (amd.source) lines.push('- Источник: ' + amd.source + ' (' + (amd.source_confidence||'') + ')');
              if (amd.message_preview) {
                lines.push('');
                lines.push('Preview:');
                lines.push(amd.message_preview);
              }
            } else {
              lines.push('AI-call без новых tool events, но с visible assistant message. Стоимость относится к генерации финального отчёта.');
            }
            lines.push('');
          } else {
            lines.push('**Model-only AI-call**');
            lines.push('');
            lines.push('В raw telemetry нет прямых tool events для этого AI-обращения. Вероятно, модель анализировала уже загруженный контекст или формулировала следующий шаг.');
            lines.push('');
          }
        } else if (files && files.length) {
          lines.push('**Файлы:**');
          files.forEach(function(f) {
            var label = '- `' + f.path + '`';
            if (f.read_count > 1) {
              label += ' — ' + f.read_count + ' фрагментов';
              if (f.ranges && f.ranges.length) label += ' [' + f.ranges.join(', ') + ']';
            }
            if (f.operation) label += ' (' + f.operation + ')';
            lines.push(label);
          });
          lines.push('');
        } else {
          lines.push('**Файлы:** нет подтверждённых файлов');
          lines.push('');
        }
        // Commands (always show in technical/details section)
        if (cmds && cmds.length) {
          lines.push('**Команды:**');
          cmds.forEach(function(c) {
            lines.push('- `' + (c.command||'').substring(0, 120) + '`');
            if (c.workdir) lines.push('  workdir: ' + c.workdir + ', exit: ' + (c.exit_code != null ? c.exit_code : '?'));
          });
          lines.push('');
        }
        // Raw evidence
        var rev = it.raw_evidence;
        if (rev && rev.length) {
          lines.push('**Raw evidence:**');
          rev.forEach(function(r) { lines.push('- event #' + r.event_index + ' `' + r.payload_type + '` call_id=' + r.call_id); });
          lines.push('');
        }
        lines.push('</details>');
        lines.push('');
      });
    }
  }

  // ── Самые дорогие действия ──
  const eha = aa.expensive_human_actions || [];
  if (eha.length > 0) {
    lines.push("### Самые дорогие действия");
    lines.push("");
    lines.push("| # | Действие | AI | Cost | Нов. input | Cached | Output | Reasoning | Почему дорого | Увер. |");
    lines.push("|---:|---|---:|---:|---:|---:|---:|---|---|");
    eha.forEach(eh => {
      const confLabel = _humanConfLabel(eh.confidence);
      lines.push('| ' + eh.index + ' | ' + (eh.display_title_ru || '').substring(0, 45) + ' | ' + (eh.linked_model_request_index ? '#' + eh.linked_model_request_index : '—') + ' | ' + (eh.total_usd != null ? '$' + Number(eh.total_usd).toFixed(5) : '—') + ' | ' + nf.format(eh.non_cached_input_tokens || 0) + ' | ' + nf.format(eh.cached_tokens || 0) + ' | ' + nf.format(eh.output_tokens || 0) + ' | ' + nf.format(eh.reasoning_tokens || 0) + ' | ' + (eh.expensive_reason || '—') + ' | ' + confLabel + ' |');
    });
    lines.push("");
  }

  // ── Mentioned files ──
  const paths = aa.important_paths || [];
  if (paths.length) {
    lines.push("### Файлы и команды");
    lines.push("");
    lines.push("Упомянутые / задействованные файлы:");
    paths.slice(0, 8).forEach(p => lines.push(`- ${p}`));
    lines.push("");
  }

  // Commands
  const cmds = aa.important_commands || [];
  if (cmds.length) {
    lines.push("Команды и проверки:");
    cmds.slice(0, 5).forEach(c => lines.push(`- \`${c}\``));
    lines.push("");
  }

  // ── Техническая детализация ──
  const hasTechnical = (sia.length > 0) || (aa.agent_activity_stages || []).length > 0;
  if (hasTechnical) {
    lines.push("### Техническая детализация");
    lines.push("");
    lines.push("> Ниже технические данные. Они нужны для аудита, но не являются основным человеческим отчётом.");
    lines.push("");

    // Technical AI calls
    const tac = aa.technical_ai_calls || {};
    const tacItems = tac.items || [];
    if (tacItems.length > 0) {
      lines.push("#### Технические AI-обращения");
      lines.push("");
      lines.push("| AI | Cost | Input | Нов. input | Output | Связан |");
      lines.push("|---:|---:|---:|---:|---:|---|");
      tacItems.forEach(ai => {
        lines.push(`| #${ai.ai_index} | ${ai.cost_total_usd != null ? '$' + Number(ai.cost_total_usd).toFixed(5) : '—'} | ${nf.format(ai.input_tokens || 0)} | ${nf.format(ai.non_cached_input_tokens || 0)} | ${nf.format(ai.output_tokens || 0)} | ${ai.linked_to_human_item ? '✓' : '—'} |`);
      });
      lines.push("");
    }

    // Stages (low confidence)
    const stages = aa.agent_activity_stages || [];
    if (stages.length > 0) {
      lines.push("#### Низкоуверенные этапы из текста ответа");
      lines.push("");
      lines.push("| Этап | Запросы | Cost | Input | Output | Уверенность |");
      lines.push("|---|---:|---:|---:|---:|---|");
      stages.forEach(s => {
        lines.push(`| ${s.title_ru} | ${s.request_range || ''} | $${Number(s.cost_total_usd || 0).toFixed(5)} | ${nf.format(s.input_tokens || 0)} | ${nf.format(s.output_tokens || 0)} | ${s.confidence || 'low'} |`);
      });
      lines.push("");
      lines.push("> Этапы построены по тексту ответа агента; точная привязка каждого внутреннего запроса не подтверждена.");
      lines.push("");
    }

    // Internal requests table
    if (sia.length > 0) {
      lines.push(`#### Внутренние запросы модели по времени (${rwu} запросов с usage` + (mre !== rwu ? `, ${mre} model-событий` : '') + ')');
      lines.push("");
      lines.push("| # | Запрос | Возможный этап | Cost | Input | Non-cached | Cached | Output | Уверенность |");
      lines.push("|---|--------|----------------|------|-------|------------|--------|--------|------------|");
      sia.forEach(a => {
        const u = a.usage || {};
        const c = a.cost || {};
        lines.push(`| ${a.index} | ${a.title_ru || ''} | ${a.possible_stage_ru || '—'} | ${c.total_usd != null ? '$' + Number(c.total_usd).toFixed(5) : '—'} | ${nf.format(u.input_tokens || 0)} | ${nf.format(u.non_cached_input_tokens || 0)} | ${nf.format(u.cached_tokens || 0)} | ${nf.format(u.output_tokens || 0)} | ${a.stage_confidence || 'low'} |`);
      });
      lines.push("");
    }

    // ── v2.13: Token cost breakdown (per-step, technical) ──
    // Добавим breakdown для каждого шага, который его имеет
    var stepsWithBreakdown = tlItems.filter(function(it) { return it.token_cost_breakdown && it.token_cost_breakdown.available; });
    if (stepsWithBreakdown.length > 0) {
      lines.push("#### Стоимость по типам токенов (по шагам)");
      lines.push("");
      stepsWithBreakdown.forEach(function(it) {
        var tcb = it.token_cost_breakdown;
        var stepTitle = (it.display_title_ru || it.full_title_ru || 'Шаг #' + it.index).substring(0, 40);
        lines.push('**' + stepTitle + ':**');
        lines.push('');
        lines.push('| Тип | Кол-во | Цена за 1M | Стоимость |');
        lines.push('|---|---:|---:|---:|');
        var items = tcb.items || [];
        for (var ki = 0; ki < items.length; ki++) {
          var item = items[ki];
          var kindLabel = item.kind === 'new_input' ? 'Новый ввод' : (item.kind === 'cached_input' ? 'Кэш' : 'Вывод');
          lines.push('| ' + kindLabel + ' | ' + nf.format(item.tokens || 0) + ' | $' + Number(item.price_per_million || 0).toFixed(2) + ' | $' + Number(item.cost_usd || 0).toFixed(6) + ' |');
        }
        lines.push('| **Итого** | | | **$' + Number(tcb.total_from_breakdown_usd || 0).toFixed(6) + '** |');
        if (tcb.reasoning_note) {
          lines.push('');
          lines.push(tcb.reasoning_note);
        }
        lines.push('');
      });
    }

    // Technical expensive
    const te = aa.top_expensive_internal_actions || [];
    if (te.length > 0) {
      lines.push("#### Самые дорогие внутренние запросы");
      lines.push("");
      lines.push("| # | Контекст этапа | AI | Cost | Input | Cached | Non-cached | Output | Reasoning | Причина |");
      lines.push("|---|--------------|----|------|-------|--------|------------|--------|-----------|--------|");
      te.slice(0, 10).forEach(a => {
        const ac = a.cost || {};
        const au = a.usage || {};
        const displayName = (a.possible_stage_ru || a.title_ru || '').substring(0, 45);
        lines.push('| ' + a.index + ' | ' + displayName + ' | #' + a.index + ' | ' + (ac.total_usd != null ? '$' + Number(ac.total_usd).toFixed(5) : '—') + ' | ' + nf.format(au.input_tokens || 0) + ' | ' + nf.format(au.cached_tokens || 0) + ' | ' + nf.format(au.non_cached_input_tokens || 0) + ' | ' + nf.format(au.output_tokens || 0) + ' | ' + nf.format(au.reasoning_tokens || 0) + ' | ' + (a.expensive_reason || '—') + ' |');
      });
      lines.push("");
    }

    // Technical events count
    const classified = (ac.file_reads || 0) + (ac.file_writes || 0) + (ac.shell_commands || 0) +
      (ac.git_operations || 0) + (ac.test_runs || 0) + (ac.context_compactions || 0) +
      (ac.internal_prompts || 0) + (ac.environment_events || 0);
    const unclassified = (aa.unclassified_raw_events || 0) + (ac.unknown_events || 0);
    lines.push("#### Технические события");
    lines.push("");
    lines.push(`- Внутренних запросов модели: ${ac.model_requests || 0}`);
    lines.push(`- Сырых событий: ${aa.event_range?.raw_events_count || 0}`);
    lines.push(`- Распознано действий: ${classified}`);
    if (unclassified > 0) lines.push(`- Нераспознано событий: ${unclassified}`);
    lines.push("");
  }

  // Notes
  (aa.notes_ru || []).forEach(n => lines.push(`> ${n}`));

  return lines;
}

function buildStepSummaryBlock(t) {
  const aa = t.agent_activity || {};
  const fsc = t.full_step_cost || {};
  const fsu = t.full_step_usage || {};
  const lines = [];
  // v2.6: show human summary first
  const hsum = aa.human_summary_ru || {};
  if (hsum.available && hsum.text) {
    lines.push('<div class="muted" style="font-weight:600;margin-bottom:2px">Главное резюме:</div>');
    lines.push('<div class="muted xsmall" style="margin-bottom:4px">' + escapeHtml(hsum.text) + '</div>');
  }
  lines.push(kv("полная стоимость шага", moneyOrNA(fsc.total_usd)));
  lines.push(kv("внутренних запросов", nf.format(fsu.request_count || 0)));
  const eha = aa.expensive_human_actions || [];
  if (eha.length > 0) {
    lines.push(kv("самое дорогое действие", (eha[0].display_title_ru || '').substring(0, 40) + ' ($' + (eha[0].total_usd != null ? Number(eha[0].total_usd).toFixed(5) : '—') + ')'));
  }
  const tl = aa.agent_timeline || {};
  if ((tl.items || []).length) lines.push(kv("событий в хронологии", nf.format(tl.items.length)));
  lines.push('<div class="muted xsmall" style="margin-top:4px">Нажмите «Подробно» для полной информации.</div>');
  return lines.join("");
}

// ── v2.6: Agent activity block (human-first ordering) ──
function buildAgentActivityBlock(t) {
  const aa = t.agent_activity || {};
  if (!aa.available) {
    return kv("данные", "недоступны");
  }
  const ac = aa.activity_counts || {};
  const lines = [];

  // ── Главное резюме ──
  const hsum = aa.human_summary_ru || {};
  if (hsum.available && hsum.text) {
    lines.push('<div class="muted" style="font-weight:600;margin-bottom:2px">Главное резюме:</div>');
    lines.push('<div class="muted xsmall" style="margin-bottom:6px">' + escapeHtml(hsum.text) + '</div>');
  } else {
    // Fallback to old tag list
    const summaryLines = aa.activity_summary_ru || [];
    if (summaryLines.length) {
      lines.push('<div class="muted" style="font-weight:600;margin-bottom:2px">Кратко:</div>');
      summaryLines.forEach((s, i) => {
        lines.push('<div class="muted xsmall">' + (i + 1) + '. ' + escapeHtml(s) + '</div>');
      });
      lines.push('<hr class="thin">');
    }
  }

  // ── Mentioned / involved files ──
  const paths = aa.important_paths || [];
  if (paths.length > 0) {
    lines.push('<div class="muted" style="font-weight:600">Упомянутые / задействованные файлы:</div>');
    paths.slice(0, 8).forEach(p => {
      lines.push('<div class="muted xsmall" style="font-family:monospace">' + escapeHtml(p) + '</div>');
    });
  }

  // ── Commands and checks ──
  const cmds = aa.important_commands || [];
  if (cmds.length > 0) {
    lines.push('<div class="muted" style="font-weight:600;margin-top:4px">Команды и проверки:</div>');
    cmds.slice(0, 5).forEach(c => {
      lines.push('<div class="muted xsmall" style="font-family:monospace">' + escapeHtml(c) + '</div>');
    });
  }

  // ── Technical events ──
  lines.push('<hr class="thin">');
  lines.push('<div class="muted" style="font-weight:600">Технические события:</div>');
  lines.push(kv("внутренних запросов модели", nf.format(ac.model_requests || 0)));
  lines.push(kv("сырых событий", nf.format(aa.event_range?.raw_events_count || 0)));

  const classified = (ac.file_reads || 0) + (ac.file_writes || 0) + (ac.shell_commands || 0) +
    (ac.git_operations || 0) + (ac.test_runs || 0) + (ac.context_compactions || 0) +
    (ac.internal_prompts || 0) + (ac.environment_events || 0);
  const unclassified = (aa.unclassified_raw_events || 0) + (ac.unknown_events || 0);
  lines.push(kv("распознано действий", nf.format(classified)));
  if (unclassified > 0) {
    lines.push(kv("нераспознано событий", nf.format(unclassified)));
  }

  // ── Tool breakdown ──
  const items = aa.activity_items || [];
  if (items.length > 0) {
    const toolCounts = {};
    items.forEach(it => {
      const tn = it.tool_name || it.category || '?';
      toolCounts[tn] = (toolCounts[tn] || 0) + 1;
    });
    const topTools = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 6);
    if (topTools.length) {
      lines.push('<span class="muted xsmall">Инструменты:</span>');
      topTools.forEach(([tn, cnt]) => {
        lines.push('<div class="muted xsmall" style="font-family:monospace">' + escapeHtml(tn) + ' ×' + cnt + '</div>');
      });
    }

    // Collapsible detailed items
    const detailId = 'activity-detail-' + t.step_index;
    lines.push('<button class="small" onclick="var el=document.getElementById(\'' + detailId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">Показать события (' + items.length + ')</button>');
    lines.push('<div id="' + detailId + '" style="display:none;max-height:300px;overflow-y:auto;font-size:11px;margin-top:4px">');
    items.forEach(it => {
      const tn = it.tool_name ? '<b>' + escapeHtml(it.tool_name) + '</b>: ' : '';
      const st = it.status === 'reported_by_agent' ? ' <span style="color:#888">[со слов агента]</span>' : '';
      lines.push('<div style="padding:1px 0;border-bottom:1px solid #eee">' + tn + escapeHtml(it.detail || '') + st + '</div>');
    });
    lines.push('</div>');
  }

  // ── Timeline ──
  const tl = aa.agent_timeline || {};
  const tlItems = tl.items || [];
  if (tlItems.length > 0) {
    const tlId = 'tl-' + t.step_index;
    lines.push('<hr class="thin">');
    lines.push('<div class="muted" style="font-weight:600">Хронология работы (' + tlItems.length + ' событий)</div>');
    lines.push('<button class="small" onclick="var el=document.getElementById(\'' + tlId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">Свернуть</button>');
    lines.push('<div id="' + tlId + '" style="display:block;max-height:450px;overflow:auto;font-size:10px;margin-top:4px">');
    lines.push('<table style="width:100%;border-collapse:collapse"><thead><tr style="background:#333">');
    lines.push('<th style="text-align:right;padding:2px 4px">#</th><th style="text-align:left;padding:2px 4px;min-width:70px">Время</th>');
    lines.push('<th style="text-align:left;padding:2px 4px">Действие</th><th style="text-align:left;padding:2px 4px;min-width:60px">Объекты</th>');
    lines.push('<th style="text-align:center;padding:2px 4px;min-width:30px">AI</th>');
    lines.push('<th style="text-align:right;padding:2px 4px">Cost</th><th style="text-align:right;padding:2px 4px">Нов. input</th>');
    lines.push('<th style="text-align:right;padding:2px 4px">Output</th><th style="text-align:right;padding:2px 4px">Δt</th>');
    lines.push('<th style="text-align:center;padding:2px 4px">Увер.</th></tr></thead><tbody>');
    tlItems.forEach(function(it) {
      var lu = it.linked_request_usage || {};
      var lc = it.linked_cost || {};
      var dur = it.duration || {};
      var ts = it.timestamp ? new Date(it.timestamp).toLocaleTimeString('ru-RU') : '';
      var dt = dur.available ? (dur.seconds_since_previous_item >= 60 ? Math.round(dur.seconds_since_previous_item / 60) + 'm' : '+' + Math.round(dur.seconds_since_previous_item) + 's') : '';
      var displayTitle = it.display_title_ru || it.recognized_action_ru || '—';
      var aiLabel = it.linked_model_request_index ? '#' + it.linked_model_request_index : '—';
      var nonCached = lu.available ? (lu.non_cached_input_tokens || 0) : 0;
      var rowStyle = '';
      if (it.row_type === 'action_only') rowStyle = 'color:#888;font-style:italic';
      if (it.row_type === 'ai_call_only') rowStyle = 'color:#aaa;';
      lines.push('<tr style="' + rowStyle + '">');
      lines.push('<td style="text-align:right;padding:1px 4px">' + it.index + '</td>');
      lines.push('<td style="padding:1px 4px;white-space:nowrap;font-size:9px">' + ts + '</td>');
      lines.push('<td style="padding:1px 4px" title="' + escapeHtml(displayTitle) + '">' + escapeHtml(displayTitle.substring(0, 55)) + '</td>');
      lines.push('<td style="padding:1px 4px;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px" title="' + escapeHtml(it.object_label || '') + '">' + escapeHtml((it.object_label || '').substring(0, 40)) + '</td>');
      lines.push('<td style="text-align:center;padding:1px 4px;font-weight:600;font-size:10px">' + aiLabel + '</td>');
      lines.push('<td style="text-align:right;padding:1px 4px;font-weight:600">' + (lc.total_usd != null ? '$' + Number(lc.total_usd).toFixed(5) : '—') + '</td>');
      lines.push('<td style="text-align:right;padding:1px 4px">' + (lu.available ? nf.format(nonCached) : '—') + '</td>');
      lines.push('<td style="text-align:right;padding:1px 4px">' + (lu.available ? nf.format(lu.output_tokens || 0) : '—') + '</td>');
      lines.push('<td style="text-align:right;padding:1px 4px;color:#888;font-size:9px">' + dt + '</td>');
      lines.push('<td style="text-align:center;padding:1px 4px;font-size:9px">' + escapeHtml(it.confidence || it.recognition_confidence || 'low') + '</td>');
      lines.push('</tr>');
    });
    lines.push('</tbody></table></div>');

    // ── Technical AI calls table ──
    var tac = aa.technical_ai_calls || {};
    var tacItems = tac.items || [];
    if (tacItems.length > 0) {
      var tacId = 'tac-' + t.step_index;
      lines.push('<hr class="thin">');
      lines.push('<div class="muted" style="font-weight:600">Технические AI-обращения (' + tacItems.length + ')</div>');
      lines.push('<button class="small" onclick="var el=document.getElementById(\'' + tacId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">Показать</button>');
      lines.push('<div id="' + tacId + '" style="display:none;max-height:350px;overflow:auto;font-size:10px;margin-top:4px">');
      lines.push('<div class="muted xsmall" style="margin-bottom:4px">AI # — техническое скрытое обращение Codex к модели. В хронологии используется как источник cost/usage.</div>');
      lines.push('<table style="width:100%;border-collapse:collapse"><thead><tr style="background:#333">');
      lines.push('<th style="text-align:center;padding:2px 4px">AI</th><th style="text-align:right;padding:2px 4px">Cost</th>');
      lines.push('<th style="text-align:right;padding:2px 4px">Input</th><th style="text-align:right;padding:2px 4px">Нов. input</th>');
      lines.push('<th style="text-align:right;padding:2px 4px">Output</th><th style="text-align:center;padding:2px 4px">Связан</th>');
      lines.push('</tr></thead><tbody>');
      tacItems.forEach(function(ai) {
        lines.push('<tr>');
        lines.push('<td style="text-align:center;padding:1px 4px;font-weight:600">#' + ai.ai_index + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px;font-weight:600">' + (ai.cost_total_usd != null ? '$' + Number(ai.cost_total_usd).toFixed(5) : '—') + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + nf.format(ai.input_tokens || 0) + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + nf.format(ai.non_cached_input_tokens || 0) + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + nf.format(ai.output_tokens || 0) + '</td>');
        lines.push('<td style="text-align:center;padding:1px 4px;font-size:9px">' + (ai.linked_to_human_item ? '✓' : '—') + '</td>');
        lines.push('</tr>');
      });
      lines.push('</tbody></table></div>');
    }
  }

  // ── v2.6: Самые дорогие действия ──
  const eha = aa.expensive_human_actions || [];
  if (eha.length > 0) {
    const ehaId = 'eha-' + t.step_index;
    lines.push('<hr class="thin">');
    lines.push('<div class="muted" style="font-weight:600">Самые дорогие действия (' + eha.length + ')</div>');
    lines.push('<button class="small" onclick="var el=document.getElementById(\'' + ehaId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">Показать</button>');
    lines.push('<div id="' + ehaId + '" style="display:none;max-height:350px;overflow:auto;font-size:10px;margin-top:4px">');
    lines.push('<table style="width:100%;border-collapse:collapse"><thead><tr style="background:#333">');
    lines.push('<th style="text-align:right;padding:2px 4px">#</th><th style="text-align:left;padding:2px 4px">Действие</th>');
    lines.push('<th style="text-align:center;padding:2px 4px">AI</th><th style="text-align:right;padding:2px 4px">Cost</th>');
    lines.push('<th style="text-align:left;padding:2px 4px">Почему дорого</th><th style="text-align:center;padding:2px 4px">Увер.</th>');
    lines.push('</tr></thead><tbody>');
    eha.forEach(function(eh) {
      var confLabel = _humanConfLabel(eh.confidence);
      lines.push('<tr>');
      lines.push('<td style="text-align:right;padding:1px 4px">' + eh.index + '</td>');
      lines.push('<td style="padding:1px 4px">' + escapeHtml((eh.display_title_ru || '').substring(0, 50)) + '</td>');
      lines.push('<td style="text-align:center;padding:1px 4px;font-weight:600">' + (eh.linked_model_request_index ? '#' + eh.linked_model_request_index : '—') + '</td>');
      lines.push('<td style="text-align:right;padding:1px 4px;font-weight:600">' + (eh.total_usd != null ? '$' + Number(eh.total_usd).toFixed(5) : '—') + '</td>');
      lines.push('<td style="padding:1px 4px;font-size:9px">' + (eh.expensive_reason || '—') + '</td>');
      lines.push('<td style="text-align:center;padding:1px 4px;font-size:9px">' + confLabel + '</td>');
      lines.push('</tr>');
    });
    lines.push('</tbody></table></div>');
  }

  // ── v2.6: Техническая детализация ──
  const hasTech = (aa.agent_activity_stages || []).length > 0 || (aa.requests_with_usage || 0) > 0;
  if (hasTech) {
    var techId = 'tech-' + t.step_index;
    lines.push('<hr class="thin">');
    lines.push('<div class="muted" style="font-weight:600">Техническая детализация</div>');
    lines.push('<div class="muted xsmall" style="margin-bottom:2px">Ниже технические данные. Они нужны для аудита, но не являются основным человеческим отчётом.</div>');
    lines.push('<button class="small" onclick="var el=document.getElementById(\'' + techId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">Показать</button>');
    lines.push('<div id="' + techId + '" style="display:none;margin-top:4px">');

    // ── Stages (inside technical) ──
    const stages = aa.agent_activity_stages || [];
    if (stages.length > 0) {
      lines.push('<div class="muted" style="font-weight:600;margin-top:6px">Этапы работы агента (приблизительно)</div>');
      lines.push('<table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:2px"><thead><tr style="background:#333">');
      lines.push('<th style="text-align:left;padding:2px 4px">Этап</th><th style="text-align:right;padding:2px 4px">Запросы</th>');
      lines.push('<th style="text-align:right;padding:2px 4px">Cost</th><th style="text-align:right;padding:2px 4px">Input</th>');
      lines.push('<th style="text-align:right;padding:2px 4px">Output</th><th style="text-align:center;padding:2px 4px">Увер.</th>');
      lines.push('</tr></thead><tbody>');
      stages.forEach(function(s) {
        lines.push('<tr>');
        lines.push('<td style="padding:1px 4px">' + escapeHtml(s.title_ru) + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + (s.request_range || '') + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px;font-weight:600">$' + Number(s.cost_total_usd || 0).toFixed(5) + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + nf.format(s.input_tokens || 0) + '</td>');
        lines.push('<td style="text-align:right;padding:1px 4px">' + nf.format(s.output_tokens || 0) + '</td>');
        lines.push('<td style="text-align:center;padding:1px 4px;font-size:9px">' + escapeHtml(s.confidence || 'low') + '</td>');
        lines.push('</tr>');
      });
      lines.push('</tbody></table>');
    }

    // ── Internal requests table (inside technical) ──
    const sia = aa.step_internal_actions || [];
    const rwu = aa.requests_with_usage || 0;
    const mre = aa.model_related_events || 0;
    if (rwu > 0) {
    lines.push('<hr class="thin">');
    lines.push('<div class="muted" style="font-weight:600">Внутренние запросы (' + rwu + ' с usage' + (mre !== rwu ? ', ' + mre + ' model-событий' : '') + ')</div>');

    const timeTableId = 'ia-time-' + t.step_index;
    const costTableId = 'ia-cost-' + t.step_index;
    lines.push('<button class="small" onclick="document.getElementById(\'' + timeTableId + '\').style.display=\'block\';document.getElementById(\'' + costTableId + '\').style.display=\'none\'" style="margin-right:4px">По времени</button>');
    lines.push('<button class="small" onclick="document.getElementById(\'' + costTableId + '\').style.display=\'block\';document.getElementById(\'' + timeTableId + '\').style.display=\'none\'">По расходу</button>');

    function buildIaTable(items, id) {
      var h = '<div id="' + id + '" style="' + (id === timeTableId ? '' : 'display:none;') + 'max-height:450px;overflow:auto;font-size:10px;margin-top:4px">';
      h += '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:#333">';
      h += '<th style="text-align:right;padding:2px 4px">#</th>';
      h += '<th style="text-align:left;padding:2px 4px">Запрос</th>';
      h += '<th style="text-align:left;padding:2px 4px;min-width:120px">Возможный этап</th>';
      h += '<th style="text-align:right;padding:2px 4px">Cost</th>';
      h += '<th style="text-align:right;padding:2px 4px">Input</th>';
      h += '<th style="text-align:right;padding:2px 4px">Non-cached</th>';
      h += '<th style="text-align:right;padding:2px 4px">Cached</th>';
      h += '<th style="text-align:right;padding:2px 4px">Output</th>';
      h += '<th style="text-align:center;padding:2px 4px">Увер.</th>';
      h += '</tr></thead><tbody>';
      items.forEach(function(a) {
        var u = a.usage || {};
        var c = a.cost || {};
        var er = a.expensive_reason || '';
        h += '<tr>';
        h += '<td style="text-align:right;padding:1px 4px">' + a.index + '</td>';
        h += '<td style="padding:1px 4px;white-space:nowrap" title="' + escapeHtml(a.title_ru || '') + '">' + escapeHtml((a.title_ru || '').substring(0, 50)) + '</td>';
        h += '<td style="padding:1px 4px;color:#888;font-size:9px">' + escapeHtml((a.possible_stage_ru || '').substring(0, 60)) + '</td>';
        h += '<td style="text-align:right;padding:1px 4px;font-weight:600">' + (c.total_usd != null ? '$' + Number(c.total_usd).toFixed(5) : '—') + '</td>';
        h += '<td style="text-align:right;padding:1px 4px">' + nf.format(u.input_tokens || 0) + '</td>';
        h += '<td style="text-align:right;padding:1px 4px">' + nf.format(u.non_cached_input_tokens || 0) + (er ? '<br><span style="color:#c09853;font-size:8px">' + escapeHtml(er) + '</span>' : '') + '</td>';
        h += '<td style="text-align:right;padding:1px 4px;color:#888">' + nf.format(u.cached_tokens || 0) + '</td>';
        h += '<td style="text-align:right;padding:1px 4px">' + nf.format(u.output_tokens || 0) + '</td>';
        h += '<td style="text-align:center;padding:1px 4px;font-size:9px">' + escapeHtml(a.stage_confidence || a.confidence || 'low') + '</td>';
        h += '</tr>';
      });
      h += '</tbody></table></div>';
      return h;
    }

    lines.push(buildIaTable(sia, timeTableId));
    var costSorted = [...sia].sort(function(a, b) { return (b.cost.total_usd || 0) - (a.cost.total_usd || 0); });
    lines.push(buildIaTable(costSorted, costTableId));
    }  // end if (rwu > 0)

    lines.push('</div>');  // close tech div
  }  // end if (hasTech)

  // ── Note ──
  const notes = aa.notes_ru || [];
  if (notes.length > 0) {
    lines.push('<hr class="thin">');
    notes.forEach(n => {
      lines.push('<div class="muted xsmall" style="font-style:italic">' + escapeHtml(n) + '</div>');
    });
  }

  return lines.join("");
}

// ── v2.1: Step cost block (full step cost vs request cost) ──
function buildStepCostBlock(t) {
  const fsu = t.full_step_usage || {};
  const fsc = t.full_step_cost || {};
  const cd = t.cumulative_delta || {};
  const ud = t.unattributed_delta || {};
  const cs = t.cost_scope || {};
  const er = t.event_range || {};
  const reqCount = fsu.request_count || 0;

  const lines = [];
  if (reqCount === 0) {
    lines.push(kv("внутренних запросов", "0"));
    lines.push(kv("полная стоимость шага", "не рассчитана"));
    lines.push(kv("причина", "нет last_token_usage внутри шага"));
  } else if (reqCount === 1) {
    lines.push(kv("внутренних запросов модели", "1"));
    lines.push(kv("полная стоимость шага", moneyOrNA(fsc.total_usd)));
    lines.push('<div class="muted xsmall">Стоимость request-а совпадает с полной стоимостью шага.</div>');
    lines.push(kv("input (полный шаг)", numOrNA(fsu.input_tokens)));
    lines.push(kv("cached input", numOrNA(fsu.cached_tokens)));
    lines.push(kv("output", numOrNA(fsu.output_tokens)));
    lines.push(kv("reasoning", numOrNA(fsu.reasoning_tokens)));
  } else {
    lines.push(kv("внутренних запросов модели", nf.format(reqCount)));
    lines.push(kv("полная стоимость шага", moneyOrNA(fsc.total_usd)));
    lines.push('<div class="muted xsmall">Полная стоимость = сумма ' + reqCount + ' внутренних запросов.</div>');
    lines.push(kv("input (полный шаг)", numOrNA(fsu.input_tokens)));
    lines.push(kv("cached input", numOrNA(fsu.cached_tokens)));
    lines.push(kv("output", numOrNA(fsu.output_tokens)));
    lines.push(kv("reasoning", numOrNA(fsu.reasoning_tokens)));
    lines.push('<hr class="thin">');
    lines.push('<span class="muted xsmall">Для сравнения:</span>');
    lines.push(kv("стоимость осн. request-а", moneyOrNA(usageMoney(t.usage || {}, "estimated_total_cost_usd"))));
  }

  // Cumulative delta
  if (cd.available) {
    lines.push('<hr class="thin">');
    lines.push(kv("прирост счётчика (Δ)", numOrNA(cd.input_tokens) + " input"));
  }

  // Unattributed delta
  if (ud.available) {
    const udInput = ud.input_tokens;
    if (udInput != null && udInput !== 0) {
      lines.push(kv("неразнесённая разница", numWithSign(udInput) + " input"));
    } else {
      lines.push(kv("неразнесённая разница", "0 (всё разнесено)"));
    }
  }

  // Event range
  if (er.start_event_index) {
    lines.push(kv("диапазон событий", er.start_event_index + "–" + er.end_event_index + " (" + er.raw_events_count + ")"));
  }

  // Confidence
  lines.push(kv("scope", cs.current_displayed_cost_scope || "—"));
  lines.push(kv("confidence", cs.mapping_confidence || "—"));

  return lines.join("");
}

function buildStepExportData(step, session) {
  const usage = step?.usage || {};
  const environment = step?.environment || {};
  return {
    step_index: step?.step_index || 0,
    turn_id: step?.turn_id || "",
    timestamp: step?.timestamp || "",
    model: step?.model || "unknown",
    reasoning: {
      effort: step?.reasoning_effort || "unknown",
      output_tokens: usage.available === false ? null : (usage.reasoning_tokens ?? null),
    },
    prompt: {
      available: !!step?.user_prompt?.available,
      kind: step?.user_prompt?.kind || "user_message",
      text: step?.user_prompt?.available ? (step?.user_prompt?.text || "") : "",
    },
    answer: {
      available: !!step?.assistant_answer?.available,
      text: step?.assistant_answer?.available ? (step?.assistant_answer?.text || "") : "",
    },
    usage: {
      available: usage.available !== false,
      confirmation_status: usage.confirmation_status || (usage.available === false ? "missing_request_usage" : "confirmed_request_usage"),
      confirmation_label: usageConfirmationLabel(usage),
      source: usage.source || "",
      note: usage.note || "",
      input_tokens: usage.available === false ? null : (usage.input_tokens ?? null),
      cached_tokens: usage.available === false ? null : (usage.cached_tokens ?? null),
      non_cached_input_tokens: usage.available === false ? null : (usage.non_cached_input_tokens ?? null),
      cached_ratio: usage.available === false ? null : (usage.cached_ratio ?? null),
      output_tokens: usage.available === false ? null : (usage.output_tokens ?? null),
      reasoning_tokens: usage.available === false ? null : (usage.reasoning_tokens ?? null),
      tool_tokens: usage.available === false ? null : (usage.tool_tokens ?? null),
    },
    cost_breakdown: {
      confirmed: usage.available !== false && usage.estimated_total_cost_usd != null,
      total_usd: usage.estimated_total_cost_usd ?? null,
      input_usd: usage.estimated_input_cost_usd ?? null,
      cached_input_usd: usage.estimated_cached_input_cost_usd ?? null,
      output_usd: usage.estimated_output_cost_usd ?? null,
      note: "request-level cost (primary_request_usage); for full visible step cost see full_step_cost",
    },
    // v2.1: full step cost fields
    event_range: step.event_range || {},
    request_usage_items: step.request_usage_items || [],
    full_step_usage: step.full_step_usage || {},
    full_step_cost: step.full_step_cost || {},
    primary_request_usage: step.primary_request_usage || {},
    cumulative_before_step: step.cumulative_before_step || {},
    cumulative_after_step: step.cumulative_after_step || {},
    cumulative_delta: step.cumulative_delta || {},
    unattributed_delta: step.unattributed_delta || {},
    cost_scope: step.cost_scope || {},
    agent_activity: step.agent_activity || {},
    environment: {
      thread_id: environment.thread_id || "",
      cwd: environment.cwd || "",
      workspace_roots: environment.workspace_roots || [],
      current_date: environment.current_date || "",
      timezone: environment.timezone || "",
      approval_policy: environment.approval_policy || "",
      sandbox_policy: environment.sandbox_policy || "",
      permission_profile: environment.permission_profile || "",
      model_context_window: environment.model_context_window || 0,
      observed_mcp_server_count: environment.observed_mcp_server_count || 0,
      observed_mcp_servers: environment.observed_mcp_servers || [],
      enabled_plugins_count: environment.enabled_plugins_count || 0,
      enabled_skills_count: environment.enabled_skills_count || 0,
      repo_context_status: environment.repo_context_status || "",
      global_user_instructions_status: environment.global_user_instructions_status || "",
      task_turn_id: environment.task_turn_id || "",
    },
    warnings: buildTelemetryWarnings(session, step),
    compaction_timeline: buildTimelineContext(session, step),
    post_step_badges: step?.post_step_badges || [],
  };
}

function buildSessionExportJson(session, steps) {
  const src = currentSource();
  const selectedStepsList = steps || [];
  return {
    export_kind: "codex-token-monitor-session",
    source: {
      id: currentSourceId,
      name: src ? src.name : "",
      kind: session?.source_kind || "",
    },
    session: {
      id: session?.id || currentSessionId,
      title: session?.title || "",
      date: session?.date || "",
      model: session?.model || "",
      reasoning: session?.reasoning || "",
      workdir: session?.workdir || "",
      archived: !!session?.archived,
    },
    summary: session?.summary || {},
    warnings: buildTelemetryWarnings(session, null),
    timeline_events: session?.timeline_events || [],
    ai_calls: session?.ai_calls || [],
    ai_calls_count: session?.ai_calls_count || 0,
    ai_calls_with_usage_count: session?.ai_calls_with_usage_count || 0,
    ai_calls_zero_usage_count: session?.ai_calls_zero_usage_count || 0,
    ai_calls_unmapped_count: session?.ai_calls_unmapped_count || 0,
    ai_calls_honest_audit_summary: session?.ai_calls_honest_audit_summary || {},
    steps: selectedStepsList.map(step => buildStepExportData(step, session)),
  };
}

function buildSessionExportMarkdown(session, steps, title) {
  const data = buildSessionExportJson(session, steps);
  const models = [...new Set((steps || []).map(step => step.model).filter(Boolean))];
  const summary = data.summary || {};
  const lines = [
    `# ${title}`,
    "",
    "## Session",
    `- Source: ${data.source.name} (${data.source.kind || "unknown"})`,
    `- Source ID: ${data.source.id}`,
    `- Session ID: ${data.session.id}`,
    `- Title: ${data.session.title}`,
    `- Date: ${data.session.date}`,
    `- Workdir: ${data.session.workdir || "—"}`,
    `- Model(s): ${models.join(", ") || "—"}`,
    `- Steps exported: ${(steps || []).length}`,
    "",
    "## Summary",
    `- Total cost: ${summary.estimated_total_cost_usd == null ? "не подтверждено" : money(summary.estimated_total_cost_usd)}`,
    `- Total input: ${summary.total_input_tokens ?? "не подтверждено"}`,
    `- Total cached: ${summary.total_cached_tokens ?? "не подтверждено"}`,
    `- Total non-cached: ${summary.total_non_cached_input_tokens ?? "не подтверждено"}`,
    `- Cache ratio: ${summary.average_cached_ratio == null ? "не подтверждено" : pct(summary.average_cached_ratio)}`,
    `- Total output: ${summary.total_output_tokens ?? "не подтверждено"}`,
    `- Total reasoning: ${summary.total_reasoning_tokens ?? "не подтверждено"}`,
    `- Usage basis: ${summary.usage_basis || "—"}`,
    `- Step usage basis: ${summary.step_usage_basis || "—"}`,
    `- Visible steps: ${summary.visible_steps_count ?? summary.turn_count ?? "—"}`,
    `- Raw model requests: ${summary.raw_model_requests_count ?? "—"}`,
    `- Visible step full usage sum (input): ${summary.visible_step_full_usage_sum?.input_tokens ?? "—"}`,
    `- Unmapped/internal usage (input): ${summary.unmapped_or_internal_usage?.input_tokens ?? "—"}`,
    `- AI calls total: ${session.ai_calls_count ?? "—"} (with usage: ${session.ai_calls_with_usage_count ?? "—"}, zero: ${session.ai_calls_zero_usage_count ?? "—"}, unmapped: ${session.ai_calls_unmapped_count ?? "—"})`,
    `- AI calls cost: ${session.ai_calls_honest_audit_summary?.ai_calls_total_cost_usd != null ? money(session.ai_calls_honest_audit_summary.ai_calls_total_cost_usd) : "—"}`,
    "",
    "## Warnings",
    ...(data.warnings.length ? data.warnings.map(w => `- ${w}`) : ["- none"]),
  ];

  data.steps.forEach(step => {
    lines.push(
      "",
      `## Step ${step.step_index}`,
      `- Timestamp: ${step.timestamp || "—"}`,
      `- Turn ID: ${step.turn_id || "—"}`,
      `- Model: ${step.model}`,
      `- Reasoning effort: ${step.reasoning.effort}`,
      `- Usage confirmation: ${step.usage.confirmation_label}`,
      `- Usage source: ${step.usage.source || "—"}`,
      `- Usage note: ${step.usage.note || "—"}`,
      `- Request cost (primary request): ${step.cost_breakdown.total_usd == null ? "не подтверждено" : money(step.cost_breakdown.total_usd)}`,
      `- Full step cost: ${step.full_step_cost.total_usd == null ? "не рассчитано" : money(step.full_step_cost.total_usd)}`,
      `- Internal requests count: ${step.full_step_usage.request_count || 0}`,
      `- Cost scope: ${step.cost_scope.current_displayed_cost_scope || "—"} (confidence: ${step.cost_scope.mapping_confidence || "—"})`,
      "",
      "### Prompt",
      step.prompt.available ? step.prompt.text : "не доступен в источнике",
      "",
      "### Answer",
      step.answer.available ? step.answer.text : "не доступен в источнике",
      "",
      "### Usage",
      `- Input: ${step.usage.input_tokens ?? "не подтверждено"}`,
      `- Cached: ${step.usage.cached_tokens ?? "не подтверждено"}`,
      `- Non-cached: ${step.usage.non_cached_input_tokens ?? "не подтверждено"}`,
      `- Cache ratio: ${step.usage.cached_ratio == null ? "не подтверждено" : pct(step.usage.cached_ratio)}`,
      `- Output: ${step.usage.output_tokens ?? "не подтверждено"}`,
      `- Reasoning: ${step.usage.reasoning_tokens ?? "не подтверждено"}`,
      `- Tools: ${step.usage.tool_tokens ?? "не подтверждено"}`,
      "",
      "### Cost breakdown (request-level)",
      `- Total (request): ${step.cost_breakdown.total_usd == null ? "не подтверждено" : money(step.cost_breakdown.total_usd)}`,
      `- Input (request): ${step.cost_breakdown.input_usd == null ? "не подтверждено" : money(step.cost_breakdown.input_usd)}`,
      `- Cached input (request): ${step.cost_breakdown.cached_input_usd == null ? "не подтверждено" : money(step.cost_breakdown.cached_input_usd)}`,
      `- Output (request): ${step.cost_breakdown.output_usd == null ? "не подтверждено" : money(step.cost_breakdown.output_usd)}`,
      "",
      "### Full step cost",
      `- Internal requests: ${step.full_step_usage.request_count || 0}`,
      `- Full step total: ${step.full_step_cost.total_usd == null ? "не рассчитано" : money(step.full_step_cost.total_usd)}`,
      `- Full step input: ${step.full_step_usage.input_tokens == null ? "—" : nf.format(step.full_step_usage.input_tokens)}`,
      `- Full step cached: ${step.full_step_usage.cached_tokens == null ? "—" : nf.format(step.full_step_usage.cached_tokens)}`,
      `- Full step output: ${step.full_step_usage.output_tokens == null ? "—" : nf.format(step.full_step_usage.output_tokens)}`,
      `- Cost scope: ${step.cost_scope.current_displayed_cost_scope || "—"}`,
      `- Mapping confidence: ${step.cost_scope.mapping_confidence || "—"}`,
      `- Event range: ${step.event_range.start_event_index || 0}–${step.event_range.end_event_index || 0}`,
      `- Cumulative delta input: ${step.cumulative_delta.available ? (step.cumulative_delta.input_tokens != null ? nf.format(step.cumulative_delta.input_tokens) : "—") : "не доступен"}`,
      `- Unattributed delta input: ${step.unattributed_delta.available ? (step.unattributed_delta.input_tokens != null ? nf.format(step.unattributed_delta.input_tokens) : "—") : "не доступен"}`,
      "",
      "### Что делал агент",
      ...buildAgentActivityMarkdown(step),
      "",
      "### Environment",
      `- Thread ID: ${step.environment.thread_id || "—"}`,
      `- CWD: ${step.environment.cwd || "—"}`,
      `- Workspace roots: ${(step.environment.workspace_roots || []).join(", ") || "—"}`,
      `- Current date: ${step.environment.current_date || "—"}`,
      `- Timezone: ${step.environment.timezone || "—"}`,
      `- Approval policy: ${step.environment.approval_policy || "—"}`,
      `- Sandbox policy: ${step.environment.sandbox_policy || "—"}`,
      `- Permission profile: ${step.environment.permission_profile || "—"}`,
      `- Model context window: ${step.environment.model_context_window || "—"}`,
      `- MCP servers: ${(step.environment.observed_mcp_servers || []).join(", ") || "—"}`,
      `- Plugins count: ${step.environment.enabled_plugins_count || 0}`,
      `- Skills count: ${step.environment.enabled_skills_count || 0}`,
      `- Repo context: ${step.environment.repo_context_status || "—"}`,
      "",
      "### Step warnings",
      ...(step.warnings.length ? step.warnings.map(w => `- ${w}`) : ["- none"]),
      "",
      "### Compaction / timeline context",
      ...(step.compaction_timeline.length
        ? step.compaction_timeline.map(evt => `- ${evt.label} @ ${evt.timestamp || "—"} (task: ${evt.compaction_task_id || "—"})`)
        : ["- none"]),
    );
  });

  return lines.join("\n");
}

function buildStepExportText(step, session, options = {}) {
  return buildSessionExportMarkdown(session, [step], options.title || `Step ${step.step_index} export`);
}

function copyStepSummary(i) {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  const step = s.steps.find(t => t.step_index === i);
  if (!step) return;
  copyText(buildStepExportText(step, s));
}

let popupTab = 'timeline';
let popupSortCol = 'index';
let popupSortDir = 'asc';

function _sortHeader(label, col, i) {
  var arrow = '';
  if (popupSortCol === col) arrow = popupSortDir === 'asc' ? ' ▲' : ' ▼';
  return '<th style="text-align:left;padding:3px;cursor:pointer;user-select:none" onclick="if(popupSortCol===\''+col+'\'){popupSortDir=popupSortDir===\'asc\'?\'desc\':\'asc\'}else{popupSortCol=\''+col+'\';popupSortDir=\'asc\'};openStepPopup('+i+')">'+label+arrow+'</th>';
}

function _sortHeaderR(label, col, i) {
  var arrow = '';
  if (popupSortCol === col) arrow = popupSortDir === 'asc' ? ' ▲' : ' ▼';
  return '<th style="text-align:right;padding:3px;cursor:pointer;user-select:none" onclick="if(popupSortCol===\''+col+'\'){popupSortDir=popupSortDir===\'asc\'?\'desc\':\'asc\'}else{popupSortCol=\''+col+'\';popupSortDir=\'asc\'};openStepPopup('+i+')">'+label+arrow+'</th>';
}

function _sortHeaderC(label, col, i) {
  var arrow = '';
  if (popupSortCol === col) arrow = popupSortDir === 'asc' ? ' ▲' : ' ▼';
  return '<th style="text-align:center;padding:3px;cursor:pointer;user-select:none" onclick="if(popupSortCol===\''+col+'\'){popupSortDir=popupSortDir===\'asc\'?\'desc\':\'asc\'}else{popupSortCol=\''+col+'\';popupSortDir=\'asc\'};openStepPopup('+i+')">'+label+arrow+'</th>';
}

function openStepPopup(i) {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  const step = s.steps.find(t => t.step_index === i);
  if (!step) return;
  const aa = step.agent_activity || {};
  const u = step.usage || {};
  const fsc = step.full_step_cost || {};

  const tabs = ['timeline','stages','expensive','requests','filescmds','tech'];
  const labels = {'timeline':'Хронология','stages':'Этапы','expensive':'Дорогие','requests':'AI-запросы','filescmds':'Файлы и команды','tech':'Техника'};

  function tabBtn(t) {
    return '<button class="small" onclick="popupTab=\''+t+'\';openStepPopup('+i+')" style="'+(popupTab===t?'font-weight:bold;background:#3a3a3a;color:#fff':'color:#aaa')+'">'+labels[t]+'</button>';
  }

  var body = '<div style="max-height:70vh;overflow:auto">';

  if (popupTab === 'timeline') {
    body += buildPopupTimeline(aa, i);
  } else if (popupTab === 'stages') {
    body += buildPopupStages(aa);
  } else if (popupTab === 'expensive') {
    body += buildPopupExpensive(aa, step);
  } else if (popupTab === 'requests') {
    body += buildPopupRequests(step);
  } else if (popupTab === 'filescmds') {
    body += buildPopupFilesCmds(aa);
  } else {
    body += buildPopupTech(aa, step);
  }
  body += '</div>';

  var html = '<div id="stepPopupOverlay" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center" onclick="if(event.target===this)closeStepPopup()">';
  html += '<div style="background:#1e1e1e;color:#d4d4d4;border-radius:8px;width:95vw;max-width:1200px;max-height:90vh;padding:16px;box-shadow:0 4px 24px rgba(0,0,0,0.6);display:flex;flex-direction:column">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
  html += '<div><b>Step '+i+'</b> — '+escapeHtml(step.model)+' / '+escapeHtml(step.reasoning_effort)+'</div>';
  html += '<div style="font-weight:600">Полная стоимость: '+(fsc.total_usd!=null?'$'+Number(fsc.total_usd).toFixed(5):'—')+' | Запросов: '+(step.full_step_usage?.request_count||0)+'</div>';
  html += '<button onclick="closeStepPopup()" style="font-size:20px;border:none;background:none;cursor:pointer">✕</button>';
  html += '</div>';
  html += '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;border-bottom:1px solid #444;padding-bottom:8px">';
  tabs.forEach(function(t) { html += tabBtn(t); });
  html += '</div>';
  html += body;
  html += '</div></div>';

  var old = document.getElementById('stepPopupOverlay');
  if (old) old.remove();
  var div = document.createElement('div');
  div.innerHTML = html;
  document.body.appendChild(div.firstElementChild);
}

function closeStepPopup() {
  var el = document.getElementById('stepPopupOverlay');
  if (el) el.remove();
}

function buildPopupTimeline(aa, i) {
  var tl = aa.agent_timeline || {};
  var items = tl.items || [];
  if (!items.length) return '<div class="muted">Нет данных хронологии</div>';

  // Sort by current column
  var sorted = [...items];
  var col = popupSortCol || 'index';
  var dir = popupSortDir === 'desc' ? -1 : 1;
  sorted.sort(function(a, b) {
    var va, vb;
    if (col === 'index') { va = a.index || 0; vb = b.index || 0; }
    else if (col === 'cost') { va = (a.linked_cost||{}).total_usd || 0; vb = (b.linked_cost||{}).total_usd || 0; }
    else if (col === 'noncached') { va = (a.linked_request_usage||{}).non_cached_input_tokens || 0; vb = (b.linked_request_usage||{}).non_cached_input_tokens || 0; }
    else if (col === 'cached') { va = (a.linked_request_usage||{}).cached_tokens || 0; vb = (b.linked_request_usage||{}).cached_tokens || 0; }
    else if (col === 'output') { va = (a.linked_request_usage||{}).output_tokens || 0; vb = (b.linked_request_usage||{}).output_tokens || 0; }
    else if (col === 'reasoning') { va = (a.linked_request_usage||{}).reasoning_tokens || 0; vb = (b.linked_request_usage||{}).reasoning_tokens || 0; }
    else if (col === 'dt') {
      va = (a.duration||{}).seconds_since_previous_item || 0;
      vb = (b.duration||{}).seconds_since_previous_item || 0;
    }
    else { va = a.index || 0; vb = b.index || 0; }
    return (va - vb) * dir;
  });

  var h = '<div style="margin-bottom:4px;color:#aaa;font-size:10px">Нажми строку для подробностей. Заголовки сортируют. По умолчанию — хронология.</div>';

  h += '<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="background:#333">';
  h += _sortHeader('#','index',i);
  h += _sortHeader('Время','index',i);
  h += _sortHeader('Действие','action',i);
  h += _sortHeader('Объекты','objects',i);
  h += _sortHeaderC('AI','ai',i);
  h += _sortHeaderR('Cost','cost',i);
  h += _sortHeaderC('Увер.','conf',i);
  h += '</tr></thead><tbody>';
  sorted.forEach(function(it) {
    var itemId = 'tl-item-' + i + '-' + it.index;
    var lu = it.linked_request_usage || {};
    var lc = it.linked_cost || {};
    var dur = it.duration || {};
    var ts = it.timestamp ? new Date(it.timestamp).toLocaleTimeString('ru-RU') : '';
    var title = it.display_title_ru || it.recognized_action_ru || '';
    var fullTitle = it.full_title_ru || title;

    // Confidence badge
    var conf = it.recognition_confidence || it.confidence || 'low';
    var badge = '<span style="font-size:9px;padding:1px 4px;border-radius:3px;';
    if (conf === 'high') badge += 'background:#1a4a1a;color:#4f4">RAW</span>';
    else if (conf === 'low') badge += 'background:#4a4a1a;color:#cc4">APPROX</span>';
    else if (conf === 'not_verified') badge += 'background:#4a1a1a;color:#c44">?</span>';
    else badge += 'background:#333;color:#aaa">'+escapeHtml(conf)+'</span>';

    // Object label: short
    var objLabel = '';
    var files = it.files;
    var cmds = it.commands;
    if (files && files.length) {
      var firstFile = files[0];
      if (files.length === 1 && firstFile.read_count > 1) {
        objLabel = firstFile.display_name + ' — ' + firstFile.read_count + ' фрагментов';
      } else {
        objLabel = files.length + ' файл' + (files.length===1?'':'а');
      }
    }
    else if (cmds && cmds.length) objLabel = cmds.length + ' команд' + (cmds.length===1?'а':'');
    else objLabel = escapeHtml((it.object_label||'').substring(0,30));

    var rowStyle = 'cursor:pointer;';
    if (it.row_type === 'ai_call_only') rowStyle += 'color:#aaa;';
    if (it.row_type === 'action_only') rowStyle += 'color:#888;font-style:italic';

    h += '<tr class="tl-click-row" style="' + rowStyle + '" onclick="var was=this.classList.contains(\'tl-sel\');var all=document.querySelectorAll(\'.tl-sel\');all.forEach(function(r){r.classList.remove(\'tl-sel\')});if(!was){this.classList.add(\'tl-sel\')};var el=document.getElementById(\''+itemId+'\');el.style.display=el.style.display===\'none\'?\'table-row\':\'none\'" title="'+escapeHtml(fullTitle)+'">';
    h += '<td style="text-align:right;padding:2px 4px">'+it.index+'</td>';
    h += '<td style="padding:2px 4px;white-space:nowrap;font-size:11px">'+ts+'</td>';
    h += '<td style="padding:2px 4px">'+escapeHtml(title.substring(0,50))+'</td>';
    h += '<td style="padding:2px 4px;font-size:10px;color:#aaa">'+objLabel+'</td>';
    h += '<td style="text-align:center;padding:2px 4px;font-weight:600;font-size:11px">'+(it.linked_model_request_index?'#'+it.linked_model_request_index:'—')+'</td>';
    h += '<td style="text-align:right;padding:2px 4px;font-weight:600">'+(lc.total_usd!=null?'$'+Number(lc.total_usd).toFixed(5):'—')+'</td>';
    h += '<td style="text-align:center;padding:2px 4px">'+badge+'</td>';
    h += '</tr>';
    // Expandable details row
    h += '<tr id="'+itemId+'" class="tl-detail" style="display:none"><td colspan="7" style="padding:8px 12px;background:#252525;border-left:3px solid #4a4">';
    h += buildTimelineItemDetails(it);
    h += '</td></tr>';
  });
  h += '</tbody></table>';
  return h;
}

function buildTimelineItemDetails(it) {
  var h = '';
  var fullTitle = it.full_title_ru || it.display_title_ru || '';
  var lai = it.linked_ai_call;
  var lu = it.linked_request_usage || {};
  var lc = it.linked_cost || {};

  // ── Top: compact summary ──
  h += '<div style="font-weight:600;margin-bottom:4px">Этап #'+it.index+' — '+escapeHtml(fullTitle)+'</div>';
  h += '<div style="font-size:11px;margin-bottom:2px">';
  if (lai) h += 'AI: #'+lai.ai_index+' | ';
  h += 'Cost: '+(lc.total_usd!=null?'$'+Number(lc.total_usd).toFixed(5):'—');
  if (lu.available || lai) {
    h += ' | Нов.input: '+nf.format(lai?lai.non_cached_input_tokens:(lu.non_cached_input_tokens||0));
    h += ' | Cached: '+nf.format(lai?lai.cached_tokens:(lu.cached_tokens||0));
    h += ' | Output: '+nf.format(lai?lai.output_tokens:(lu.output_tokens||0));
    h += ' | Reasoning: '+nf.format(lai?lai.reasoning_tokens:(lu.reasoning_tokens||0));
  }
  h += ' | Уверенность: '+_humanConfLabel(it.recognition_confidence||it.confidence);
  h += '</div>';

  // ── Cost scope note ──
  if (lai) {
    h += '<div style="font-size:10px;color:#c09853;margin-bottom:6px">Стоимость этапа известна точно по telemetry AI #'+lai.ai_index+'. Отдельная стоимость файлов/команд недоступна. Ниже — вклад объектов в контекст этапа.</div>';
  }

  // ── v2.13: Context contribution: "Вклад файлов и команд в New input" ──
  var isServiceAction = (it.display_title_ru||'').indexOf('Обновил план') >= 0 || (it.display_title_ru||'').indexOf('Выполнил служебное') >= 0;
  var allObjects = [];
  (it.files||[]).forEach(function(f) { allObjects.push({kind:'file',obj:f,cc:f.context_contribution||{}}); });
  // Only include commands that are NOT file_read (they're already shown as files)
  (it.commands||[]).forEach(function(c) {
    if (c.classified_action !== 'file_read' && c.classified_action !== 'file_read_batch') {
      allObjects.push({kind:'command',obj:c,cc:c.context_contribution||{}});
    }
  });

  // v2.13: only show contribution table when there are real tool-output rows
  // and not for model_only / final_report without tool events
  var isFinalReport = it.row_type === 'ai_call_only' && (it.display_title_ru||'').indexOf('Сформулировал') >= 0;
  var isModelOnly = it.row_type === 'ai_call_only' && !isFinalReport;
  var hasRealObjects = allObjects.some(function(ao){ var cc=ao.cc; return cc.output_length_chars || cc.estimated_text_tokens; });

  if (hasRealObjects && allObjects.length > 0) {
    h += '<div style="font-weight:600;font-size:10px;margin-bottom:2px">Вклад файлов и команд в New input</div>';
    h += '<table style="width:100%;border-collapse:collapse;font-size:10px"><thead><tr style="background:#333">';
    h += '<th style="text-align:left;padding:2px 4px">Объект</th><th style="text-align:left;padding:2px 4px">Тип</th><th style="text-align:right;padding:2px 4px">Размер вывода</th><th style="text-align:right;padding:2px 4px">~Токенов текста tool-output</th><th style="text-align:right;padding:2px 4px">Доля tool-output</th><th style="text-align:right;padding:2px 4px">~New input tokens</th><th style="text-align:right;padding:2px 4px">~Вклад в New input cost</th><th style="text-align:center;padding:2px 4px">Copy</th>';
    h += '</tr></thead><tbody>';
    allObjects.forEach(function(ao) {
      var cc = ao.cc;
      var obj = ao.obj;
      var name = ao.kind==='file' ? (obj.display_name||obj.path||'?').split('\\').pop().split('/').pop() : (obj.command||'').substring(0,50);
      var full = ao.kind==='file' ? obj.path : obj.command;
      var type = ao.kind==='file' ? (obj.operation||'read') : (obj.classified_action||'cmd');
      if (ao.kind==='file' && obj.read_count > 1) {
        name += ' — ' + obj.read_count + ' фрагментов';
        if (obj.ranges && obj.ranges.length) {
          name += ' [' + obj.ranges.join(', ') + ']';
        }
      }
      var outLen = cc.output_length_chars;
      var estTok = cc.estimated_text_tokens;
      var share = cc.share_of_tool_output_text;
      var estCost = cc.estimated_new_input_cost_usd;

      // ~New input tokens = share * nc_tokens from token_cost_breakdown
      var tcb = it.token_cost_breakdown;
      var ncTokens = 0;
      if (tcb && tcb.available && tcb.items) {
        var ni = tcb.items.find(function(x){return x.kind==='new_input';});
        if (ni) ncTokens = ni.tokens || 0;
      }
      var estNITokens = (share != null && ncTokens > 0) ? Math.round(ncTokens * share) : null;

      h += '<tr>';
      h += '<td style="padding:1px 4px;font-family:monospace;font-size:9px" title="'+escapeHtml(full||'')+'">'+escapeHtml(name)+'</td>';
      h += '<td style="padding:1px 4px;color:#888;font-size:9px">'+escapeHtml(type)+'</td>';
      h += '<td style="text-align:right;padding:1px 4px">'+(outLen?nf.format(outLen):'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 4px">'+(estTok!=null?'~'+nf.format(estTok):'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 4px">'+(share!=null?Number(share*100).toFixed(0)+'%':'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 4px">'+(estNITokens!=null?'~'+nf.format(estNITokens):'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 4px;font-size:9px">'+(estCost!=null?'~$'+Number(estCost).toFixed(6):'—')+'</td>';
      h += '<td style="text-align:center;padding:1px 4px"><button class="small" onclick="event.stopPropagation();copyText(\''+escapeHtml(full||'').replace(/'/g,"\\'")+'\')" style="font-size:8px;padding:0 3px">Copy</button></td>';
      h += '</tr>';
    });
    h += '</tbody></table>';
    h += '<div style="font-size:9px;color:#888;margin-top:4px">Это оценка. Raw telemetry даёт точную стоимость только на уровне AI-call целиком. Cached, Output и Reasoning не распределяются по отдельным файлам/командам.</div>';
  } else if (isServiceAction) {
    h += '<div style="font-size:10px;color:#888">Это служебное действие Codex: обновление плана работы. Файлов и команд нет.</div>';
  } else if (it.row_type === 'ai_call_only' && (it.display_title_ru||'').indexOf('Сформулировал') >= 0) {
    var amd = it.assistant_message_data;
    h += '<div style="margin-top:4px;padding:6px 8px;background:#1a1a2e;border:1px solid #333;border-radius:4px">';
    h += '<div style="font-weight:600;font-size:10px;color:#7af">Финальный ответ агента</div>';
    if (amd && amd.available) {
      h += '<div style="font-size:9px;color:#888;margin-top:2px">'+escapeHtml(amd.cost_explanation_ru||'')+'</div>';
      if (amd.message_length_chars) h += '<div style="font-size:9px;margin-top:4px">Размер ответа: '+nf.format(amd.message_length_chars)+' симв.</div>';
      if (amd.message_text_location_ru) h += '<div style="font-size:9px;color:#888">'+escapeHtml(amd.message_text_location_ru)+'</div>';
      if (amd.source) h += '<div style="font-size:9px;color:#888">Источник: '+escapeHtml(amd.source)+' ('+escapeHtml(amd.source_confidence||'')+')</div>';
      if (amd.message_preview) {
        h += '<div style="margin-top:4px;font-size:9px;color:#888;max-height:120px;overflow-y:auto;white-space:pre-wrap;font-family:monospace">'+escapeHtml(amd.message_preview)+'</div>';
      }
    }
    h += '</div>';
  } else if (it.row_type === 'ai_call_only') {
    h += '<div style="margin-top:4px;padding:6px 8px;background:#1a1a2e;border:1px solid #333;border-radius:4px">';
    h += '<div style="font-weight:600;font-size:10px;color:#7af">Model-only AI-call</div>';
    h += '<div style="font-size:9px;color:#888;margin-top:2px">В raw telemetry нет прямых tool events для этого AI-обращения. Вероятно, модель анализировала уже загруженный контекст или формулировала следующий шаг.</div>';
    if (lai) {
      h += '<div style="font-size:9px;margin-top:2px">AI: #'+lai.ai_index+' | Cost: $'+Number(lc.total_usd||0).toFixed(5)+' | Нов.input: '+nf.format(lai.non_cached_input_tokens||0)+' | Cached: '+nf.format(lai.cached_tokens||0)+' | Output: '+nf.format(lai.output_tokens||0)+' | Reasoning: '+nf.format(lai.reasoning_tokens||0)+'</div>';
    }
    h += '</div>';
  } else {
    h += '<div style="font-size:10px;color:#888">Файлы: нет. Команды: нет.</div>';
  }

  // ── v2.10: apply_patch data ──
  var apd = it.apply_patch_data;
  if (apd && apd.available) {
    h += '<div style="margin-top:6px;padding:6px 8px;background:#1a1a2e;border:1px solid #333;border-radius:4px">';
    h += '<div style="font-weight:600;font-size:10px;margin-bottom:4px;color:#7af">Patch-действие и связанный AI cost</div>';
    // Files table
    if (it.files && it.files.length) {
      h += '<table style="font-size:10px;border-collapse:collapse;width:100%"><thead><tr style="background:#333">';
      h += '<th style="text-align:left;padding:2px 4px">Файл</th><th style="text-align:left;padding:2px 4px">Роль</th><th style="text-align:right;padding:2px 4px">Patch input</th><th style="text-align:right;padding:2px 4px">Tool output</th><th style="text-align:right;padding:2px 4px">AI cost</th>';
      h += '</tr></thead><tbody>';
      it.files.forEach(function(f) {
        var pic = apd.patch_input_chars;
        var ptok = apd.estimated_patch_tokens;
        var toc = apd.output_length;
        var ttok = apd.estimated_tool_output_tokens;
        h += '<tr>';
        h += '<td style="padding:1px 4px;font-family:monospace;font-size:9px">'+escapeHtml(f.display_name||f.path||'?')+'</td>';
        h += '<td style="padding:1px 4px;font-size:9px">'+escapeHtml(f.operation||'modified')+'</td>';
        h += '<td style="text-align:right;padding:1px 4px">'+(pic?nf.format(pic)+' симв. (~'+nf.format(ptok)+' ток.)':'—')+'</td>';
        h += '<td style="text-align:right;padding:1px 4px">'+(toc?nf.format(toc)+' симв. (~'+nf.format(ttok)+' ток.)':'—')+'</td>';
        h += '<td style="text-align:right;padding:1px 4px;font-weight:600">'+(lc.total_usd!=null?'$'+Number(lc.total_usd).toFixed(5):'—')+'</td>';
        h += '</tr>';
      });
      h += '</tbody></table>';
    }
    // Status
    if (apd.patch_status) {
      var stColor = apd.patch_status==='success'?'#4f4':(apd.patch_status==='failed'?'#c44':'#cc4');
      h += '<div style="margin-top:4px;font-size:10px">Статус: <span style="color:'+stColor+';font-weight:600">'+escapeHtml(apd.patch_status)+'</span></div>';
    }
    // Cost note
    h += '<div style="margin-top:4px;font-size:9px;color:#c09853">'+escapeHtml(apd.cost_note_ru||'')+'</div>';
    h += '</div>';
  }

  // ── v2.10: plan_update details ──
  var pud = it.plan_update_data;
  if (pud && pud.available) {
    h += '<div style="margin-top:6px;padding:6px 8px;background:#1a1a2e;border:1px solid #333;border-radius:4px">';
    h += '<div style="font-weight:600;font-size:10px;margin-bottom:4px;color:#7af">План работы</div>';
    h += '<div style="font-size:9px;color:#888;margin-bottom:4px">'+escapeHtml(pud.note_ru||'')+'</div>';
    if (pud.explanation) {
      h += '<div style="font-size:9px;color:#aaa;margin-bottom:4px">'+escapeHtml(pud.explanation)+'</div>';
    }
    if (pud.plan_items && pud.plan_items.length) {
      h += '<ol style="margin:0;padding-left:18px;font-size:9px;color:#aaa">';
      pud.plan_items.forEach(function(pi) {
        h += '<li>'+escapeHtml(String(pi))+'</li>';
      });
      h += '</ol>';
    }
    h += '</div>';
  }

  // ── Техническое (collapsed) ──
  var techId = 'tech-detail-'+it.index;
  h += '<div style="margin-top:6px"><button class="small" onclick="event.stopPropagation();var el=document.getElementById(\''+techId+'\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'" style="font-size:9px;padding:2px 6px">Техническое</button></div>';
  h += '<div id="'+techId+'" style="display:none;margin-top:4px;font-size:9px;color:#888">';
  // Show ALL commands including file_read in technical
  var allCmds = it.commands;
  if (allCmds && allCmds.length) {
    var hasReadCmds = allCmds.some(function(c){return c.classified_action==='file_read'||c.classified_action==='file_read_batch';});
    if (hasReadCmds) {
      h += '<div style="font-weight:600">Технические команды (чтение):</div>';
      allCmds.forEach(function(c) {
        if (c.classified_action==='file_read'||c.classified_action==='file_read_batch') {
          h += '<div style="font-size:8px;margin:1px 0"><span style="font-family:monospace">'+escapeHtml((c.command||'').substring(0,100))+'</span></div>';
        }
      });
    }
  }
  // v2.13: Token cost breakdown moved to technical block
  var tcb = it.token_cost_breakdown;
  if (tcb && tcb.available) {
    h += '<div style="font-weight:600;margin-top:6px">Расчёт стоимости по типам токенов:</div>';
    h += '<table style="width:100%;border-collapse:collapse;font-size:8px;margin-top:2px"><thead><tr style="background:#333">';
    h += '<th style="text-align:left;padding:1px 3px">Тип</th><th style="text-align:right;padding:1px 3px">Кол-во</th><th style="text-align:right;padding:1px 3px">$/1M</th><th style="text-align:right;padding:1px 3px">Стоимость</th>';
    h += '</tr></thead><tbody>';
    var items = tcb.items || [];
    for (var k = 0; k < items.length; k++) {
      var item = items[k];
      var kindLabel = item.kind === 'new_input' ? 'New input' : (item.kind === 'cached_input' ? 'Cached' : 'Output');
      h += '<tr>';
      h += '<td style="padding:1px 3px">' + kindLabel + '</td>';
      h += '<td style="text-align:right;padding:1px 3px">' + nf.format(item.tokens || 0) + '</td>';
      h += '<td style="text-align:right;padding:1px 3px">$' + Number(item.price_per_million || 0).toFixed(2) + '</td>';
      h += '<td style="text-align:right;padding:1px 3px">$' + Number(item.cost_usd || 0).toFixed(6) + '</td>';
      h += '</tr>';
    }
    h += '<tr style="border-top:1px solid #555"><td style="padding:1px 3px;font-weight:600">Итого</td><td></td><td></td><td style="text-align:right;padding:1px 3px;font-weight:600">$' + Number(tcb.total_from_breakdown_usd || 0).toFixed(6) + '</td></tr>';
    if (tcb.matched_model_key) h += '<tr><td colspan="4" style="font-size:8px;padding:1px 3px">Модель: ' + escapeHtml(tcb.matched_model_key) + ' · Источник: ' + escapeHtml(tcb.pricing_source||'—') + '</td></tr>';
    h += '</tbody></table>';
    h += '<div style="font-size:8px;margin-top:2px">' + escapeHtml(tcb.reasoning_note || '') + '</div>';
  }
  var rev = it.raw_evidence;
  if (rev && rev.length) {
    h += '<div style="font-weight:600;margin-top:4px">Raw evidence:</div>';
    rev.forEach(function(r) {
      h += '<div>event #'+r.event_index+' '+escapeHtml(r.payload_type||'')+' '+escapeHtml(r.call_id||'').substring(0,20)+'</div>';
    });
  }
  var details = it.details || {};
  if (details.available) {
    h += '<div style="margin-top:2px">'+escapeHtml(details.summary_ru||'')+'</div>';
  }
  h += '<div style="margin-top:4px"><button class="small" onclick="event.stopPropagation();copyText(JSON.stringify({index:it.index,title:fullTitle,confidence:it.recognition_confidence||it.confidence,linked_ai_call:lai},null,2))" style="font-size:9px;padding:2px 6px">Copy JSON</button></div>';
  h += '</div>';

  return h;
}

function buildPopupStages(aa) {
  var stages = aa.agent_activity_stages || [];
  if (!stages.length) return '<div class="muted">Нет данных этапов</div>';
  var h = '<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="background:#333">';
  h += '<th style="text-align:left;padding:4px">Этап</th><th style="text-align:right;padding:4px">Запросы</th><th style="text-align:right;padding:4px">Cost</th><th style="text-align:right;padding:4px">Input</th><th style="text-align:right;padding:4px">Output</th><th style="text-align:center;padding:4px">Увер.</th>';
  h += '</tr></thead><tbody>';
  stages.forEach(function(s) {
    h += '<tr><td style="padding:2px 4px">'+escapeHtml(s.title_ru)+'</td><td style="text-align:right;padding:2px 4px">'+(s.request_range||'')+'</td>';
    h += '<td style="text-align:right;padding:2px 4px;font-weight:600">$'+Number(s.cost_total_usd||0).toFixed(5)+'</td>';
    h += '<td style="text-align:right;padding:2px 4px">'+nf.format(s.input_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:2px 4px">'+nf.format(s.output_tokens||0)+'</td>';
    h += '<td style="text-align:center;padding:2px 4px;font-size:10px">'+escapeHtml(s.confidence||'low')+'</td></tr>';
  });
  h += '</tbody></table>';
  return h;
}

function buildPopupExpensive(aa, step) {
  // Prefer expensive_human_actions if available, fallback to step_internal_actions
  var eha = aa.expensive_human_actions || [];
  if (eha.length > 0) {
    var h = '<div style="font-weight:600;margin-bottom:4px">Самые дорогие действия</div>';
    h += '<table style="width:100%;border-collapse:collapse;font-size:11px"><thead><tr style="background:#333">';
    h += '<th style="text-align:right;padding:3px">#</th><th style="text-align:left;padding:3px">Действие</th><th style="text-align:center;padding:3px">AI</th><th style="text-align:right;padding:3px">Cost</th><th style="text-align:right;padding:3px">Нов.input</th><th style="text-align:right;padding:3px">Cached</th><th style="text-align:right;padding:3px">Output</th><th style="text-align:right;padding:3px">Reason</th><th style="text-align:left;padding:3px">Почему</th><th style="text-align:center;padding:3px">Увер.</th>';
    h += '</tr></thead><tbody>';
    eha.forEach(function(eh) {
      var confLabel = _humanConfLabel(eh.confidence);
      h += '<tr>';
      h += '<td style="text-align:right;padding:1px 3px">'+eh.index+'</td>';
      h += '<td style="padding:1px 3px">'+escapeHtml((eh.display_title_ru||'').substring(0,50))+'</td>';
      h += '<td style="text-align:center;padding:1px 3px;font-weight:600">'+(eh.linked_model_request_index?'#'+eh.linked_model_request_index:'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 3px;font-weight:600">'+(eh.total_usd!=null?'$'+Number(eh.total_usd).toFixed(5):'—')+'</td>';
      h += '<td style="text-align:right;padding:1px 3px">'+nf.format(eh.non_cached_input_tokens||0)+'</td>';
      h += '<td style="text-align:right;padding:1px 3px;color:#888">'+nf.format(eh.cached_tokens||0)+'</td>';
      h += '<td style="text-align:right;padding:1px 3px">'+nf.format(eh.output_tokens||0)+'</td>';
      h += '<td style="text-align:right;padding:1px 3px;color:#888">'+nf.format(eh.reasoning_tokens||0)+'</td>';
      h += '<td style="padding:1px 3px;font-size:10px">'+escapeHtml(eh.expensive_reason||'—')+'</td>';
      h += '<td style="text-align:center;padding:1px 3px;font-size:9px">'+confLabel+'</td>';
      h += '</tr>';
    });
    h += '</tbody></table>';
    return h;
  }
  // Fallback to old style with stage context
  var sia = aa.step_internal_actions || [];
  var costSorted = [...sia].sort(function(a,b){return (b.cost.total_usd||0)-(a.cost.total_usd||0);}).slice(0,15);
  if (!costSorted.length) return '<div class="muted">Нет данных</div>';
  var h = '<table style="width:100%;border-collapse:collapse;font-size:11px"><thead><tr style="background:#333">';
  h += '<th style="text-align:right;padding:3px">#</th><th style="text-align:left;padding:3px">Контекст этапа</th><th style="text-align:right;padding:3px">Cost</th><th style="text-align:right;padding:3px">Input</th><th style="text-align:right;padding:3px">Cached</th><th style="text-align:right;padding:3px">Output</th><th style="text-align:left;padding:3px">Почему</th>';
  h += '</tr></thead><tbody>';
  costSorted.forEach(function(a) {
    var c = a.cost || {};
    var u = a.usage || {};
    var displayName = (a.possible_stage_ru || a.title_ru || '').substring(0,45);
    h += '<tr><td style="text-align:right;padding:1px 3px">'+a.index+'</td>';
    h += '<td style="padding:1px 3px">'+escapeHtml(displayName)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px;font-weight:600">'+(c.total_usd!=null?'$'+Number(c.total_usd).toFixed(5):'—')+'</td>';
    h += '<td style="text-align:right;padding:1px 3px">'+nf.format(u.input_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px;color:#888">'+nf.format(u.cached_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px">'+nf.format(u.output_tokens||0)+'</td>';
    h += '<td style="padding:1px 3px;font-size:10px">'+escapeHtml(a.expensive_reason||'—')+'</td></tr>';
  });
  h += '</tbody></table>';
  return h;
}

function buildPopupRequests(step) {
  var sia = step.step_internal_actions || [];
  if (!sia.length) return '<div class="muted">Нет данных</div>';
  var h = '<table style="width:100%;border-collapse:collapse;font-size:11px"><thead><tr style="background:#333">';
  h += '<th style="text-align:right;padding:3px">#</th><th style="text-align:left;padding:3px">Контекст этапа</th><th style="text-align:right;padding:3px">Cost</th><th style="text-align:right;padding:3px">Input</th><th style="text-align:right;padding:3px">Non-cached</th><th style="text-align:right;padding:3px">Cached</th><th style="text-align:right;padding:3px">Output</th><th style="text-align:right;padding:3px">Reason</th>';
  h += '</tr></thead><tbody>';
  sia.forEach(function(a) {
    var u = a.usage || {};
    var c = a.cost || {};
    var displayName = (a.possible_stage_ru || a.title_ru || '').substring(0,45);
    h += '<tr><td style="text-align:right;padding:1px 3px">'+a.index+'</td>';
    h += '<td style="padding:1px 3px">'+escapeHtml(displayName)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px;font-weight:600">'+(c.total_usd!=null?'$'+Number(c.total_usd).toFixed(5):'—')+'</td>';
    h += '<td style="text-align:right;padding:1px 3px">'+nf.format(u.input_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px">'+nf.format(u.non_cached_input_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px;color:#888">'+nf.format(u.cached_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px">'+nf.format(u.output_tokens||0)+'</td>';
    h += '<td style="text-align:right;padding:1px 3px;color:#888">'+nf.format(u.reasoning_tokens||0)+'</td></tr>';
  });
  h += '</tbody></table>';
  return h;
}

function buildPopupFilesCmds(aa) {
  var paths = aa.important_paths || [];
  var cmds = aa.important_commands || [];
  var h = '';
  if (paths.length) {
    h += '<div style="font-weight:600;margin-bottom:4px">Файлы:</div><table style="width:100%;font-size:12px">';
    paths.forEach(function(p) { h += '<tr><td style="padding:2px 4px;font-family:monospace">'+escapeHtml(p)+'</td></tr>'; });
    h += '</table>';
  }
  if (cmds.length) {
    h += '<div style="font-weight:600;margin-top:12px;margin-bottom:4px">Команды:</div><table style="width:100%;font-size:12px">';
    cmds.forEach(function(c) { h += '<tr><td style="padding:2px 4px;font-family:monospace">'+escapeHtml(c)+'</td></tr>'; });
    h += '</table>';
  }
  if (!paths.length && !cmds.length) h = '<div class="muted">Нет данных</div>';
  return h;
}

function buildPopupTech(aa, step) {
  var ac = aa.activity_counts || {};
  var er = aa.event_range || {};
  var h = '<table style="font-size:12px">';
  h += '<tr><td style="padding:2px 8px">Внутренних запросов с usage:</td><td><b>'+nf.format(aa.requests_with_usage||0)+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Model-событий:</td><td><b>'+nf.format(aa.model_related_events||0)+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Сырых событий в шаге:</td><td><b>'+nf.format(er.raw_events_count||0)+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Диапазон событий:</td><td><b>'+(er.start_event_index||0)+'–'+(er.end_event_index||0)+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Распознано действий:</td><td><b>'+nf.format((ac.file_reads||0)+(ac.file_writes||0)+(ac.shell_commands||0)+(ac.git_operations||0)+(ac.test_runs||0)+(ac.context_compactions||0))+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Нераспознано:</td><td><b>'+nf.format(aa.unclassified_raw_events||0)+'</b></td></tr>';
  h += '<tr><td style="padding:2px 8px">Confidence:</td><td><b>'+escapeHtml(aa.confidence||'—')+'</b></td></tr>';
  h += '</table>';
  return h;
}

function copySessionSummary() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(buildSessionExportMarkdown(s, s.steps, "Session export"));
}

function copySessionJson() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(JSON.stringify(buildSessionExportJson(s, s.steps), null, 2));
}

function copySessionTable() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(buildSessionExportMarkdown(s, s.steps, "Session markdown export"));
}

function copySelectedSummary() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(buildSessionExportMarkdown(s, selectedSteps(), "Selected steps export"));
}

function copySelectedJson() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(JSON.stringify(buildSessionExportJson(s, selectedSteps()), null, 2));
}

function copySelectedTable() {
  const s = sessionDetailCache;
  if (!s || !s.steps) return;
  copyText(buildSessionExportMarkdown(s, selectedSteps(), "Selected steps export"));
}

function updateRawDownloadButtons() {
  const sessionButton = document.getElementById("rawSessionDownloadButton");
  const selectedButton = document.getElementById("rawSelectedDownloadButton");
  if (!sessionButton || !selectedButton) return;

  const available = sessionDetailCache?.raw_export_available === true;
  const unavailableReason = sessionDetailCache?.raw_export_unavailable_reason ||
    "Исходная телеметрия для этой сессии недоступна";
  sessionButton.disabled = !available;
  sessionButton.title = available ? "Скачать исходные rollout JSONL и manifest" : unavailableReason;

  const hasSelection = selected.size > 0;
  selectedButton.disabled = !available || !hasSelection;
  selectedButton.title = !available
    ? unavailableReason
    : (hasSelection
      ? "Скачать исходные rollout JSONL и manifest выбранных шагов"
      : "Сначала выделите шаги");
}

function downloadRawTelemetry(selectedOnly) {
  if (!currentSourceId || !currentSessionId || !sessionDetailCache) {
    showToast("Сначала выберите сессию");
    return;
  }
  if (sessionDetailCache.raw_export_available !== true) {
    showToast(sessionDetailCache.raw_export_unavailable_reason ||
      "Исходная телеметрия недоступна");
    return;
  }

  const params = new URLSearchParams();
  params.set("source_id", currentSourceId);
  params.set("session_id", currentSessionId);
  if (selectedOnly) {
    const stepIndices = [...selected].sort((a, b) => a - b);
    if (stepIndices.length === 0) {
      showToast("Сначала выделите шаги");
      return;
    }
    params.set("step_indices", stepIndices.join(","));
  }

  const link = document.createElement("a");
  link.href = "/api/raw-export?" + params.toString();
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

// ── Audit ──
let auditResultCache = null;
let auditLoading = false;

async function auditSession(selectedOnly) {
  if (!currentSourceId || !currentSessionId) {
    showToast("Сначала выберите сессию");
    return;
  }
  const stepIndices = selectedOnly ? [...selected].sort((a,b) => a-b) : null;
  if (selectedOnly && (!stepIndices || stepIndices.length === 0)) {
    showToast("Сначала выделите шаги (чекбоксами)");
    return;
  }
  auditLoading = true;
  auditResultCache = null;
  renderAuditPanel();
  const body = {
    source_id: currentSourceId,
    session_id: currentSessionId,
  };
  if (stepIndices && stepIndices.length > 0) {
    body.step_indices = stepIndices;
  }
  const data = await apiPost("/api/audit_session", body);
  auditResultCache = data;
  auditLoading = false;
  renderAuditPanel();
  if (data && data.audit_status) {
    showToast("Аудит: " + data.audit_status);
  } else if (data && data.error) {
    showToast("Ошибка: " + data.error);
  } else {
    showToast("Аудит: нет ответа от сервера");
  }
}

function auditStatusEmoji(status) {
  return status === "ok" ? "✅" : status === "warning" ? "⚠️" : status === "fail" ? "❌" : "❓";
}

function buildAuditSummaryRu(result, findings) {
  const r = result || {};
  const parts = [];
  const statusText = r.audit_status === "ok" ? "Всё в порядке" : r.audit_status === "warning" ? "Есть замечания" : "Обнаружены ошибки";

  parts.push(`<b>${statusText}.</b>`);

  // Evidence basis — most important truth signal
  if (r.evidence_basis === "verified_against_source_evidence") {
    parts.push("Аудит проверен по исходным данным (raw rollout/OTel).");
  } else if (r.evidence_basis === "detail_looked_plausible") {
    parts.push("Деталь внутренне непротиворечива, но исходные данные недоступны — статусы понижены.");
  } else if (r.evidence_basis === "not_verified") {
    parts.push("Аудит не смог проверить ключевые свойства — нет ни исходных данных, ни внутренних маркеров.");
  }

  // Audit scope
  if (r.audit_scope === "selected_steps") {
    parts.push(`Проверены только выбранные шаги (${r.audited_steps_count || "?"} из ${r.total_steps_in_session || "?"}) — это не полная проверка сессии.`);
  }

  if (r.usage_confirmation === "all_confirmed") {
    parts.push("Использование токенов подтверждено для всех проверенных шагов.");
  } else if (r.usage_confirmation === "partial") {
    const missingSteps = findings.filter(f => f.id === "step_usage_missing" || f.id === "step_usage_missing_unclear").length;
    parts.push(`Использование токенов подтверждено не для всех шагов (${missingSteps} шаг(ов) без подтверждённых данных).`);
  }

  if (r.fallback_used) {
    parts.push("Обнаружен fallback на общие (cumulative) данные вместо пошаговых.");
  }

  const mismatchF = findings.find(f => f.id === "summary_visible_step_mismatch");
  if (mismatchF) {
    parts.push("Общий итог сессии значительно больше суммы видимых шагов — это нормально для live-режима (в итог входят скрытые системные токены).");
  }

  if (r.cost_confidence === "estimated_from_cumulative") {
    parts.push("Стоимость посчитана от общей суммы токенов, а не от суммы шагов — точность ограничена.");
  }

  return parts.join(" ");
}

function renderAuditPanel() {
  const panel = document.getElementById("auditPanel");
  if (!panel) return;

  if (!sessionDetailCache) {
    panel.innerHTML = "";
    return;
  }

  if (auditLoading) {
    panel.innerHTML = `<div class="loading">Запуск аудита...</div>`;
    return;
  }

  const selCount = selected.size;
  const auditButtonsHtml = `
    <div class="audit-actions">
      <button class="ghost" onclick="auditSession(false)">🔍 Аудит сессии</button>
      ${selCount > 0 ? `<button class="ghost" onclick="auditSession(true)">🔍 Аудит выбранных (${selCount})</button>` : ""}
      ${auditResultCache ? `<button class="ghost" onclick="auditResultCache=null;renderAuditPanel()" title="Сбросить результат аудита">✕ Сбросить</button>` : ""}
    </div>`;

  if (!auditResultCache) {
    panel.innerHTML = auditButtonsHtml;
    return;
  }

  const r = auditResultCache;
  const findings = r.findings || [];
  const failCount = findings.filter(f => f.level === "fail").length;
  const warnCount = findings.filter(f => f.level === "warning").length;
  const okCount = findings.filter(f => f.level === "ok").length;

  let findingsHtml = "";
  if (findings.length === 0) {
    findingsHtml = `<div class="empty small">Все проверки пройдены</div>`;
  } else {
    findingsHtml = `<table class="audit-table"><thead><tr><th>Level</th><th>ID</th><th>Сообщение</th></tr></thead><tbody>`;
    findings.forEach(f => {
      findingsHtml += `<tr>
        <td>${auditStatusEmoji(f.level)} ${f.level}</td>
        <td class="mono xsmall">${escapeHtml(f.id || "")}</td>
        <td class="xsmall">${escapeHtml(f.message || "")}</td>
      </tr>`;
    });
    findingsHtml += `</tbody></table>`;
  }

  const collapseId = "audit-body";
  const scopeLabel = r.audit_scope === "selected_steps"
    ? ` (выбранные шаги: ${r.audited_steps_count || "?"} из ${r.total_steps_in_session || "?"})`
    : " (вся сессия)";

  panel.innerHTML = `
    <div class="audit-result">
      <div class="audit-header">
        <button class="ghost xsmall" onclick="toggleAuditCollapse()" id="auditCollapseBtn">▾</button>
        <b>Результат аудита${scopeLabel}</b>
        <span class="pill ${r.audit_status === 'ok' ? 'green' : r.audit_status === 'warning' ? 'yellow' : 'red'}">${auditStatusEmoji(r.audit_status)} ${r.audit_status}</span>
        <button class="ghost xsmall" onclick="auditSession(false)">🔄</button>
      </div>
      <div id="${collapseId}">
        <div class="audit-meta">
          <div class="cmini"><span>Evidence</span><b>${r.evidence_basis || "—"}</b></div>
          <div class="cmini"><span>Scope</span><b>${r.audit_scope || "—"}</b></div>
          <div class="cmini"><span>Usage</span><b>${r.usage_confirmation || "—"}</b></div>
          <div class="cmini"><span>Step attr.</span><b>${r.step_attribution_confidence || "—"}</b></div>
          <div class="cmini"><span>Cost conf.</span><b>${r.cost_confidence || "—"}</b></div>
          <div class="cmini"><span>Fallback</span><b>${r.fallback_used ? "да" : "нет"}</b></div>
        </div>
        <div class="audit-summary-ru">${buildAuditSummaryRu(r, findings)}</div>
        <div class="audit-counts">
          <span class="pill green">✅ ${okCount}</span>
          <span class="pill yellow">⚠️ ${warnCount}</span>
          <span class="pill red">❌ ${failCount}</span>
        </div>
        ${findingsHtml}
        ${buildCumulativeAccountingHtml(r)}
        ${r.report_path ? `<div class="audit-path mono xsmall">Отчёт: ${escapeHtml(r.report_path)}</div>` : ""}
      </div>
      ${auditButtonsHtml}
    </div>`;
}

function buildCumulativeAccountingHtml(r) {
  const rows = r.cumulative_accounting_rows || [];
  const sca = r.session_cumulative_accounting;
  if (!rows.length && !sca) return "";

  let html = '<div class="audit-cumulative">';
  html += '<div class="audit-section-title">📊 Cumulative Accounting</div>';

  if (rows.length) {
    html += '<table class="audit-table"><thead><tr><th>Step</th><th>request_usage</th><th>cumulative_after</th><th>cumulative_delta</th><th>unattributed_delta</th></tr></thead><tbody>';
    rows.forEach(row => {
      const req = fmtTokenDictShort(row.request_usage || {});
      const cum = fmtTokenDictShort(row.cumulative_usage_after_step || {});
      const delta = fmtTokenDictShort(row.cumulative_delta_since_previous_visible_step || {});
      const unattrib = fmtTokenDictShort(row.unattributed_delta || {});
      html += `<tr>
        <td>${row.step_index || "?"}</td>
        <td class="mono xsmall">${escapeHtml(req)}</td>
        <td class="mono xsmall">${escapeHtml(cum)}</td>
        <td class="mono xsmall">${escapeHtml(delta)}</td>
        <td class="mono xsmall">${escapeHtml(unattrib)}</td>
      </tr>`;
    });
    html += '</tbody></table>';
  }

  if (sca) {
    html += '<div class="audit-section-title xsmall">Session-Level</div>';
    html += `<div class="mono xsmall">session_total_usage: ${fmtTokenDictShort(sca.session_total_usage || {})}</div>`;
    html += `<div class="mono xsmall">request_usage_sum: ${fmtTokenDictShort(sca.visible_steps_request_usage_sum || {})}</div>`;
    html += `<div class="mono xsmall">delta_sum: ${fmtTokenDictShort(sca.visible_steps_cumulative_delta_sum || {})}</div>`;
    html += `<div class="mono xsmall">unattributed: ${fmtTokenDictShort(sca.unattributed_session_usage || {})}</div>`;
    if (sca.includes_hidden_context_possible) {
      html += '<div class="warning xsmall">⚠️ Видимые шаги покрывают менее 50% session total — возможен скрытый контекст</div>';
    }
  }

  html += '</div>';
  return html;
}

function buildCumulativeCostMetric(u) {
  const cumUsage = u.cumulative_usage_after_step || {};
  if (!cumUsage.available) return "";
  const cumCost = u.estimated_cumulative_cost_usd;
  if (cumCost == null) return "";
  return `<span class="metric"><span class="label" title="Cumulative cost after this step (total_token_usage)">Cumul. $</span><b>$${cumCost.toFixed(4)}</b></span>`;
}

function buildCumulativeInputMetric(u) {
  const cumUsage = u.cumulative_usage_after_step || {};
  if (!cumUsage.available) return "";
  const cumInput = cumUsage.input_tokens;
  if (cumInput == null || cumInput === 0) return "";
  return `<span class="metric"><span class="label" title="Cumulative input tokens after this step">Cumul. in</span><b>${nf.format(cumInput)}</b></span>`;
}

function fmtTokenDictShort(d) {
  if (!d || Object.keys(d).length === 0) return "—";
  const parts = [];
  for (const [k, v] of Object.entries(d)) {
    if (v === null || v === undefined) continue;
    if (typeof v === 'number') parts.push(`${k}=${v.toLocaleString()}`);
  }
  return parts.length ? parts.join(", ") : "—";
}

function toggleAuditCollapse() {
  const body = document.getElementById("audit-body");
  const btn = document.getElementById("auditCollapseBtn");
  if (!body || !btn) return;
  const collapsed = body.style.display === "none";
  body.style.display = collapsed ? "" : "none";
  btn.textContent = collapsed ? "▾" : "▸";
}

// ── Auto refresh ──
function toggleAutoRefresh() {
  autoRefresh = !autoRefresh;
  renderStatus();
  setupAutoRefresh();
}

function setupAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (autoRefresh && !stopped) {
    refreshTimer = setInterval(() => {
      refreshAll();
    }, 3000);
  }
}

// ── Controls collapse ──
function toggleControls() {
  const wrap = document.getElementById("controlsWrap");
  const btn = document.getElementById("collapseBtn");
  wrap.classList.toggle("collapsed");
  btn.textContent = wrap.classList.contains("collapsed") ? "▸" : "▾";
  localStorage.setItem("ctm_controls_collapsed", wrap.classList.contains("collapsed") ? "1" : "0");
}

// ── Resizer ──
function setupResizer() {
  const app = document.getElementById("app");
  const resizer = document.getElementById("resizer");
  let dragging = false;
  resizer.addEventListener("mousedown", () => {
    dragging = true;
    document.body.style.userSelect = "none";
  });
  window.addEventListener("mousemove", e => {
    if (!dragging) return;
    const w = Math.max(280, Math.min(620, e.clientX));
    app.style.setProperty("--left-width", w + "px");
    localStorage.setItem("ctm_left_width", String(w));
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.userSelect = "";
  });
}

async function applySessionFilters() {
  const previousSessionId = currentSessionId;
  renderSessions();
  renderSourceInfo();
  if (currentSessionId !== previousSessionId) {
    selected.clear();
    sessionDetailCache = null;
    sessionDetailLoading = true;
    auditResultCache = null;
    renderAll();
    await loadSessionDetail();
    renderAll();
    return;
  }
  renderHeader();
  renderSteps();
  renderSelection();
}

function renderHeader() {
  const s = sessionDetailCache;
  if (!s) {
    document.getElementById("title").textContent = "Выберите сессию";
    const selectedSession = currentSession();
    document.getElementById("title").textContent = selectedSession && sessionDetailLoading
      ? "Загрузка сессии..."
      : document.getElementById("title").textContent;
    document.getElementById("meta").textContent = selectedSession ? selectedSession.title : "";
    document.getElementById("stats").innerHTML = "";
    return;
  }
  const z = metricsForSession(s);
  const src = currentSource();
  const sourceKind = s.source_kind || "archive";
  const kindLabel = sourceKind === "live" ? "live" : "архив";
  const hasAmbiguousLiveSteps = sourceKind === "live" && (s.steps || []).some(t => t?.usage?.available === false);
  const usageNote = hasAmbiguousLiveSteps ? " · часть шагов без точной per-step разбивки" : "";

  document.getElementById("title").textContent = s.title;
  document.getElementById("meta").textContent = `${src ? src.name : ""} [${kindLabel}] · ${s.id} · ${s.date} · ${s.workdir}${usageNote}`;
  document.getElementById("stats").innerHTML = [
    stat("Cost", money(z.cost), "good"),
    stat("Input", nf.format(z.input), "blue"),
    stat("Cached", nf.format(z.cached), "good"),
    stat("Non-cached", nf.format(z.non), "warn"),
    stat("Cache", pct(z.ratio), "blue"),
    stat("Output", nf.format(z.output)),
  ].join("");
}

function renderSessions() {
  const list = filteredSessions();
  const root = document.getElementById("sessions");
  document.getElementById("sessionCount").textContent = `${list.length}/${sessionsCache.length}`;
  document.getElementById("archivedToggleBtn").style.borderColor = showArchived ? "rgba(124,156,255,.75)" : "";
  root.innerHTML = "";

  if (!list.length) {
    root.innerHTML = `<div class="empty small">Нет подходящих сессий</div>`;
    return;
  }

  if (!list.find(s => s.id === currentSessionId)) currentSessionId = preferredSessionId(list);

  list.forEach(s => {
    const costText = s.total_cost_usd == null ? "—" : money(s.total_cost_usd);
    const stepText = s.step_count == null ? "—" : nf.format(s.step_count);
    const el = document.createElement("div");
    const sourceKind = s.source_kind || "archive";
    const badgeCls = sourceKind === "live" ? "green" : "purple";
    const sourceLabel = sourceKind === "live" ? "live" : "архив";
    const cbadges = (s.confirmation_badges || []).map(b => `<span class="pill yellow">${b}</span>`).join("");

    el.className = "session" + (s.id === currentSessionId ? " active" : "");
    el.onclick = async () => {
      currentSessionId = s.id;
      selected.clear();
      expandedSteps.clear();
      openTextBlocks.clear();
      sessionDetailCache = null;
      sessionDetailLoading = true;
      renderAll();
      await loadSessionDetail();
      renderAll();
    };
    el.innerHTML = `
      <div class="session-head">
        <div>
          <div class="session-title">${escapeHtml(s.title)}</div>
          <div class="session-id muted xsmall mono">${escapeHtml(s.id)}</div>
          <div class="session-date">${escapeHtml(formatSessionDate(s))}</div>
        </div>
        <div class="row-actions">
          <button class="icon ghost" title="Архивировать/Вернуть" onclick="event.stopPropagation();toggleArchive('${s.id}')">🗄</button>
          <span class="pill blue">${stepText}</span>
        </div>
      </div>
      <div class="pills">
        <span class="pill ${badgeCls}">${sourceLabel}</span>
        <span class="pill">${escapeHtml(s.model)}</span>
        <span class="pill purple">${escapeHtml(s.reasoning)}</span>
        <span class="pill ${s.warnings_count ? 'yellow' : 'green'}">${s.warnings_count} warn</span>
        ${cbadges}
        ${s.has_normalized ? '<span class="pill green">normalized</span>' : (s.has_parsed ? '<span class="pill">parsed</span>' : '')}
      </div>
      <div class="compact-metrics">
        <div class="cmini"><span>Cost</span><b>${costText}</b></div>
        <div class="cmini"><span>Steps</span><b>${stepText}</b></div>
        <div class="cmini"><span>Model</span><b>${escapeHtml(s.model)}</b></div>
      </div>`;
    root.appendChild(el);
  });
}

function renderSteps() {
  const root = document.getElementById("steps");
  root.innerHTML = "";
  const s = sessionDetailCache;
  if (!s) {
    root.innerHTML = `<div class="loading">${currentSession() && sessionDetailLoading ? "Загрузка шагов..." : "Выберите сессию слева"}</div>`;
    return;
  }
  if (!s.steps || !s.steps.length) {
    root.innerHTML = `<div class="loading">Для этой сессии шаги пока не найдены</div>`;
    return;
  }

  const sourceKind = s.source_kind || "archive";
  const hasAmbiguousLiveSteps = sourceKind === "live" && s.steps.some(t => t?.usage?.available === false);
  const usageWarning = hasAmbiguousLiveSteps
    ? `<div class="empty small" style="margin-bottom:8px">⚠ Для части live-шагов точная per-step разбивка не подтверждена. В таких местах смотри totals всей сессии.</div>`
    : "";

  if (usageWarning) {
    const warnEl = document.createElement("div");
    warnEl.innerHTML = usageWarning;
    root.appendChild(warnEl);
  }

  const timelineByStep = new Map();
  (s.timeline_events || []).forEach(evt => {
    const key = Number(evt.after_step_index || 0);
    if (!timelineByStep.has(key)) timelineByStep.set(key, []);
    timelineByStep.get(key).push(evt);
  });

  s.steps.forEach(t => {
    const el = document.createElement("div");
    const idx = t.step_index;
    el.className = "step" + (selected.has(idx) ? " selected" : "");
    el.id = "step-" + idx;
    const u = t.usage || {};
    const env = t.environment || {};
    const usageAvail = u.available !== false;
    const usageNote = (!usageAvail && u.note) ? `<span class="muted xsmall"> (${u.note})</span>` : "";
    const postBadges = (t.post_step_badges || []).map(b => `<span class="pill yellow">${escapeHtml(b)}</span>`).join("");

    el.innerHTML = `
      <div class="step-head" onclick="toggleDetails(${idx})">
        <input type="checkbox" ${selected.has(idx) ? "checked" : ""} onclick="event.stopPropagation()" onchange="toggleSelect(${idx})">
        <div>
          <div class="step-title">
            <b>Step ${idx}</b>
            <span class="pill blue">${escapeHtml(t.model)}</span>
            <span class="pill purple">${escapeHtml(t.reasoning_effort)}</span>
            ${usageAvail ? '' : '<span class="pill yellow" title="Для этого шага нет подтвержденной per-step token delta">usage⚠</span>'}
            <span class="pill ${(t.warnings || []).length ? 'yellow' : 'green'}">${(t.warnings || []).length} warn</span>
            ${postBadges}
          </div>
          <div class="metrics">
            ${metric("Cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${metric("Input", usageNumber(u, "input_tokens"))}
            ${metric("Cached", usageNumber(u, "cached_tokens"))}
            ${metric("Non-cached", usageNumber(u, "non_cached_input_tokens"))}
            ${metric("Cache", usagePercent(u, "cached_ratio"))}
            ${metric("Output", usageNumber(u, "output_tokens"))}
            ${metric("Reasoning", usageNumber(u, "reasoning_tokens"))}
            ${metric("MCP", nf.format(env.observed_mcp_server_count))}
          </div>
          <div class="preview-row">
            <div class="preview">
              <span class="label">${t.user_prompt.kind === 'system_composed' ? 'System prompt' : 'Prompt'}</span>
              <div class="text">${t.user_prompt.available ? escapeHtml(ellipsis(t.user_prompt.text, 90)) : "—"}</div>
            </div>
            <div class="preview">
              <span class="label">Answer</span>
              <div class="text">${t.assistant_answer.available ? escapeHtml(ellipsis(t.assistant_answer.text, 90)) : "—"}</div>
            </div>
          </div>
        </div>
        <div class="row-actions">
          <button class="icon" onclick="event.stopPropagation();openStepPopup(${idx})">Подробно</button>
          <button class="icon" onclick="event.stopPropagation();copyStepSummary(${idx})">Copy</button>
        </div>
      </div>
      <div class="detail">
        ${textBlock(t.user_prompt.kind === 'system_composed' ? "System prompt (composed)" : "User prompt", "prompt", t.user_prompt.available, t.user_prompt.text, idx)}
        ${textBlock("Assistant answer", "answer", t.assistant_answer.available, t.assistant_answer.text, idx)}
        <div class="detail-grid">
          <div class="box">
            <h3>Tokens${usageNote}</h3>
            ${kv("input_tokens", usageNumber(u, "input_tokens"))}
            ${kv("cached_tokens", usageNumber(u, "cached_tokens"))}
            ${kv("non_cached", usageNumber(u, "non_cached_input_tokens"))}
            ${kv("cached_ratio", usagePercent(u, "cached_ratio"))}
            ${kv("output_tokens", usageNumber(u, "output_tokens"))}
            ${kv("reasoning_tokens", usageNumber(u, "reasoning_tokens"))}
            ${kv("tool_tokens", usageNumber(u, "tool_tokens"))}
          </div>
          <div class="box">
            <h3>Cost</h3>
            ${kv("input_cost", usageMoney(u, "estimated_input_cost_usd"))}
            ${kv("cached_cost", usageMoney(u, "estimated_cached_input_cost_usd"))}
            ${kv("output_cost", usageMoney(u, "estimated_output_cost_usd"))}
            ${kv("total_cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${kv("pricing", "config/token_pricing.json")}
          </div>
          <div class="box">
            <h3>Environment</h3>
            ${kv("thread_id", env.thread_id)}
            ${kv("turn_id", t.turn_id)}
            ${kv("MCP servers", (env.observed_mcp_servers || []).join(", ") || "none")}
            ${kv("plugins_count", env.enabled_plugins_count)}
            ${kv("skills_count", env.enabled_skills_count)}
            ${kv("repo_context", env.repo_context_status)}
            ${kv("warnings", (t.warnings || []).join(", ") || "none")}
          </div>
        </div>
      </div>`;
    root.appendChild(el);

    const extraEvents = timelineByStep.get(Number(idx)) || [];
    extraEvents.forEach(evt => {
      const wrap = document.createElement("div");
      wrap.innerHTML = renderTimelineEvent(evt);
      root.appendChild(wrap.firstElementChild);
    });
  });
}

function renderHeader() {
  const s = sessionDetailCache;
  if (!s) {
    document.getElementById("title").textContent = "Выберите сессию";
    const selectedSession = currentSession();
    document.getElementById("title").textContent = selectedSession && sessionDetailLoading
      ? "Загрузка сессии..."
      : document.getElementById("title").textContent;
    document.getElementById("meta").textContent = selectedSession ? selectedSession.title : "";
    document.getElementById("stats").innerHTML = "";
    return;
  }

  const z = metricsForSession(s);
  const src = currentSource();
  const sourceKind = s.source_kind || "archive";
  const kindLabel = sourceKind === "live" ? "live" : "архив";
  const hasAmbiguousLiveSteps = sourceKind === "live" && (s.steps || []).some(t => t?.usage?.available === false);
  const usageNoteParts = [];
  if (sourceKind === "live" && (s.summary?.usage_basis || s.summary?.step_usage_basis)) {
    usageNoteParts.push("live totals = cumulative, step usage = request-level");
  }
  if (hasAmbiguousLiveSteps) {
    usageNoteParts.push("часть шагов без точной per-step разбивки");
  }
  const usageNote = usageNoteParts.length ? ` · ${usageNoteParts.join(" · ")}` : "";

  document.getElementById("title").textContent = s.title;
  document.getElementById("meta").textContent = `${src ? src.name : ""} [${kindLabel}] · ${s.id} · ${s.date} · ${s.workdir}${usageNote}`;
  document.getElementById("stats").innerHTML = [
    stat("Cost", money(z.cost), "good"),
    stat("Input", nf.format(z.input), "blue"),
    stat("Cached", nf.format(z.cached), "good"),
    stat("Non-cached", nf.format(z.non), "warn"),
    stat("Cache", pct(z.ratio), "blue"),
    stat("Output", nf.format(z.output)),
  ].join("");
}

function renderSteps() {
  const root = document.getElementById("steps");
  root.innerHTML = "";
  const s = sessionDetailCache;
  if (!s) {
    root.innerHTML = `<div class="loading">${currentSession() && sessionDetailLoading ? "Загрузка шагов..." : "Выберите сессию слева"}</div>`;
    return;
  }
  if (!s.steps || !s.steps.length) {
    root.innerHTML = `<div class="loading">Для этой сессии шаги пока не найдены</div>`;
    return;
  }

  const sourceKind = s.source_kind || "archive";
  const hasAmbiguousLiveSteps = sourceKind === "live" && s.steps.some(t => t?.usage?.available === false);
  const summaryWarnings = buildTelemetryWarnings(s, null);
  const usageWarning = hasAmbiguousLiveSteps
    ? `<div class="empty small" style="margin-bottom:8px">⚠ Для части live-шагов точная per-step разбивка не подтверждена. В таких местах смотри totals всей сессии.</div>`
    : "";
  const telemetryWarning = summaryWarnings.length
    ? `<div class="empty small" style="margin-bottom:8px">${summaryWarnings.map(w => `⚠ ${escapeHtml(w)}`).join("<br>")}</div>`
    : "";

  if (usageWarning) {
    const warnEl = document.createElement("div");
    warnEl.innerHTML = usageWarning;
    root.appendChild(warnEl);
  }
  if (telemetryWarning) {
    const telemetryEl = document.createElement("div");
    telemetryEl.innerHTML = telemetryWarning;
    root.appendChild(telemetryEl);
  }

  const timelineByStep = new Map();
  (s.timeline_events || []).forEach(evt => {
    const key = Number(evt.after_step_index || 0);
    if (!timelineByStep.has(key)) timelineByStep.set(key, []);
    timelineByStep.get(key).push(evt);
  });

  s.steps.forEach(t => {
    const el = document.createElement("div");
    const idx = t.step_index;
    el.className = "step" + (selected.has(idx) ? " selected" : "");
    el.id = "step-" + idx;
    const u = t.usage || {};
    const env = t.environment || {};
    const usageAvail = u.available !== false;
    const usageNote = (!usageAvail && u.note) ? `<span class="muted xsmall"> (${u.note})</span>` : "";
    const postBadges = (t.post_step_badges || []).map(b => `<span class="pill yellow">${escapeHtml(b)}</span>`).join("");

    el.innerHTML = `
      <div class="step-head" onclick="toggleDetails(${idx})">
        <input type="checkbox" ${selected.has(idx) ? "checked" : ""} onclick="event.stopPropagation()" onchange="toggleSelect(${idx})">
        <div>
          <div class="step-title">
            <b>Step ${idx}</b>
            <span class="pill blue">${escapeHtml(t.model)}</span>
            <span class="pill purple">${escapeHtml(t.reasoning_effort)}</span>
            ${usageAvail ? '' : '<span class="pill yellow" title="Для этого шага нет подтвержденной per-step token delta">usage⚠</span>'}
            <span class="pill ${(t.warnings || []).length ? 'yellow' : 'green'}">${(t.warnings || []).length} warn</span>
            ${postBadges}
          </div>
          <div class="metrics">
            ${metric("Cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${buildCumulativeCostMetric(u)}
            ${metric("Input", usageNumber(u, "input_tokens"))}
            ${buildCumulativeInputMetric(u)}
            ${metric("Cached", usageNumber(u, "cached_tokens"))}
            ${metric("Non-cached", usageNumber(u, "non_cached_input_tokens"))}
            ${metric("Cache", usagePercent(u, "cached_ratio"))}
            ${metric("Output", usageNumber(u, "output_tokens"))}
            ${metric("Reasoning", usageNumber(u, "reasoning_tokens"))}
            ${metric("MCP", nf.format(env.observed_mcp_server_count))}
          </div>
          <div class="preview-row">
            <div class="preview">
              <span class="label">${t.user_prompt.kind === 'system_composed' ? 'System prompt' : 'Prompt'}</span>
              <div class="text">${t.user_prompt.available ? escapeHtml(ellipsis(t.user_prompt.text, 90)) : "—"}</div>
            </div>
            <div class="preview">
              <span class="label">Answer</span>
              <div class="text">${t.assistant_answer.available ? escapeHtml(ellipsis(t.assistant_answer.text, 90)) : "—"}</div>
            </div>
          </div>
        </div>
        <div class="row-actions">
          <button class="icon" onclick="event.stopPropagation();openStepPopup(${idx})">Подробно</button>
          <button class="icon" onclick="event.stopPropagation();copyStepSummary(${idx})">Copy</button>
        </div>
      </div>
      <div class="detail">
        ${textBlock(t.user_prompt.kind === 'system_composed' ? "System prompt (composed)" : "User prompt", "prompt", t.user_prompt.available, t.user_prompt.text, idx)}
        ${textBlock("Assistant answer", "answer", t.assistant_answer.available, t.assistant_answer.text, idx)}
        ${wideBlock("Сводка", "summary", buildStepSummaryBlock(t), idx)}
        <div class="detail-grid">
          <div class="box">
            <h3>Tokens${usageNote}</h3>
            ${kv("input_tokens", usageNumber(u, "input_tokens"))}
            ${kv("cached_tokens", usageNumber(u, "cached_tokens"))}
            ${kv("non_cached", usageNumber(u, "non_cached_input_tokens"))}
            ${kv("cached_ratio", usagePercent(u, "cached_ratio"))}
            ${kv("output_tokens", usageNumber(u, "output_tokens"))}
            ${kv("reasoning_tokens", usageNumber(u, "reasoning_tokens"))}
            ${kv("tool_tokens", usageNumber(u, "tool_tokens"))}
            <hr class="thin">
            ${kv("cumul_input", usageNumber((u.cumulative_usage_after_step || {}), "input_tokens"))}
            ${kv("cumul_cached", usageNumber((u.cumulative_usage_after_step || {}), "cached_tokens"))}
            ${kv("cumul_output", usageNumber((u.cumulative_usage_after_step || {}), "output_tokens"))}
            <hr class="thin">
            ${kv("confirmation", usageConfirmationLabel(u))}
            ${kv("source", u.source || "—")}
          </div>
          <div class="box">
            <h3>Cost</h3>
            ${kv("input_cost", usageMoney(u, "estimated_input_cost_usd"))}
            ${kv("cached_cost", usageMoney(u, "estimated_cached_input_cost_usd"))}
            ${kv("output_cost", usageMoney(u, "estimated_output_cost_usd"))}
            ${kv("total_cost", usageMoney(u, "estimated_total_cost_usd"))}
            ${kv("cumulative_cost", usageMoney(u, "estimated_cumulative_cost_usd"))}
            ${kv("pricing", "config/token_pricing.json")}
          </div>
          <div class="box">
            <h3>Environment</h3>
            ${kv("thread_id", env.thread_id)}
            ${kv("cwd", env.cwd || "—")}
            ${kv("timezone", env.timezone || "—")}
            ${kv("approval_policy", env.approval_policy || "—")}
            ${kv("sandbox_policy", env.sandbox_policy || "—")}
            ${kv("permission_profile", env.permission_profile || "—")}
            ${kv("model_context_window", env.model_context_window || "—")}
            ${kv("turn_id", t.turn_id)}
            ${kv("MCP servers", (env.observed_mcp_servers || []).join(", ") || "none")}
            ${kv("plugins_count", env.enabled_plugins_count)}
            ${kv("skills_count", env.enabled_skills_count)}
            ${kv("repo_context", env.repo_context_status)}
            ${kv("warnings", buildTelemetryWarnings(s, t).join(" | ") || "none")}
          </div>
        </div>
      </div>`;
    root.appendChild(el);

    const extraEvents = timelineByStep.get(Number(idx)) || [];
    extraEvents.forEach(evt => {
      const wrap = document.createElement("div");
      wrap.innerHTML = renderTimelineEvent(evt);
      root.appendChild(wrap.firstElementChild);
    });
  });

  // Restore expanded step details after re-render (auto-refresh)
  expandedSteps.forEach(i => {
    const el = document.getElementById("step-" + i);
    if (el) el.classList.add("open");
  });
  // Restore open text blocks (prompt, answer, stepcost, activity)
  openTextBlocks.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.add("open");
  });
}

// ── Event listeners ──
document.getElementById("sourceSelect").addEventListener("change", async e => {
  currentSourceId = e.target.value;
  currentWorkdirFilter = ALL_WORKDIRS_VALUE;
  localStorage.removeItem("ctm_workdir_filter");
  currentSessionId = "";
  selected.clear();
  await refreshAll();
});

document.getElementById("workdirFilter").addEventListener("change", async e => {
  currentWorkdirFilter = normalizeWorkdir(e.target.value || "");
  localStorage.setItem("ctm_workdir_filter", currentWorkdirFilter);
  await applySessionFilters();
});

document.getElementById("q").addEventListener("input", async () => {
  await applySessionFilters();
});

document.getElementById("modelFilter").addEventListener("change", async () => {
  await applySessionFilters();
});
document.getElementById("riskFilter").addEventListener("change", async () => {
  await applySessionFilters();
});
document.getElementById("sortFilter").addEventListener("change", async e => {
  localStorage.setItem("ctm_sort_mode", e.target.value);
  await applySessionFilters();
});

// ── Init ──
function loadUIState() {
  showArchived = localStorage.getItem("ctm_show_archived") === "1";
  const collapsed = localStorage.getItem("ctm_controls_collapsed") === "1";
  if (collapsed) {
    document.getElementById("controlsWrap").classList.add("collapsed");
    document.getElementById("collapseBtn").textContent = "▸";
  }
  const left = localStorage.getItem("ctm_left_width");
  if (left) document.getElementById("app").style.setProperty("--left-width", left + "px");
  const sort = localStorage.getItem("ctm_sort_mode");
  if (sort) {
    const sortEl = document.getElementById("sortFilter");
    if (sortEl) sortEl.value = sort;
  }
  currentWorkdirFilter = normalizeWorkdir(localStorage.getItem("ctm_workdir_filter") || "");
}

async function init() {
  loadUIState();
  setupResizer();
  setupAutoRefresh();
  initSources();
  await refreshAll();
}

function renderAiCallsSectionIntoSteps(root, session) {
  if (!root || !session || !session.ai_calls || !session.ai_calls.length) return;
  if (root.querySelector(".ai-calls-section")) return;

  const cas = session.ai_calls_honest_audit_summary || {};
  const buckets = cas.ai_calls_usage_buckets_by_input || {};
  const isFallback = !!cas.degraded_from_fallback;
  const callsSection = document.createElement("div");
  callsSection.className = "ai-calls-section";
  callsSection.innerHTML = `
    <div class="box" style="margin-top:0;margin-bottom:8px">
      <h3>AI Calls - honest call-level audit (primary truth)${isFallback ? ' <span style="color:#c09853;font-weight:400">[DEGRADED: fallback]</span>' : ''}</h3>
      <div class="muted xsmall" style="margin-bottom:6px">${isFallback
        ? '<span style="color:#c09853;font-weight:600">DEGRADED:</span> rollout JSONL not found. Call-level view was reconstructed from logs fallback and is not raw request-level truth.'
        : 'Each AI call comes from live last_token_usage. Zero-usage is counted separately. Unmapped calls are marked explicitly.'}</div>
      ${isFallback ? '<div class="warning-banner" style="background:#3a2a00;border:1px solid #c09853;color:#c09853;padding:6px 10px;margin-bottom:8px;border-radius:4px;font-size:12px">Fallback session: call-level data is degraded and does not reflect true per-request cost.</div>' : ''}
      <div class="metrics" style="margin-bottom:6px">
        ${metric("AI calls", nf.format(cas.ai_calls_total || 0))}
        ${metric("With usage", nf.format(cas.ai_calls_with_usage || 0))}
        ${metric("Zero usage", nf.format(cas.ai_calls_zero_usage || 0))}
        ${metric(isFallback ? "Fallback" : "Unmapped", nf.format(isFallback ? (cas.ai_calls_total || 0) : (cas.ai_calls_unmapped || 0)))}
        ${metric("Input", nf.format(cas.ai_calls_total_input_tokens || 0))}
        ${metric("Output", nf.format(cas.ai_calls_total_output_tokens || 0))}
        ${metric("Cost", cas.ai_calls_total_cost_usd != null ? money(cas.ai_calls_total_cost_usd) : "-")}
      </div>
      <div class="muted xsmall" style="margin-top:4px">Buckets by input_tokens:</div>
      <div class="pills" style="flex-wrap:wrap;margin-bottom:6px">
        ${Object.entries(buckets).map(([k, v]) => `<span class="pill">${escapeHtml(k.replace(/_/g, " "))}: ${nf.format((v && v.count) || 0)}</span>`).join("")}
      </div>
      <button class="small" style="margin-top:6px" onclick="var el=document.getElementById('aiCallsTable');el.style.display=el.style.display==='none'?'block':'none'">Show AI calls table</button>
      <div id="aiCallsTable" style="display:none;max-height:400px;overflow:auto;margin-top:6px">
        <table style="width:100%;border-collapse:collapse;font-size:11px">
          <thead><tr style="background:#2a2a2a">
            <th style="text-align:right;padding:2px 4px">#</th>
            <th style="text-align:left;padding:2px 4px">Model</th>
            <th style="text-align:right;padding:2px 4px">Step</th>
            <th style="text-align:right;padding:2px 4px">Input</th>
            <th style="text-align:right;padding:2px 4px">Cached</th>
            <th style="text-align:right;padding:2px 4px">Output</th>
            <th style="text-align:right;padding:2px 4px">Reasoning</th>
            <th style="text-align:right;padding:2px 4px">Cost</th>
            <th style="text-align:center;padding:2px 4px">Zero?</th>
            <th style="text-align:center;padding:2px 4px">Map</th>
          </tr></thead><tbody>
          ${session.ai_calls.map(function(c) {
            const cost = c.estimated_cost || {};
            const usage = c.usage || {};
            const zeroMark = c.is_zero_usage ? '<span style="color:#c09853">zero</span>' : '<span style="color:#6a6">usage</span>';
            const mapColor = c.mapping_confidence === "unmapped" ? "#c44" : (c.mapping_confidence === "medium" ? "#cc4" : (c.mapping_confidence === "fallback_logs_only" ? "#c09853" : "#4a4"));
            return '<tr style="' + (c.is_zero_usage ? 'opacity:0.5' : '') + '">' +
              '<td style="text-align:right;padding:1px 4px">' + c.call_index + '</td>' +
              '<td style="padding:1px 4px">' + escapeHtml(c.model) + '</td>' +
              '<td style="text-align:right;padding:1px 4px">' + (c.step_index || '-') + '</td>' +
              '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.input_tokens || 0) + '</td>' +
              '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.cached_tokens || 0) + '</td>' +
              '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.output_tokens || 0) + '</td>' +
              '<td style="text-align:right;padding:1px 4px">' + nf.format(usage.reasoning_tokens || 0) + '</td>' +
              '<td style="text-align:right;padding:1px 4px;font-weight:600">' + (cost.estimated_total_cost_usd != null ? money(cost.estimated_total_cost_usd) : '-') + '</td>' +
              '<td style="text-align:center;padding:1px 4px">' + zeroMark + '</td>' +
              '<td style="text-align:center;padding:1px 4px;color:' + mapColor + '">' + escapeHtml(c.mapping_confidence) + '</td>' +
              '</tr>';
          }).join("")}
          </tbody></table>
      </div>
    </div>`;

  const firstStep = root.querySelector(".step");
  if (firstStep) {
    root.insertBefore(callsSection, firstStep);
  } else {
    root.appendChild(callsSection);
  }
}

const oldRenderHeader = renderHeader;
renderHeader = function patchedRenderHeader() {
  oldRenderHeader();
  const s = sessionDetailCache;
  if (!s) return;
  const cas = s.ai_calls_honest_audit_summary || {};
  if (!cas.ai_calls_total) return;
  const meta = document.getElementById("meta");
  if (!meta) return;
  if (meta.textContent.includes("AI calls:")) return;
  meta.textContent += ` · AI calls: ${cas.ai_calls_with_usage || 0} with usage / ${cas.ai_calls_zero_usage || 0} zero / ${cas.ai_calls_unmapped || 0} unmapped`;
};

const oldRenderSteps = renderSteps;
renderSteps = function patchedRenderSteps() {
  oldRenderSteps();
  const root = document.getElementById("steps");
  renderAiCallsSectionIntoSteps(root, sessionDetailCache);
};

init();
