#!/usr/bin/env python3
"""Codex Token Monitor Server v2 — source-aware hybrid monitor over live Codex chats + OTel archives."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SCHEMA_VERSION = "token-monitor-server.v2"
ARCHIVE_STATE_VERSION = "archive-state.v2"

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_DIR = REPO_ROOT / "config"
STATIC_DIR = REPO_ROOT / "static" / "codex-token-monitor"
LOCAL_MONITOR_DIR = REPO_ROOT / "_local" / "codex-token-monitor"
AUDITS_DIR = LOCAL_MONITOR_DIR / "audits"
ROLLOUT_INDEX_TTL_SEC = 10.0

_live_rollout_summary_cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}
_live_rollout_summary_lock = threading.Lock()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_json_safe(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _extract_content_text(content_parts: Any) -> str:
    if not isinstance(content_parts, list):
        return ""
    return " ".join(
        str(part.get("text", "") if isinstance(part, dict) else part)
        for part in content_parts
    ).strip()


def _looks_like_system_composed_prompt(text: str) -> bool:
    return (
        "AGENTS.md" in text
        or "Global Instructions" in text
        or len(text) > 5000
    )


def _is_internal_live_user_prompt(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    return (
        _looks_like_system_composed_prompt(raw)
        or raw.startswith("PLEASE IMPLEMENT THIS PLAN:")
        or raw.startswith("<turn_aborted>")
        or "the user interrupted the previous turn on purpose" in lower
        or raw.startswith("Прочитай handoff ")
        or raw.startswith("Read handoff ")
    )


def _humanize_live_title(title: str, fallback: str) -> str:
    raw = str(title or "").strip()
    if not raw:
        return fallback
    first_line = next((line.strip() for line in raw.splitlines() if line.strip()), raw)
    if len(first_line) > 140:
        return first_line[:139] + "\u2026"
    return first_line


# ── Config loading ──


def load_config(config_path: Path) -> dict[str, Any]:
    """Load v2 config with sources. Falls back to v1 projects-style config."""
    if not config_path.exists():
        return {
            "version": 2,
            "default_source_id": "",
            "sources": [],
        }
    data = read_json(config_path)

    # v2 config has 'sources' key
    if "sources" in data:
        return data

    # v1 config — migrate on-the-fly to sources
    return _migrate_v1_config(data)


def _migrate_v1_config(data: dict[str, Any]) -> dict[str, Any]:
    """Convert v1 project-based config to v2 source-based config."""
    projects = data.get("projects", [])
    sources = []
    for p in projects:
        sources.append({
            "id": p.get("id", "legacy"),
            "name": p.get("name", "Legacy Project"),
            "kind": "archive",
            "path": p.get("path", ""),
            "runs_dir": p.get("runs_dir", "_local/codex-token-debugger"),
        })
    default_id = data.get("default_project_id", "")
    if not default_id and sources:
        default_id = sources[0]["id"]
    return {
        "version": 2,
        "default_source_id": default_id,
        "sources": sources,
    }


def find_source(config: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for s in config.get("sources", []):
        if s["id"] == source_id:
            return s
    return None


# ── Archive state ──


def load_archive_state() -> dict[str, list[str]]:
    path = LOCAL_MONITOR_DIR / "archive_state.json"
    data = read_json_safe(path)
    if data and isinstance(data.get("archived_sessions"), dict):
        return data["archived_sessions"]
    return {}


def save_archive_state(state: dict[str, list[str]]) -> None:
    path = LOCAL_MONITOR_DIR / "archive_state.json"
    write_json(path, {"version": ARCHIVE_STATE_VERSION, "archived_sessions": state})


def is_archived(source_id: str, session_id: str) -> bool:
    state = load_archive_state()
    return session_id in state.get(source_id, [])


def set_archived(source_id: str, session_id: str, archived: bool) -> None:
    state = load_archive_state()
    source_archived = state.setdefault(source_id, [])
    if archived:
        if session_id not in source_archived:
            source_archived.append(session_id)
    else:
        if session_id in source_archived:
            source_archived.remove(session_id)
    save_archive_state(state)


def discover_archive_sessions(source: dict[str, Any]) -> list[dict[str, Any]]:
    project_path = Path(source["path"])
    runs_dir_name = source.get("runs_dir", "_local/codex-token-debugger")
    runs_dir = project_path / runs_dir_name

    if not runs_dir.exists() or not runs_dir.is_dir():
        return []

    sessions: list[dict[str, Any]] = []
    for entry in sorted(runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not entry.is_dir():
            continue

        normalized_json = entry / "token-cost-normalized" / "token_cost_dashboard_data.json"
        parsed_jsonl = entry / "parsed" / "token_usage.jsonl"

        has_normalized = normalized_json.exists()
        has_parsed = parsed_jsonl.exists()

        if not has_normalized and not has_parsed:
            continue

        session_id = entry.name
        dashboard = read_json_safe(normalized_json) if has_normalized else None

        title = session_id
        date_iso = ""
        model = "unknown"
        reasoning = "unknown"
        workdir = str(project_path)
        step_count = 0
        total_cost = None
        warnings_count = 0
        confirmation_badges: list[str] = []

        # Check for confirmation summary
        reports_dir = entry / "reports"
        if reports_dir.exists():
            for rpt in reports_dir.glob("*_confirmation_summary.json"):
                cdata = read_json_safe(rpt)
                if cdata and isinstance(cdata, dict):
                    kind = cdata.get("kind", "")
                    if kind == "mixed":
                        confirmation_badges.append("mixed")
                    if kind == "noisy":
                        confirmation_badges.append("noisy")
                    sel_turn = cdata.get("selected_turn") or cdata.get("selected_turn_index")
                    if sel_turn is not None:
                        confirmation_badges.append(f"turn:{sel_turn}")

        if dashboard and isinstance(dashboard, dict):
            summary = dashboard.get("summary", {})
            turns = dashboard.get("turns", [])
            if isinstance(summary, dict):
                date_iso = _extract_date(summary, turns)
                models = summary.get("models", [])
                model = _pick_model(models)
                step_count = summary.get("turn_count", len(turns) if isinstance(turns, list) else 0)
                total_cost = summary.get("estimated_total_cost_usd")
                warnings_count = len(summary.get("warnings", []))
            if isinstance(turns, list) and turns:
                efforts = sorted({str(t.get("reasoning_effort", "unknown")) for t in turns})
                reasoning = efforts[0] if len(efforts) == 1 else "mixed"
                if not date_iso:
                    date_iso = _earliest_timestamp(turns)

        if not date_iso:
            mtime = entry.stat().st_mtime
            date_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        sessions.append({
            "id": session_id,
            "title": title,
            "date": date_iso,
            "model": model,
            "reasoning": reasoning,
            "workdir": workdir,
            "step_count": step_count,
            "total_cost_usd": total_cost,
            "warnings_count": warnings_count,
            "has_normalized": has_normalized,
            "has_parsed": has_parsed,
            "source_kind": "archive",
            "confirmation_badges": confirmation_badges,
        })

    return sessions


def _extract_date(summary: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    for turn in turns:
        ts = turn.get("timestamp", "")
        if ts:
            return ts
    return ""


def _earliest_timestamp(turns: list[dict[str, Any]]) -> str:
    timestamps = [t.get("timestamp", "") for t in turns if t.get("timestamp", "")]
    return min(timestamps) if timestamps else ""


def _pick_model(models: list[str]) -> str:
    if not models:
        return "unknown"
    return models[0] if len(models) == 1 else "mixed"


def _compute_turn_summary(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary from a list of turn dicts (filtered or full)."""
    total_input = 0
    total_cached = 0
    total_output = 0
    total_reasoning = 0
    total_tool = 0
    total_cost = 0.0
    models: set[str] = set()
    warnings: list[str] = []
    for t in turns:
        total_input += to_int(t.get("input_tokens", 0))
        total_cached += to_int(t.get("cached_tokens", 0))
        total_output += to_int(t.get("output_tokens", 0))
        total_reasoning += to_int(t.get("reasoning_tokens", 0))
        total_tool += to_int(t.get("tool_tokens", 0))
        m = str(t.get("model", ""))
        if m:
            models.add(m)
        w = t.get("warnings")
        if isinstance(w, list):
            warnings.extend(w)
        cost = t.get("estimated_cost_usd", {})
        if isinstance(cost, dict):
            total_cost += float(cost.get("total", 0) or 0)
    non_cached = total_input - total_cached
    ratio = (total_cached / total_input) if total_input > 0 else 0
    return {
        "turn_count": len(turns),
        "session_count": 1,
        "total_input_tokens": total_input,
        "total_cached_tokens": total_cached,
        "total_non_cached_input_tokens": non_cached,
        "average_cached_ratio": ratio,
        "total_output_tokens": total_output,
        "total_reasoning_tokens": total_reasoning,
        "total_tool_tokens": total_tool,
        "estimated_total_cost_usd": total_cost,
        "models": sorted(models),
        "warnings": warnings,
    }


def build_archive_session_detail(source: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    project_path = Path(source["path"])
    runs_dir_name = source.get("runs_dir", "_local/codex-token-debugger")
    runs_dir = project_path / runs_dir_name
    run_dir = runs_dir / session_id

    if not run_dir.exists() or not run_dir.is_dir():
        return None

    normalized_json = run_dir / "token-cost-normalized" / "token_cost_dashboard_data.json"
    dashboard = read_json_safe(normalized_json)

    if not dashboard:
        return _fallback_session(session_id, run_dir)

    summary = dashboard.get("summary", {})
    turns = dashboard.get("turns", [])
    sessions_list = dashboard.get("sessions", [])

    title = session_id
    date_iso = _extract_date(summary, turns)
    if not date_iso:
        mtime = run_dir.stat().st_mtime
        date_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

    models = summary.get("models", [])
    model_str = _pick_model(models)
    efforts = sorted({str(t.get("reasoning_effort", "unknown")) for t in turns})
    reasoning_str = efforts[0] if len(efforts) == 1 else "mixed"

    confirmation_badges: list[str] = []
    selected_turn_index: int | None = None
    reports_dir = run_dir / "reports"
    if reports_dir.exists():
        for rpt in reports_dir.glob("*_confirmation_summary.json"):
            cdata = read_json_safe(rpt)
            if cdata and isinstance(cdata, dict):
                kind = cdata.get("kind", "")
                if kind == "mixed":
                    confirmation_badges.append("mixed")
                if kind == "noisy":
                    confirmation_badges.append("noisy")
                sel_turn = cdata.get("selected_turn") or cdata.get("selected_turn_index")
                if sel_turn is not None:
                    if isinstance(sel_turn, dict):
                        # selected_turn is an object with model/timestamp — match by these
                        st_model = str(sel_turn.get("model", ""))
                        st_ts = str(sel_turn.get("timestamp", ""))
                        confirmation_badges.append(f"model:{st_model}")
                        selected_turn_index = -1  # signal: match by fields
                        _selected_turn_data = sel_turn
                    else:
                        sel_turn_int = to_int(sel_turn)
                        confirmation_badges.append(f"turn:{sel_turn_int}")
                        selected_turn_index = sel_turn_int

    # When a confirmed turn is selected, show only that turn
    if selected_turn_index is not None and isinstance(turns, list):
        if selected_turn_index == -1:
            # selected_turn was a dict — match by model+timestamp
            st_model = str(_selected_turn_data.get("model", ""))
            st_ts = str(_selected_turn_data.get("timestamp", ""))
            filtered = [t for t in turns
                        if str(t.get("model", "")) == st_model and str(t.get("timestamp", "")) == st_ts]
            if filtered:
                turns = filtered
                model_str = str(turns[0].get("model", model_str))
                reasoning_str = str(turns[0].get("reasoning_effort", reasoning_str))
                summary = _compute_turn_summary(turns)
        else:
            filtered = [t for t in turns if to_int(t.get("turn_index", 0)) == selected_turn_index]
            if filtered:
                turns = filtered
                model_str = str(turns[0].get("model", model_str))
                reasoning_str = str(turns[0].get("reasoning_effort", reasoning_str))
                summary = _compute_turn_summary(turns)

    steps = []
    for t in turns:
        steps.append(_build_step(t))

    return {
        "id": session_id,
        "title": title,
        "date": date_iso,
        "model": model_str,
        "reasoning": reasoning_str,
        "workdir": str(project_path),
        "source_kind": "archive",
        "confirmation_badges": confirmation_badges,
        "summary": summary,
        "steps": steps,
    }


def _fallback_session(session_id: str, run_dir: Path) -> dict[str, Any]:
    mtime = run_dir.stat().st_mtime
    date_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    return {
        "id": session_id,
        "title": session_id,
        "date": date_iso,
        "model": "unknown",
        "reasoning": "unknown",
        "workdir": "",
        "source_kind": "archive",
        "confirmation_badges": [],
        "summary": {
            "turn_count": 0,
            "session_count": 0,
            "total_input_tokens": 0,
            "total_cached_tokens": 0,
            "total_non_cached_input_tokens": 0,
            "average_cached_ratio": 0,
            "total_output_tokens": 0,
            "total_reasoning_tokens": 0,
            "total_tool_tokens": 0,
            "estimated_total_cost_usd": None,
            "warnings": [],
        },
        "steps": [],
    }


def _build_step(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_index": to_int(turn.get("turn_index"), 0),
        "turn_id": str(turn.get("turn_id", "")),
        "timestamp": str(turn.get("timestamp", "")),
        "model": str(turn.get("model", "unknown")),
        "reasoning_effort": str(turn.get("reasoning_effort", "unknown")),
        "user_prompt": {
            "available": False,
            "text": "",
            "hidden_by_default": True,
        },
        "assistant_answer": {
            "available": False,
            "text": "",
            "hidden_by_default": True,
        },
        "usage": {
            "input_tokens": to_int(turn.get("input_tokens"), 0),
            "cached_tokens": to_int(turn.get("cached_tokens"), 0),
            "non_cached_input_tokens": to_int(turn.get("non_cached_input_tokens"), 0),
            "cached_ratio": float(turn.get("cached_ratio", 0)),
            "output_tokens": to_int(turn.get("output_tokens"), 0),
            "reasoning_tokens": to_int(turn.get("reasoning_tokens"), 0),
            "tool_tokens": to_int(turn.get("tool_tokens"), 0),
            "available": True,
            "estimated_total_cost_usd": (
                turn.get("estimated_cost_usd", {}).get("total")
                if isinstance(turn.get("estimated_cost_usd"), dict)
                else None
            ),
            "estimated_input_cost_usd": (
                turn.get("estimated_cost_usd", {}).get("input")
                if isinstance(turn.get("estimated_cost_usd"), dict)
                else None
            ),
            "estimated_cached_input_cost_usd": (
                turn.get("estimated_cost_usd", {}).get("cached_input")
                if isinstance(turn.get("estimated_cost_usd"), dict)
                else None
            ),
            "estimated_output_cost_usd": (
                turn.get("estimated_cost_usd", {}).get("output")
                if isinstance(turn.get("estimated_cost_usd"), dict)
                else None
            ),
        },
        "environment": {
            "thread_id": str(turn.get("thread_id", "")),
            "observed_mcp_server_count": to_int(turn.get("observed_mcp_server_count"), 0),
            "observed_mcp_servers": turn.get("observed_mcp_servers")
            if isinstance(turn.get("observed_mcp_servers"), list)
            else [],
            "enabled_plugins_count": to_int(turn.get("enabled_plugins_count"), 0),
            "enabled_skills_count": to_int(turn.get("enabled_skills_count"), 0),
            "global_user_instructions_status": str(turn.get("global_user_instructions_status", "unknown")),
            "repo_context_status": str(turn.get("repo_context_status", "unknown")),
        },
        "warnings": turn.get("warnings")
        if isinstance(turn.get("warnings"), list)
        else [],
    }


# ── Live chat adapter ──


def _load_pricing() -> dict[str, dict[str, float]]:
    """Load token pricing from config/token_pricing.json.
    Returns dict keyed by model name with input/cached_input/output prices,
    or empty dict on absence/error."""
    pricing_path = CONFIG_DIR / "token_pricing.json"
    if not pricing_path.exists():
        return {}
    data = read_json_safe(pricing_path)
    if not isinstance(data, dict):
        return {}
    result = data.get("prices_per_1m", {})
    return result if isinstance(result, dict) else {}


def discover_live_sessions(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Read real Codex chats from codex_dir (read-only)."""
    codex_dir = Path(source.get("codex_dir", ""))
    if not codex_dir.exists():
        return []

    sqlite_path = codex_dir / "state_5.sqlite"
    threads = _read_threads_from_sqlite(sqlite_path)
    threads_by_id = {
        str(thread.get("id", "")).strip(): thread
        for thread in threads
        if str(thread.get("id", "")).strip()
    }

    index_path = codex_dir / "session_index.jsonl"
    index_entries = _read_session_index(index_path)
    rollout_summaries = _get_live_rollout_summaries(codex_dir, allow_build=True)

    sessions: list[dict[str, Any]] = []
    all_thread_ids = set(threads_by_id) | set(index_entries) | set(rollout_summaries)
    for thread_id in all_thread_ids:
        thread = threads_by_id.get(thread_id, {})
        ie = index_entries.get(thread_id, {})
        rollout_summary = rollout_summaries.get(thread_id, {})
        title = thread.get("title", thread_id) or thread_id
        if title == thread_id:
            title = ie.get("thread_name") or rollout_summary.get("title_hint") or thread_id
        title = _humanize_live_title(title, thread_id)

        date_iso = (
            thread.get("updated_at")
            or thread.get("created_at")
            or ie.get("updated_at")
            or rollout_summary.get("latest_timestamp")
            or ""
        )
        model = (
            thread.get("model")
            or rollout_summary.get("model")
            or "unknown"
        )
        reasoning_effort = (
            thread.get("reasoning_effort")
            or rollout_summary.get("reasoning_effort")
            or "unknown"
        )
        cwd = (
            thread.get("cwd")
            or rollout_summary.get("cwd")
            or source.get("codex_dir", "")
        )

        step_count = None
        total_cost = None
        if rollout_summary:
            step_count = to_int(rollout_summary.get("step_count", 0))
        last_token = rollout_summary.get("last_token_usage", {})
        if isinstance(last_token, dict) and last_token:
            ti = to_int(last_token.get("input_tokens", last_token.get("input_token_count", 0)))
            tc_in = to_int(last_token.get("cached_input_tokens", last_token.get("cached_input_token_count", 0)))
            to_out = to_int(last_token.get("output_tokens", last_token.get("output_token_count", 0)))
            pricing = _load_pricing()
            if model in pricing:
                p = pricing[model]
                non_cached = ti - tc_in
                total_cost = (
                    (non_cached / 1_000_000) * p.get("input", 0)
                    + (tc_in / 1_000_000) * p.get("cached_input", 0)
                    + (to_out / 1_000_000) * p.get("output", 0)
                )

        sessions.append({
            "id": thread_id,
            "title": title,
            "date": date_iso,
            "model": model,
            "reasoning": reasoning_effort,
            "workdir": cwd,
            "step_count": step_count,
            "total_cost_usd": total_cost,
            "warnings_count": 0,
            "has_normalized": False,
            "has_parsed": True,
            "source_kind": "live",
            "confirmation_badges": [],
        })

    sessions.sort(key=lambda s: (str(s.get("date", "")), str(s.get("id", ""))), reverse=True)
    return sessions


def _read_threads_from_sqlite(sqlite_path: Path) -> list[dict[str, Any]]:
    """Read threads table from Codex state_5.sqlite (read-only)."""
    if not sqlite_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM pragma_table_info('threads')")
        columns = {r[0] for r in cursor.fetchall()}
        select_cols = []
        for col in ["id", "title", "model", "reasoning_effort", "cwd", "created_at", "updated_at"]:
            if col in columns:
                select_cols.append(col)
            else:
                select_cols.append(f"NULL as {col}")
        query = f"SELECT {', '.join(select_cols)} FROM threads ORDER BY updated_at DESC, created_at DESC"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _read_session_index(index_path: Path) -> dict[str, dict[str, Any]]:
    """Read session_index.jsonl for thread_name per thread_id."""
    entries: dict[str, dict[str, Any]] = {}
    if not index_path.exists():
        return entries
    try:
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                tid = obj.get("thread_id") or obj.get("id") or ""
                if tid:
                    entries[tid] = obj
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return entries


def _scan_rollout_file_summary(rollout_path: Path) -> tuple[str | None, dict[str, Any]]:
    thread_id = None
    step_count = 0
    last_token_usage = None
    latest_timestamp = ""
    title_hint = ""
    model = ""
    reasoning_effort = ""
    cwd = ""

    try:
        with rollout_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = str(obj.get("timestamp", "") or "")
                if timestamp and timestamp > latest_timestamp:
                    latest_timestamp = timestamp

                outer_type = obj.get("type")
                payload = obj.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                if thread_id is None and outer_type == "session_meta":
                    candidate = str(payload.get("id", "")).strip()
                    if candidate:
                        thread_id = candidate
                    cwd = str(payload.get("cwd", "") or cwd)

                if outer_type == "turn_context":
                    if thread_id is None:
                        candidate = str(payload.get("thread_id", "")).strip()
                        if candidate:
                            thread_id = candidate
                    model = str(payload.get("model", "") or model)
                    reasoning_effort = str(payload.get("reasoning_effort", "") or reasoning_effort)

                if outer_type == "response_item" and payload.get("role") == "user":
                    text = _extract_content_text(payload.get("content", []))
                    if text and not _is_internal_live_user_prompt(text):
                        step_count += 1
                        if not title_hint:
                            title_hint = text

                if outer_type == "event_msg":
                    info = payload.get("info", {})
                    token_usage = info.get("total_token_usage") if isinstance(info, dict) else None
                    if isinstance(token_usage, dict):
                        last_token_usage = token_usage
    except OSError:
        return None, {}

    return thread_id, {
        "paths": [str(rollout_path)],
        "step_count": step_count,
        "last_token_usage": last_token_usage if isinstance(last_token_usage, dict) else {},
        "latest_timestamp": latest_timestamp,
        "title_hint": title_hint,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "cwd": cwd,
    }


def _get_live_rollout_summaries(codex_dir: Path, *, allow_build: bool = True) -> dict[str, dict[str, Any]]:
    cache_key = str(codex_dir.resolve())
    now = time.time()
    cached = _live_rollout_summary_cache.get(cache_key)
    if cached and (now - cached[0]) < ROLLOUT_INDEX_TTL_SEC:
        return cached[1]
    if not allow_build:
        return cached[1] if cached else {}

    with _live_rollout_summary_lock:
        now = time.time()
        cached = _live_rollout_summary_cache.get(cache_key)
        if cached and (now - cached[0]) < ROLLOUT_INDEX_TTL_SEC:
            return cached[1]

        sessions_dir = codex_dir / "sessions"
        summaries: dict[str, dict[str, Any]] = {}
        if not sessions_dir.exists():
            _live_rollout_summary_cache[cache_key] = (now, summaries)
            return summaries

        for rollout_path in sorted(sessions_dir.glob("**/rollout-*.jsonl")):
            thread_id, file_summary = _scan_rollout_file_summary(rollout_path)
            if not thread_id:
                continue
            existing = summaries.setdefault(thread_id, {"paths": [], "step_count": 0, "last_token_usage": {}})
            existing["paths"].extend(file_summary.get("paths", []))
            existing["step_count"] = to_int(existing.get("step_count", 0)) + to_int(file_summary.get("step_count", 0))
            if file_summary.get("last_token_usage"):
                existing["last_token_usage"] = file_summary["last_token_usage"]

        _live_rollout_summary_cache[cache_key] = (now, summaries)
        return summaries


def _read_rollout_jsonl(codex_dir: Path, thread_id: str) -> list[dict[str, Any]]:
    """Read rollout JSONL files for a given thread via cached file lookup."""
    events: list[dict[str, Any]] = []
    summary = _get_live_rollout_summaries(codex_dir).get(thread_id, {})
    paths = summary.get("paths", [])
    if not isinstance(paths, list):
        return events

    for raw_path in sorted(str(p) for p in paths):
        rollout_path = Path(raw_path)
        try:
            with rollout_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
                continue
    return events


_LOG_TURN_ID_RE = re.compile(r'turn(?:\.id|_id)=([0-9a-f-]{36})', re.IGNORECASE)
_LOG_SUBMISSION_ID_RE = re.compile(r'Submission sub=Submission \{ id: "([0-9a-f-]{36})", op: UserInput', re.IGNORECASE)
_LOG_TEXT_RE = re.compile(r'Text \{ text: "(.*?)", text_elements:', re.DOTALL)
_LOG_MODEL_RE = re.compile(r'model=([^\s}]+)')
_LOG_REASONING_RE = re.compile(r'codex\.turn\.reasoning_effort=([^\s}:]+)')
_LOG_CWD_RE = re.compile(r'cwd=([^}\r\n]+)')


def _decode_debug_log_text(raw: str) -> str:
    """Best-effort unescape for Rust debug strings stored in logs_2.sqlite."""
    if not raw:
        return ""
    text = raw.replace(r"\r\n", "\n").replace(r"\n", "\n").replace(r"\t", "\t")
    text = text.replace(r"\"", '"').replace(r"\\", "\\")
    return text.strip()


def _read_live_log_fallback_steps(
    codex_dir: Path,
    thread_id: str,
    *,
    default_model: str,
    default_reasoning: str,
    default_cwd: str,
) -> list[dict[str, Any]]:
    """Fallback for live sessions missing rollout JSONL.

    Builds coarse per-turn steps from logs_2.sqlite. This is intentionally
    lower fidelity than rollout parsing, but avoids empty detail pages for
    recent/live sessions whose raw rollout files are absent.
    """
    logs_path = codex_dir / "logs_2.sqlite"
    if not logs_path.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{logs_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, ts, target, feedback_log_body FROM logs WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        return []

    turns: dict[str, dict[str, Any]] = {}
    turn_order: list[str] = []

    for row in rows:
        body = str(row["feedback_log_body"] or "")
        if not body:
            continue

        turn_id = ""
        m = _LOG_TURN_ID_RE.search(body)
        if m:
            turn_id = m.group(1)
        else:
            m = _LOG_SUBMISSION_ID_RE.search(body)
            if m:
                turn_id = m.group(1)
        if not turn_id:
            continue

        if turn_id not in turns:
            turns[turn_id] = {
                "turn_id": turn_id,
                "timestamp": datetime.fromtimestamp(int(row["ts"]), timezone.utc).isoformat() if row["ts"] else "",
                "model": default_model or "unknown",
                "reasoning": default_reasoning or "unknown",
                "cwd": default_cwd or "",
                "prompt": "",
                "tool_event_count": 0,
                "mcp_event_count": 0,
                "row_count": 0,
            }
            turn_order.append(turn_id)

        turn = turns[turn_id]
        turn["row_count"] += 1

        if turn["model"] in ("", "unknown"):
            m = _LOG_MODEL_RE.search(body)
            if m:
                turn["model"] = m.group(1)
        if turn["reasoning"] in ("", "unknown"):
            m = _LOG_REASONING_RE.search(body)
            if m:
                turn["reasoning"] = m.group(1)
        if not turn["cwd"]:
            m = _LOG_CWD_RE.search(body)
            if m:
                turn["cwd"] = m.group(1).strip()

        if not turn["prompt"] and "Submission sub=Submission" in body and "op: UserInput" in body:
            m = _LOG_TEXT_RE.search(body)
            if m:
                turn["prompt"] = _decode_debug_log_text(m.group(1))

        lower_body = body.lower()
        if (
            'otel.name="function_call"' in body
            or "apply_patch" in lower_body
            or "write_file" in lower_body
            or "shell_command" in lower_body
            or "function_call_output" in lower_body
        ):
            turn["tool_event_count"] += 1
        if "mcp" in str(row["target"]).lower() or "mcp" in lower_body:
            turn["mcp_event_count"] += 1

    steps: list[dict[str, Any]] = []
    for idx, turn_id in enumerate(turn_order, start=1):
        turn = turns[turn_id]
        if turn["row_count"] <= 0:
            continue

        tool_hits = to_int(turn.get("tool_event_count", 0))
        mcp_hits = to_int(turn.get("mcp_event_count", 0))
        fallback_note = (
            "Шаг восстановлен по logs_2.sqlite: raw rollout JSONL для этого хода не найден, "
            "поэтому точная per-step стоимость и полный текст ответа агента недоступны."
        )
        if tool_hits or mcp_hits:
            fallback_note += f" Обнаружено log-событий: tool={tool_hits}, mcp={mcp_hits}."

        steps.append({
            "step_index": idx,
            "timestamp": turn.get("timestamp", ""),
            "turn_id": turn_id,
            "model": turn.get("model") or default_model or "unknown",
            "reasoning_effort": turn.get("reasoning") or default_reasoning or "unknown",
            "user_prompt": {
                "available": bool(turn.get("prompt")),
                "kind": "user_message",
                "text": turn.get("prompt", ""),
            },
            "assistant_answer": {
                "available": True,
                "text": fallback_note,
            },
            "usage": {
                "available": False,
                "source": "logs_2.sqlite_fallback",
                "note": "raw rollout JSONL missing; step reconstructed from logs_2.sqlite",
            },
            "warnings": [
                "logs_2.sqlite fallback",
                "raw rollout JSONL missing",
            ],
            "post_step_badges": ["logs fallback"],
            "environment": {
                "thread_id": thread_id,
                "observed_mcp_server_count": 1 if mcp_hits > 0 else 0,
                "observed_mcp_servers": ["logs_2.sqlite"] if mcp_hits > 0 else [],
                "enabled_plugins_count": 0,
                "enabled_skills_count": 0,
                "repo_context_status": "unknown",
            },
            "request_usage_items": [],
            "full_step_usage": {
                "source": "logs_2.sqlite_fallback",
                "request_count": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "non_cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "tool_tokens": 0,
            },
            "full_step_cost": {"available": False, "total_usd": None},
            "primary_request_usage": {"available": False},
            "cumulative_before_step": {"available": False},
            "cumulative_after_step": {"available": False},
            "cumulative_delta": {"available": False},
            "unattributed_delta": {"available": False},
            "cost_scope": {
                "current_displayed_cost_scope": "unknown",
                "full_step_cost_available": False,
                "request_cost_available": False,
                "mapping_confidence": "fallback_logs_only",
            },
            "event_range": {},
            "live_tool_events": [],
            "agent_activity": {
                "available": True,
                "activity_counts": {
                    "tool_events_from_logs": tool_hits,
                    "mcp_events_from_logs": mcp_hits,
                    "log_rows_seen": to_int(turn.get("row_count", 0)),
                },
                "activity_summary_ru": [fallback_note],
                "human_summary_ru": {
                    "available": True,
                    "text": fallback_note,
                },
                "requests_with_usage": 0,
                "model_related_events": tool_hits,
                "step_internal_actions": [],
                "agent_activity_stages": [],
                "agent_timeline": {"items": []},
            },
        })

    return steps


def build_live_session_detail(source: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    """Build session detail for a live Codex chat."""
    codex_dir = Path(source.get("codex_dir", ""))
    if not codex_dir.exists():
        return None

    sqlite_path = codex_dir / "state_5.sqlite"
    threads = _read_threads_from_sqlite(sqlite_path)
    thread = next((t for t in threads if t.get("id") == session_id), None)

    index_path = codex_dir / "session_index.jsonl"
    index_entries = _read_session_index(index_path)

    title = session_id
    date_iso = ""
    model = "unknown"
    reasoning = "unknown"
    cwd = ""

    if thread:
        title = thread.get("title", session_id) or session_id
        if title == session_id:
            ie = index_entries.get(session_id, {})
            title = ie.get("thread_name", session_id)
        title = _humanize_live_title(title, session_id)
        date_iso = thread.get("updated_at", thread.get("created_at", ""))
        model = thread.get("model", "unknown")
        reasoning = thread.get("reasoning_effort", "unknown")
        cwd = thread.get("cwd", "")
    if not date_iso:
        date_iso = datetime.now(timezone.utc).isoformat()

    events = _read_rollout_jsonl(codex_dir, session_id)
    used_logs_fallback = False
    if events:
        steps, timeline_events = _build_live_steps(events, session_id)
    else:
        steps = _read_live_log_fallback_steps(
            codex_dir,
            session_id,
            default_model=model,
            default_reasoning=reasoning,
            default_cwd=cwd,
        )
        timeline_events = []
        used_logs_fallback = bool(steps)

    total_cost = None
    total_input = 0
    total_cached = 0
    total_output = 0
    total_reasoning = 0
    total_tool = 0

    last_token = None
    for ev in reversed(events):
        pl = ev.get("payload", ev)
        if not isinstance(pl, dict):
            continue
        # token usage is in event_msg.payload.info.total_token_usage
        if pl.get("type") == "event_msg" or ev.get("type") == "event_msg":
            info = pl.get("info", {})
            tc = info.get("total_token_usage") if isinstance(info, dict) else None
            if tc and isinstance(tc, dict):
                last_token = tc
                break

    if last_token:
        total_input = to_int(last_token.get("input_tokens", last_token.get("input_token_count", 0)))
        total_cached = to_int(last_token.get("cached_input_tokens", last_token.get("cached_input_token_count", 0)))
        total_output = to_int(last_token.get("output_tokens", last_token.get("output_token_count", 0)))
        total_reasoning = to_int(last_token.get("reasoning_output_tokens", last_token.get("reasoning_token_count", 0)))
        total_tool = to_int(last_token.get("tool_tokens", last_token.get("tool_token_count", 0)))

        pricing = _load_pricing()
        if model in pricing:
            p = pricing[model]
            non_cached = total_input - total_cached
            total_cost = (
                (non_cached / 1_000_000) * p.get("input", 0)
                + (total_cached / 1_000_000) * p.get("cached_input", 0)
                + (total_output / 1_000_000) * p.get("output", 0)
            )

    summary_warnings: list[dict[str, str]] = []
    if total_input > 0:
        summary_warnings.append({
            "id": "live_totals_are_cumulative",
            "message": "В live-источнике totals берутся из последнего cumulative total_token_usage по треду, а не из суммы видимых шагов.",
        })
    if any((step.get("usage", {}) or {}).get("available") for step in steps):
        summary_warnings.append({
            "id": "live_steps_use_request_usage",
            "message": "Per-step usage для live-шага берётся из request-level last_token_usage, если он есть в rollout.",
        })
    if used_logs_fallback:
        summary_warnings.append({
            "id": "live_steps_restored_from_logs_fallback",
            "message": "Для этой live-сессии rollout JSONL не найден; шаги восстановлены по logs_2.sqlite с пониженной точностью.",
        })

    # v2.1: compute visible_step_full_usage_sum and unmapped_or_internal_usage
    visible_step_full_usage_sum: dict[str, int] = {
        "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
        "reasoning_tokens": 0, "tool_tokens": 0,
    }
    raw_model_requests_count = 0
    for step in steps:
        fsu = step.get("full_step_usage", {})
        if isinstance(fsu, dict):
            for fld in visible_step_full_usage_sum:
                visible_step_full_usage_sum[fld] += to_int(fsu.get(fld, 0))
            raw_model_requests_count += to_int(fsu.get("request_count", 0))
    unmapped_or_internal_usage: dict[str, int] = {
        "input_tokens": total_input - visible_step_full_usage_sum["input_tokens"],
        "cached_tokens": total_cached - visible_step_full_usage_sum["cached_tokens"],
        "output_tokens": total_output - visible_step_full_usage_sum["output_tokens"],
        "reasoning_tokens": total_reasoning - visible_step_full_usage_sum["reasoning_tokens"],
        "tool_tokens": total_tool - visible_step_full_usage_sum["tool_tokens"],
        "available": bool(total_input or total_output),
    }

    return {
        "id": session_id,
        "title": title,
        "date": date_iso,
        "model": model,
        "reasoning": reasoning,
        "workdir": cwd,
        "source_kind": "live",
        "summary": {
            "turn_count": len(steps),
            "session_count": 1,
            "usage_basis": "live_total_token_usage_latest",
            "step_usage_basis": "live_last_token_usage",
            "total_input_tokens": total_input,
            "total_cached_tokens": total_cached,
            "total_non_cached_input_tokens": total_input - total_cached,
            "average_cached_ratio": (total_cached / total_input) if total_input > 0 else 0,
            "total_output_tokens": total_output,
            "total_reasoning_tokens": total_reasoning,
            "total_tool_tokens": total_tool,
            "estimated_total_cost_usd": total_cost,
            "warnings": summary_warnings,
            "visible_steps_count": len(steps),
            "raw_model_requests_count": raw_model_requests_count,
            "visible_step_full_usage_sum": visible_step_full_usage_sum,
            "unmapped_or_internal_usage": unmapped_or_internal_usage,
            "session_activity_summary": _compute_session_activity_summary(steps),
        },
        "timeline_events": timeline_events,
        "steps": steps,
    }


def _compute_session_activity_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, int] = {
        "visible_steps": len(steps),
        "raw_model_requests": 0, "raw_events": 0,
        "file_reads": 0, "file_writes": 0, "shell_commands": 0,
        "git_operations": 0, "test_runs": 0, "context_compactions": 0,
        "unknown_events": 0,
    }
    top_expensive: list[dict[str, Any]] = []

    for step in steps:
        aa = step.get("agent_activity", {})
        if not isinstance(aa, dict) or not aa.get("available"):
            continue
        er = aa.get("event_range", {})
        totals["raw_events"] += er.get("raw_events_count", 0)
        counts = aa.get("activity_counts", {})
        if isinstance(counts, dict):
            totals["raw_model_requests"] += counts.get("model_requests", 0)
            totals["file_reads"] += counts.get("file_reads", 0)
            totals["file_writes"] += counts.get("file_writes", 0)
            totals["shell_commands"] += counts.get("shell_commands", 0)
            totals["git_operations"] += counts.get("git_operations", 0)
            totals["test_runs"] += counts.get("test_runs", 0)
            totals["context_compactions"] += counts.get("context_compactions", 0)
            totals["unknown_events"] += counts.get("unknown_events", 0)

        fsc = step.get("full_step_cost", {})
        if isinstance(fsc, dict) and fsc.get("total_usd") is not None:
            top_expensive.append({
                "step_index": step.get("step_index", 0),
                "full_step_cost_usd": fsc["total_usd"],
                "internal_requests": step.get("full_step_usage", {}).get("request_count", 0),
                "main_activity_ru": "; ".join(aa.get("activity_summary_ru", [])[:3]),
            })

    top_expensive.sort(key=lambda x: x["full_step_cost_usd"], reverse=True)

    all_internal: list[dict[str, Any]] = []
    for step in steps:
        aa = step.get("agent_activity", {})
        sia = aa.get("step_internal_actions", []) if isinstance(aa, dict) else []
        for a in sia:
            if a.get("cost", {}).get("total_usd") is not None:
                all_internal.append({
                    "step_index": step.get("step_index", 0),
                    "action_index": a.get("index", 0),
                    "action_title_ru": a.get("title_ru", "") or f"\u0412\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u0438\u0439 \u0437\u0430\u043f\u0440\u043e\u0441 \u043c\u043e\u0434\u0435\u043b\u0438 #{a.get('index', 0)}",
                    "possible_stage_ru": a.get("possible_stage_ru", ""),
                    "confidence": a.get("stage_confidence", "low"),
                    "input_tokens": a.get("usage", {}).get("input_tokens", 0),
                    "non_cached_input_tokens": a.get("usage", {}).get("non_cached_input_tokens", 0),
                    "output_tokens": a.get("usage", {}).get("output_tokens", 0),
                    "cost_usd": a["cost"]["total_usd"],
                    "expensive_reason_ru": a.get("expensive_reason", ""),
                })
    all_internal.sort(key=lambda x: x["cost_usd"], reverse=True)

    return {
        "visible_steps": totals["visible_steps"],
        "raw_model_requests": totals["raw_model_requests"],
        "raw_events": totals["raw_events"],
        "file_reads": totals["file_reads"],
        "file_writes": totals["file_writes"],
        "shell_commands": totals["shell_commands"],
        "git_operations": totals["git_operations"],
        "test_runs": totals["test_runs"],
        "context_compactions": totals["context_compactions"],
        "unknown_events": totals["unknown_events"],
        "top_expensive_steps": top_expensive[:5],
        "top_expensive_internal_actions": all_internal[:10],
    }


def _extract_patch_target_files(args: dict[str, Any]) -> list[dict[str, str]]:
    """Extract target file paths with roles from apply_patch arguments.

    Returns list of {path, role, confidence} dicts.
    role: 'modified' (Update), 'added' (Add), 'deleted' (Delete).
    Searches all string values recursively for *** Update/Add/Delete File: patterns.
    """
    import re as _re_patch
    seen: set[str] = set()
    results: list[dict[str, str]] = []

    def _search_strings(obj: Any) -> None:
        if isinstance(obj, str):
            for m in _re_patch.finditer(r'\*\*\*\s*(Update|Add|Delete)\s+File:\s*(.+)', obj):
                role_word = m.group(1)
                p = m.group(2).strip()
                if p and p not in seen:
                    seen.add(p)
                    role = {"Update": "modified", "Add": "added", "Delete": "deleted"}.get(role_word, "modified")
                    results.append({"path": p, "role": role, "confidence": "high"})
        elif isinstance(obj, dict):
            for v in obj.values():
                _search_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                _search_strings(v)

    _search_strings(args)

    # Fallback: check common key names for explicit file paths (role unknown → modified)
    for key in ("file_path", "target_file", "path", "target", "file"):
        fp = args.get(key, "")
        if isinstance(fp, str) and fp.strip() and fp.strip() not in seen:
            seen.add(fp.strip())
            results.append({"path": fp.strip(), "role": "modified", "confidence": "low"})

    fl = args.get("files", args.get("changed_files", args.get("targets", [])))
    if isinstance(fl, list):
        for f in fl:
            if isinstance(f, str) and f.strip() and f.strip() not in seen:
                seen.add(f.strip())
                results.append({"path": f.strip(), "role": "modified", "confidence": "low"})

    return results


def _detect_patch_status(output_text: str, success_flag: bool | None) -> str:
    """Detect apply_patch status from output text and success flag.

    Returns: 'success', 'failed', or 'unknown'.
    """
    # Check explicit flag first — it takes priority even without output text
    if success_flag is False:
        return "failed"
    if success_flag is True:
        return "success"

    if not output_text:
        return "unknown"
    ol = output_text.lower()
    if "apply_patch verification failed" in ol:
        return "failed"
    if "failed to" in ol or "error" in ol:
        return "failed"
    if "success. updated the following files" in ol:
        return "success"
    if "successfully" in ol and ("patched" in ol or "updated" in ol or "applied" in ol):
        return "success"
    return "unknown"


def _build_apply_patch_title(file_infos: list[dict[str, str]], status: str) -> str:
    """Build human-readable title for apply_patch action."""
    count = len(file_infos)
    prefix = "Пытался изменить" if status == "failed" else "Изменил"

    if count == 0:
        return "Выполнил patch" if status != "failed" else "Пытался выполнить patch"
    elif count == 1:
        basename = file_infos[0]["path"].split("\\")[-1].split("/")[-1]
        return f"{prefix} {basename}"
    else:
        basename = file_infos[0]["path"].split("\\")[-1].split("/")[-1]
        return f"{prefix} {basename} +{count - 1}"

def _classify_shell_command(command: str) -> dict[str, Any]:
    """Classify a shell command string into a human-readable action.

    Returns dict with classified_action, title_ru, action_type, and optional target_path.
    """
    cmd_lower = command.strip().lower() if command else ""

    # ── file read patterns ──
    if any(kw in cmd_lower for kw in ("get-content", "cat ", "type ", "sed -n", "head ", "tail ")):
        import re as _re_sc
        path_m = _re_sc.search(r"""['"]([^'"]+)['"]""", command)
        target = path_m.group(1) if path_m else ""
        basename_lower = target.split("\\")[-1].split("/")[-1].lower() if target else ""
        # Batch candidate: core project context files read together
        batch_keywords = ("readme", "navigation", "project_state", "handoff", "agents",
                          "context", "language_policy", "bug_journal", "agreements")
        if any(kw in basename_lower for kw in batch_keywords):
            return {
                "classified_action": "file_read",
                "action_type": "file_read_batch",
                "title_ru": "Прочитал контекст проекта",
                "target_path": target,
                "is_batch_candidate": True,
                "batch_group": "project_context",
            }
        return {
            "classified_action": "file_read",
            "action_type": "file_read",
            "title_ru": "Прочитал файл",
            "target_path": target,
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── code search patterns ──
    if any(kw in cmd_lower for kw in ("rg ", "select-string", "findstr", "grep ")):
        return {
            "classified_action": "code_search",
            "action_type": "code_search",
            "title_ru": "Искал по коду",
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── test run patterns ──
    if any(kw in cmd_lower for kw in ("python -m unittest", "pytest", "npm test", "npm run test")):
        return {
            "classified_action": "test_run",
            "action_type": "test_run",
            "title_ru": "Запустил тесты",
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── syntax check patterns ──
    # node --check, node -c, python -m py_compile, tsc --noEmit, etc.
    syntax_check_patterns = (
        "node --check", "node -c",
        "python -m py_compile",
        "tsc --noemit", "tsc --no-emit",
        "cargo check",
        "go build",
    )
    if any(p in cmd_lower for p in syntax_check_patterns):
        if "node" in cmd_lower:
            title = "Проверил JavaScript синтаксис"
        elif "python" in cmd_lower:
            title = "Проверил Python синтаксис"
        elif "tsc" in cmd_lower:
            title = "Проверил TypeScript синтаксис"
        elif "cargo" in cmd_lower:
            title = "Проверил Rust синтаксис"
        elif "go" in cmd_lower:
            title = "Проверил Go синтаксис"
        else:
            title = "Проверил синтаксис"
        return {
            "classified_action": "syntax_check",
            "action_type": "syntax_check",
            "title_ru": title,
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── git operations ──
    if any(kw in cmd_lower for kw in ("git status", "git diff", "git log", "git branch", "git add", "git commit", "git show", "git stash")):
        if "git status" in cmd_lower:
            title = "Проверил состояние repo"
        elif "git diff" in cmd_lower:
            if "--stat" in cmd_lower:
                title = "Проверил статистику изменений"
            else:
                title = "Проверил изменения"
        elif "git log" in cmd_lower:
            title = "Посмотрел историю"
        elif "git show" in cmd_lower:
            title = "Посмотрел commit"
        elif "git stash" in cmd_lower:
            title = "Временно сохранил изменения"
        elif "git add" in cmd_lower:
            title = "Добавил файлы в индекс"
        elif "git commit" in cmd_lower:
            title = "Зафиксировал изменения"
        else:
            title = "Git-операция"
        return {
            "classified_action": "git_operation",
            "action_type": "git_operation",
            "title_ru": title,
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── python diagnostic script ──
    if "python " in cmd_lower:
        return {
            "classified_action": "diagnostic_script",
            "action_type": "diagnostic_script",
            "title_ru": "Запустил диагностический скрипт",
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── fallback ──
    return {
        "classified_action": "shell_command",
        "action_type": "shell_command",
        "title_ru": "Выполнил команду",
        "target_path": "",
        "is_batch_candidate": False,
        "batch_group": "",
    }


def _classify_service_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Classify function_call without a shell command (service/instrument calls).

    Returns classification dict compatible with _classify_shell_command output.
    """
    # ── plan update ──
    if tool_name == "update_plan":
        explanation = str(args.get("explanation", ""))
        plan_items_raw = args.get("plan") or args.get("items") or args.get("plan_items") or []
        plan_items: list[str] = []
        if isinstance(plan_items_raw, list):
            for it in plan_items_raw:
                if isinstance(it, dict):
                    # Codex plan format: {step, status}
                    plan_items.append(str(it.get("step", it.get("title", str(it)))))
                else:
                    plan_items.append(str(it))
        return {
            "classified_action": "plan_update",
            "action_type": "plan_update",
            "title_ru": "Обновил план работы",
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
            "plan_explanation": explanation,
            "plan_items": plan_items,
        }

    if tool_name == "todo_write":
        return {
            "classified_action": "todo_write",
            "action_type": "todo_write",
            "title_ru": "Обновил список задач",
            "target_path": "",
            "is_batch_candidate": False,
            "batch_group": "",
        }

    # ── unknown service call ──
    return {
        "classified_action": "service_action",
        "action_type": tool_name,
        "title_ru": "Выполнил служебное действие",
        "target_path": "",
        "is_batch_candidate": False,
        "batch_group": "",
    }


def _build_live_steps(events: list[dict[str, Any]], thread_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse rollout events into step structure with honest token mapping.

    Real rollout schema:
      {type: "turn_context", payload: {model, effort, turn_id, ...}}
      {type: "response_item", payload: {role: "user"|"assistant", content: [{text}]}}
      {type: "response_item", payload: {type: "function_call", name, arguments, call_id}}
      {type: "response_item", payload: {type: "function_call_output", call_id, output}}
      {type: "event_msg", payload: {info: {total_token_usage: {input_tokens, ...}}}}

    v2.1: Collects ALL last_token_usage checkpoints inside each visible step,
    computes full_step_usage as sum, and full_step_cost from full_step_usage.
    Tracks event_range (start_event_index..end_event_index) for auditability.

    v2.5: Captures function_call/function_call_output as live_tool_events
    and builds human_timeline from real tool evidence.
    """
    steps: list[dict[str, Any]] = []
    timeline_events: list[dict[str, Any]] = []
    current_step: dict[str, Any] | None = None
    step_index = 0
    pending_text: list[str] = []
    # Track model/reasoning from turn_context (not present in response_item)
    current_model = "unknown"
    current_reasoning = "unknown"
    last_visible_step_index = 0
    active_task_turn_id = ""
    current_turn_context: dict[str, Any] = {}
    # v2.1: global event index for event_range tracking
    global_event_index = 0
    # v2.1: carry cumulative_after from previous visible step for cumulative_before
    prev_step_cumulative_after: dict[str, Any] | None = None

    def _classify_event(ev: dict[str, Any], ev_idx: int) -> dict[str, Any] | None:
        """Classify a single raw rollout event into an activity item.
        Returns None if the event doesn't represent a meaningful activity."""
        outer_type = ev.get("type", "")
        pl = ev.get("payload", {})
        if not isinstance(pl, dict):
            pl = {}
        ts = str(ev.get("timestamp", ""))

        # ── context_compacted ──
        if outer_type == "event_msg" and str(pl.get("type", "")) == "context_compacted":
            return {
                "event_index": ev_idx, "timestamp": ts,
                "category": "context_compaction",
                "title_ru": "Сжатие контекста",
                "detail": "Codex сжал контекст после этого хода",
                "path": "", "command": "", "status": "ok", "tags": [],
                "token_usage": {"available": False},
            }

        # ── task_started / task_complete ──
        if outer_type == "event_msg":
            etype = str(pl.get("type", ""))
            if etype in ("task_started", "task_complete"):
                return {
                    "event_index": ev_idx, "timestamp": ts,
                    "category": "environment_event",
                    "title_ru": "Задача начата" if etype == "task_started" else "Задача завершена",
                    "detail": f"turn_id={pl.get('turn_id', '')}",
                    "path": "", "command": "", "status": "ok", "tags": [],
                    "token_usage": {"available": False},
                }

        # ── response_item (assistant) ──
        if outer_type == "response_item" and pl.get("role") == "assistant":
            content = pl.get("content", [])
            if not isinstance(content, list):
                return None
            items: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "tool_use":
                    items.extend(_classify_tool_use(block, ev_idx, ts))
                elif block_type == "text":
                    txt = str(block.get("text", ""))
                    if txt.strip():
                        items.extend(_classify_text_activity(txt, ev_idx, ts))
            return items[0] if len(items) == 1 else (items if items else None)

        # ── response_item (user) ──
        if outer_type == "response_item" and pl.get("role") == "user":
            content = pl.get("content", [])
            if not isinstance(content, list):
                return None
            txt = _extract_content_text(content)
            if txt and not _is_internal_live_user_prompt(txt):
                return {
                    "event_index": ev_idx, "timestamp": ts,
                    "category": "model_request",
                    "title_ru": "Запрос пользователя",
                    "detail": txt[:200],
                    "path": "", "command": "", "status": "ok", "tags": [],
                    "token_usage": {"available": False},
                }

    def _classify_tool_use(block: dict[str, Any], ev_idx: int, ts: str) -> list[dict[str, Any]]:
        """Classify a tool_use content block into activity items."""
        tool_name = str(block.get("name", "")).lower()
        tool_input = block.get("input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}

        result: list[dict[str, Any]] = []
        tags: list[str] = []

        # Extract path and command from common input patterns
        file_path = str(tool_input.get("path", tool_input.get("file_path", tool_input.get("filePath", ""))))
        cmd_text = str(tool_input.get("command", tool_input.get("cmd", "")))

        def _make_item(category: str, title_ru: str, detail: str, path: str = "", command: str = "", status: str = "ok", extra_tags: list[str] | None = None) -> dict[str, Any]:
            return {
                "event_index": ev_idx, "timestamp": ts,
                "category": category,
                "tool_name": tool_name,
                "title_ru": title_ru,
                "detail": detail,
                "path": path, "command": command, "status": status,
                "tags": (tags + (extra_tags or [])),
                "token_usage": {"available": False},
            }

        if tool_name in ("read_file", "read", "open_file"):
            result.append(_make_item("file_read", f"read_file", file_path or tool_name, path=file_path))
        elif tool_name in ("write_to_file", "write_file", "create_file"):
            result.append(_make_item("file_write", f"write_to_file", file_path or tool_name, path=file_path))
        elif tool_name in ("edit_file", "apply_diff", "apply_patch", "replace_in_file"):
            result.append(_make_item("file_write", f"edit_file", file_path or tool_name, path=file_path))
        elif tool_name in ("execute_command", "run_command", "shell", "exec", "terminal"):
            detail_text = cmd_text[:200]
            is_git = any(kw in cmd_text.lower() for kw in (
                "git status", "git add", "git commit", "git push", "git diff", "git log",
                "git branch", "git checkout", "git merge", "git pull", "git fetch",
            ))
            is_push = "git push" in cmd_text.lower()
            is_test = any(kw in cmd_text.lower() for kw in (
                "python -m unittest", "pytest", "node --check", "npm test", "npm run test",
            ))
            if is_git:
                cat = "git_operation"
                extra = ["network_or_publish_action"] if is_push else None
            elif is_test:
                cat = "test_run"
                extra = None
            else:
                cat = "shell_command"
                extra = None
            result.append(_make_item(cat, f"execute_command", detail_text or cmd_text[:200], command=cmd_text[:500], extra_tags=extra))
        elif tool_name in ("list_files", "search_files", "search_content", "grep", "find_files"):
            result.append(_make_item("file_read", f"list_files / search",
                str(tool_input.get("path", tool_input.get("target_directory", ""))),
                path=str(tool_input.get("path", ""))))
        elif tool_name in ("web_search", "web_fetch", "tavily_search", "tavily_extract", "fetch_url"):
            result.append(_make_item("network_or_publish_action", f"web_search",
                str(tool_input.get("query", tool_input.get("url", "")))[:200],
                extra_tags=["network"]))
        else:
            result.append(_make_item("unknown", f"Инструмент: {tool_name}",
                str(tool_input)[:200], status="unknown"))

        return result

    def _classify_text_activity(text: str, ev_idx: int, ts: str) -> list[dict[str, Any]]:
        """Heuristic classification from assistant text mention patterns.
        Extracts file paths and command mentions."""
        items: list[dict[str, Any]] = []
        lower = text.lower()

        # Detect git mentions
        git_keywords = ["git status", "git add", "git commit", "git push", "git diff", "git log"]
        for kw in git_keywords:
            if kw in lower:
                items.append({
                    "event_index": ev_idx, "timestamp": ts,
                    "category": "git_operation",
                    "title_ru": "Git-действие",
                    "detail": kw,
                    "path": "", "command": kw, "status": "ok",
                    "tags": ["network_or_publish_action"] if "push" in kw else [],
                    "token_usage": {"available": False},
                })

        # Detect test mentions
        test_kw = ["python -m unittest", "pytest", "node --check", "npm test", "npm run test"]
        for kw in test_kw:
            if kw in lower:
                items.append({
                    "event_index": ev_idx, "timestamp": ts,
                    "category": "test_run",
                    "title_ru": "Запуск тестов",
                    "detail": kw,
                    "path": "", "command": kw, "status": "ok", "tags": [],
                    "token_usage": {"available": False},
                })

        # Extract file paths from text (simplistic: look for .py, .js, .md, .json, .ts extensions)
        import re as _re
        path_pattern = _re.compile(r'[\w/\\.-]+\.(?:py|js|ts|tsx|jsx|md|json|yaml|yml|css|html|bat|txt)')
        seen = set()
        for m in path_pattern.finditer(text):
            p = m.group(0)
            if p not in seen and len(p) > 3:
                seen.add(p)
                items.append({
                    "event_index": ev_idx, "timestamp": ts,
                    "category": "file_read",
                    "title_ru": "Упомянул файл",
                    "detail": p,
                    "path": p, "command": "", "status": "ok", "tags": [],
                    "token_usage": {"available": False},
                })

        return items

    def _make_request_usage_item(req: dict[str, Any], model: str) -> dict[str, Any]:
        """Build a single request_usage_item dict from raw last_token_usage."""
        inp = to_int(req.get("input_tokens"), 0)
        cached = to_int(req.get("cached_tokens"), 0)
        out = to_int(req.get("output_tokens"), 0)
        reas = to_int(req.get("reasoning_tokens"), 0)
        tool = to_int(req.get("tool_tokens"), 0)
        non_cached = max(inp - cached, 0)
        req_costs = _estimate_usage_costs(model, inp, cached, out)
        return {
            "event_index": req.get("event_index", 0),
            "timestamp": str(req.get("timestamp", "")),
            "source": "live_last_token_usage",
            "input_tokens": inp,
            "cached_tokens": cached,
            "non_cached_input_tokens": non_cached,
            "output_tokens": out,
            "reasoning_tokens": reas,
            "tool_tokens": tool,
            "estimated_cost": {
                "total_usd": req_costs.get("estimated_total_cost_usd"),
                "input_usd": req_costs.get("estimated_input_cost_usd"),
                "cached_input_usd": req_costs.get("estimated_cached_input_cost_usd"),
                "output_usd": req_costs.get("estimated_output_cost_usd"),
            },
        }

    def _sum_usage_items(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Sum token fields across a list of usage dicts."""
        result: dict[str, Any] = {
            "source": "sum_last_token_usage_inside_visible_step",
            "request_count": len(items),
            "input_tokens": 0,
            "cached_tokens": 0,
            "non_cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "tool_tokens": 0,
        }
        for it in items:
            for fld in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "tool_tokens"):
                result[fld] = to_int(result.get(fld, 0)) + to_int(it.get(fld, 0))
        result["non_cached_input_tokens"] = max(result["input_tokens"] - result["cached_tokens"], 0)
        return result

    def _make_cumulative_dict(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """Convert a raw total_token_usage snapshot to a cumulative dict."""
        if not isinstance(snapshot, dict):
            return {"available": False}
        inp = to_int(snapshot.get("input_tokens"), 0)
        out = to_int(snapshot.get("output_tokens"), 0)
        has_cum = any(v > 0 for v in (inp, out))
        return {
            "available": has_cum,
            "input_tokens": inp if has_cum else 0,
            "cached_tokens": to_int(snapshot.get("cached_tokens"), 0) if has_cum else 0,
            "output_tokens": out if has_cum else 0,
            "reasoning_tokens": to_int(snapshot.get("reasoning_tokens"), 0) if has_cum else 0,
            "tool_tokens": to_int(snapshot.get("tool_tokens"), 0) if has_cum else 0,
        }

    def _delta_cumulative(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
        """Compute delta between two cumulative dicts."""
        if not after.get("available") or not before.get("available"):
            return {"available": False}
        return {
            "available": True,
            "input_tokens": to_int(after.get("input_tokens"), 0) - to_int(before.get("input_tokens"), 0),
            "cached_tokens": to_int(after.get("cached_tokens"), 0) - to_int(before.get("cached_tokens"), 0),
            "output_tokens": to_int(after.get("output_tokens"), 0) - to_int(before.get("output_tokens"), 0),
            "reasoning_tokens": to_int(after.get("reasoning_tokens"), 0) - to_int(before.get("reasoning_tokens"), 0),
            "tool_tokens": to_int(after.get("tool_tokens"), 0) - to_int(before.get("tool_tokens"), 0),
        }

    def _delta_unattributed(cum_delta: dict[str, Any], full_usage: dict[str, Any]) -> dict[str, Any]:
        """Compute unattributed_delta = cumulative_delta - full_step_usage."""
        if not cum_delta.get("available") or full_usage.get("request_count", 0) == 0:
            return {"available": False}
        return {
            "available": True,
            "input_tokens": to_int(cum_delta.get("input_tokens"), 0) - to_int(full_usage.get("input_tokens"), 0),
            "cached_tokens": to_int(cum_delta.get("cached_tokens"), 0) - to_int(full_usage.get("cached_tokens"), 0),
            "output_tokens": to_int(cum_delta.get("output_tokens"), 0) - to_int(full_usage.get("output_tokens"), 0),
            "reasoning_tokens": to_int(cum_delta.get("reasoning_tokens"), 0) - to_int(full_usage.get("reasoning_tokens"), 0),
            "tool_tokens": to_int(cum_delta.get("tool_tokens"), 0) - to_int(full_usage.get("tool_tokens"), 0),
            "interpretation": "cumulative growth not explained by summed request usage inside visible step",
        }

    def _build_cost_scope(request_count: int) -> dict[str, Any]:
        """Build cost_scope metadata for a step."""
        if request_count == 0:
            return {
                "current_displayed_cost_scope": "unknown",
                "full_step_cost_available": False,
                "request_cost_available": False,
                "mapping_confidence": "not_verified",
            }
        if request_count == 1:
            return {
                "current_displayed_cost_scope": "single_request",
                "full_step_cost_available": True,
                "request_cost_available": True,
                "mapping_confidence": "high",
            }
        return {
            "current_displayed_cost_scope": "full_visible_step",
            "full_step_cost_available": True,
            "request_cost_available": True,
            "mapping_confidence": "high",
        }

    def _extract_text_activity_items(text: str, source_label: str) -> list[dict[str, Any]]:
        """Extract activity items from Russian/English prose text (answer or prompt)."""
        if not text or not text.strip():
            return []
        items: list[dict[str, Any]] = []
        lower = text.lower()

        # ── Russian action phrase patterns ──
        ACTION_PATTERNS = [
            # (regex_or_substring, category, title_ru)
            (r"читаю|прочитал|прочитаю|собираю контекст|соберу контекст|изучаю|изучил|смотрю|посмотрел|проверяю текущ|проверил текущ|проверяю реализацию|добрал|поднял фактическ|сверяю|сверил|анализирую|проанализировал", "file_read", "Изучал контекст / читал файлы"),
            (r"пишу тесты|добавил тест|добавил тесты|добавляю тест|правлю тесты|пишу test|добавил test|обновил тесты|обновляю тесты", "file_write", "Писал / обновлял тесты"),
            (r"правлю |внёс правки|внесены правки|добавил |добавлены |обновил |исправил |исправлено|переписал|переделал|меняю |изменил |поменял ", "file_write", "Вносил правки в код / export"),
            (r"тесты зелёные|тесты прошли|тесты проходят|прогоняю тесты|прогнал тесты|запустил тесты|запускаю тесты|прогнал проверку|прогоняю проверку", "test_run", "Запускал проверки и тесты"),
            (r"node --check|python -m unittest|pytest|npm test|npm run test|прогнал unittest|прогнал node.*check", "test_run", "Запускал проверки и тесты"),
            (r"commit|закоммитил|git push|запушил|git status|git diff|git branch|origin/main|ветк[аиу]|сделал push|сделал commit", "git_operation", "Git-действия"),
            (r"сжатие контекста|compaction|контекст сжат|сжат контекст", "context_compaction", "Сжатие контекста"),
            (r"проверяю.*rollout|проверил.*rollout|смотрю.*rollout|raw rollout|live thread|живую сессию|live session", "file_read", "Проверял raw rollout / live thread"),
            (r"проверяю.*monitor|проверил.*monitor|смотрю.*monitor|monitor.*код|monitor.*code|codex.token.monitor", "file_read", "Проверял код monitor"),
            (r"handoff|ограничени[ея] задач|hard constraint|читаю handoff|прочитал handoff", "file_read", "Читал handoff и ограничения"),
            (r"bug.journal|bug_journal|баги|bug", "file_read", "Проверял bug journal"),
            (r"export|экспорт|copy.*step|copy.*session|session.*json|session.*md", "file_write", "Обновлял export/copy"),
            (r"ui|фронтенд|app\.js|index\.html|styles\.css|карточк[ауи] шага|step card", "file_write", "Правил UI / фронтенд"),
            (r"audit|аудит", "file_write", "Обновлял audit"),
            (r"verification|проверк[ауи]|verify|верифик", "test_run", "Делал verification"),
        ]

        for pattern, category, title_ru in ACTION_PATTERNS:
            import re as _re2
            if _re2.search(pattern, text):
                # Find the matching context snippet
                m = _re2.search(pattern, text)
                snippet = text[max(0, m.start() - 30):m.end() + 30] if m else pattern
                items.append({
                    "event_index": 0, "timestamp": "",
                    "category": category,
                    "tool_name": f"text:{source_label}",
                    "title_ru": title_ru,
                    "detail": snippet.strip()[:200],
                    "path": "", "command": "", "status": "reported_by_agent",
                    "tags": [],
                    "token_usage": {"available": False},
                })

        # ── Extract file paths from text ──
        import re as _re3
        path_pattern = _re3.compile(
            r'(?:scripts|static|tests|config|canon|docs|references|ideas|\.ai)/[\w/\-\.]+\.(?:py|js|ts|tsx|jsx|md|json|yaml|yml|css|html|bat|txt)'
            r'|[\w_\-]+\.(?:py|js|md|json|css|html)'
        )
        seen_paths = set()
        for m in path_pattern.finditer(text):
            p = m.group(0)
            if p not in seen_paths and len(p) > 4 and not p.startswith("http"):
                seen_paths.add(p)
                items.append({
                    "event_index": 0, "timestamp": "",
                    "category": "file_read",
                    "tool_name": f"text:{source_label}",
                    "title_ru": "Упомянутый файл",
                    "detail": p,
                    "path": p, "command": "", "status": "reported_by_agent",
                    "tags": [],
                    "token_usage": {"available": False},
                })

        # ── Extract command mentions ──
        cmd_pattern = _re3.compile(
            r'(?:python\s+-m\s+unittest[\s\w\.\-]+)'
            r'|(?:node\s+--check[\s\w\.\-/]+)'
            r'|(?:git\s+(?:push|commit|status|diff|log|branch)[\s\w\.\-/]*)'
            r'|(?:npm\s+(?:test|run\s+test)[\s\w\.\-/]*)'
            r'|(?:pytest[\s\w\.\-/]*)'
        )
        for m in cmd_pattern.finditer(text):
            c = m.group(0).strip()
            items.append({
                "event_index": 0, "timestamp": "",
                "category": "shell_command",
                "tool_name": f"text:{source_label}",
                "title_ru": "Команда",
                "detail": c,
                "path": "", "command": c, "status": "reported_by_agent",
                "tags": [],
                "token_usage": {"available": False},
            })

        return items

    def _enrich_timeline_items(
        items: list[dict[str, Any]],
        lte: list[dict[str, Any]],
        tool_groups: list[dict[str, Any]],
        request_usage_items: list[dict[str, Any]],
        assigned_indices: set[int],
        step_model: str = "unknown",
    ) -> None:
        """v2.7: Add details, files, commands, raw_evidence, linked_ai_call to each timeline item."""
        # Build lookup: event_index -> tool_event
        ev_map: dict[int, dict[str, Any]] = {}
        for te in lte:
            ei = te.get("event_index", 0)
            if ei:
                ev_map[ei] = te

        # Build lookup: tool_group index -> item index (which timeline item owns this group)
        tg_to_item: dict[int, int] = {}
        for item in items:
            tev = item.get("tool_evidence", {})
            if tev.get("available"):
                for ev_idx in tev.get("event_indices", []):
                    for gi, tg in enumerate(tool_groups):
                        if ev_idx in tg.get("event_indices", []):
                            tg_to_item[gi] = item.get("index", 0)

        for item in items:
            row_type = item.get("row_type", "")
            tev = item.get("tool_evidence", {})
            has_tools = tev.get("available", False)
            is_approx = row_type == "ai_call_only"
            is_tool_only = row_type == "action_only"
            ai_idx = item.get("linked_model_request_index")

            # ── linked_ai_call ──
            linked_ai_call = None
            if ai_idx and ai_idx <= len(request_usage_items):
                rui = request_usage_items[ai_idx - 1]
                rc = rui.get("estimated_cost", {}) or {}
                linked_ai_call = {
                    "ai_index": ai_idx,
                    "event_index": rui.get("event_index", 0),
                    "timestamp": rui.get("timestamp", ""),
                    "cost_total_usd": rc.get("total_usd"),
                    "input_tokens": rui.get("input_tokens", 0),
                    "cached_tokens": rui.get("cached_tokens", 0),
                    "non_cached_input_tokens": max(0, rui.get("input_tokens", 0) - rui.get("cached_tokens", 0)),
                    "output_tokens": rui.get("output_tokens", 0),
                    "reasoning_tokens": rui.get("reasoning_tokens", 0),
                }
            item["linked_ai_call"] = linked_ai_call

            # ── details ──
            if has_tools or is_tool_only:
                item["details"] = {
                    "available": True,
                    "summary_ru": "Этап подтверждён raw tool events (function_call/function_call_output из rollout).",
                    "confidence_explanation_ru": "high / raw: действие подтверждено function_call/function_call_output из raw rollout.",
                    "cost_explanation_ru": "Cost относится к AI-осмыслению результата tool events, а не к самому выполнению команд.",
                    "source": "live_tool_events",
                }
            elif is_approx:
                item["details"] = {
                    "available": True,
                    "summary_ru": "Нет прямых tool events для этого AI call. Название получено приблизительно по соседним событиям / тексту ответа.",
                    "confidence_explanation_ru": "low / approx: прямое raw-подтверждение отсутствует.",
                    "cost_explanation_ru": "Cost подтверждён request_usage_item, но человекочитаемое действие приблизительное.",
                    "source": "fallback_from_neighbor_context",
                }
            else:
                item["details"] = {"available": False}

            # ── files ──
            files: list[dict[str, Any]] = []
            if has_tools:
                ev_indices = tev.get("event_indices", [])
                seen_paths: set[str] = set()
                # v2.10: file_read dedup — track read_count and ranges per path
                read_dedup: dict[str, dict[str, Any]] = {}
                for ev_idx in ev_indices:
                    te = ev_map.get(ev_idx)
                    if not te:
                        continue
                    is_apply_patch = te.get("classified_action") == "apply_patch"
                    is_file_read = te.get("classified_action") in ("file_read", "file_read_batch")

                    # v2.10: use patch_file_infos for apply_patch (with role), else target_paths
                    if is_apply_patch:
                        pfi_list = te.get("patch_file_infos", [])
                        for pfi in pfi_list:
                            tp = pfi.get("path", "").strip()
                            if not tp or tp in seen_paths:
                                continue
                            seen_paths.add(tp)
                            files.append({
                                "path": tp,
                                "display_name": tp.split("\\")[-1].split("/")[-1] if tp else "",
                                "operation": pfi.get("role", "modified"),
                                "source": "patch_header",
                                "confidence": pfi.get("confidence", "high"),
                                "event_index": ev_idx,
                                "call_id": te.get("call_id", ""),
                                "output_found": te.get("output_found", False),
                                "output_event_index": te.get("output_event_index") or 0,
                                "output_length_chars": te.get("output_length", 0) if te.get("output_found") else None,
                            })
                    elif is_file_read:
                        # Dedup file reads by path
                        tp = te.get("target_path", "").strip()
                        if not tp:
                            continue
                        if tp in read_dedup:
                            rd = read_dedup[tp]
                            rd["read_count"] += 1
                            # Extract line range from command if present
                            cmd = te.get("command", "")
                            import re as _re_range
                            range_m = _re_range.search(r'\[(\d+)\.\.(\d+)\]', cmd)
                            if range_m:
                                rd["ranges"].append(f"{range_m.group(1)}..{range_m.group(2)}")
                            if te.get("output_length", 0):
                                rd["total_output_chars"] = (rd.get("total_output_chars") or 0) + te.get("output_length", 0)
                        else:
                            read_dedup[tp] = {
                                "path": tp,
                                "display_name": tp.split("\\")[-1].split("/")[-1],
                                "operation": "read",
                                "read_count": 1,
                                "ranges": [],
                                "source": "function_call",
                                "confidence": "high",
                                "event_index": ev_idx,
                                "call_id": te.get("call_id", ""),
                                "total_output_chars": te.get("output_length", 0) if te.get("output_found") else None,
                                "output_found": te.get("output_found", False),
                            }
                            cmd = te.get("command", "")
                            import re as _re_range2
                            range_m = _re_range2.search(r'\[(\d+)\.\.(\d+)\]', cmd)
                            if range_m:
                                read_dedup[tp]["ranges"].append(f"{range_m.group(1)}..{range_m.group(2)}")
                    else:
                        tps = te.get("target_paths") or ([te.get("target_path", "")] if te.get("target_path") else [])
                        for tp in tps:
                            tp = tp.strip()
                            if not tp or tp in seen_paths:
                                continue
                            seen_paths.add(tp)
                            op = "modified"
                            files.append({
                                "path": tp,
                                "display_name": tp.split("\\")[-1].split("/")[-1] if tp else "",
                                "operation": op,
                                "source": "function_call",
                                "confidence": "high",
                                "event_index": ev_idx,
                                "call_id": te.get("call_id", ""),
                                "output_found": te.get("output_found", False),
                                "output_event_index": te.get("output_event_index") or 0,
                                "output_length_chars": te.get("output_length", 0) if te.get("output_found") else None,
                            })

                # Add deduplicated file reads
                for rd in read_dedup.values():
                    if rd["read_count"] > 1:
                        rd["operation"] = "read_batch"
                    # v2.10: map total_output_chars → output_length_chars for context_contribution
                    if "total_output_chars" in rd and "output_length_chars" not in rd:
                        rd["output_length_chars"] = rd["total_output_chars"]
                    files.append(rd)

            item["files"] = files if files else None

            # ── commands ──
            commands: list[dict[str, Any]] = []
            if has_tools:
                ev_indices = tev.get("event_indices", [])
                for ev_idx in ev_indices:
                    te = ev_map.get(ev_idx)
                    if not te:
                        continue
                    cmd = te.get("command", "")
                    if cmd or te.get("action_type") == "shell_command":
                        # v2.9: use linked function_call_output data (already attached by processor)
                        output_found = te.get("output_found", False)
                        output_preview = te.get("output_preview", "")
                        output_length = te.get("output_length", 0)
                        exit_code = te.get("output_exit_code") if te.get("output_exit_code") is not None else te.get("exit_code")
                        commands.append({
                            "command": cmd,
                            "workdir": te.get("workdir", ""),
                            "classified_action": te.get("classified_action", ""),
                            "source": "function_call",
                            "confidence": "high",
                            "event_index": ev_idx,
                            "call_id": te.get("call_id", ""),
                            "output_found": output_found,
                            "output_event_index": te.get("output_event_index") or 0,
                            "exit_code": exit_code,
                            "output_preview": output_preview,
                            "output_length_chars": output_length if output_found else None,
                        })
            item["commands"] = commands if commands else None

            # ── v2.9: context contribution for files/commands (NOT cost) ──
            lai = item.get("linked_ai_call")
            if lai and (files or commands):
                total_cost = lai.get("cost_total_usd") or 0
                total_input = lai.get("input_tokens", 0)
                total_cached = lai.get("cached_tokens", 0)
                total_nc = lai.get("non_cached_input_tokens", 0)
                total_output = lai.get("output_tokens", 0)
                total_reasoning = lai.get("reasoning_tokens", 0)
                ai_call_idx = lai.get("ai_index", 0)

                total_group_out_len = 0
                file_read_paths: set[str] = {f.get("path", "") for f in (files or []) if f.get("path")}
                for f in (files or []):
                    total_group_out_len += f.get("output_length_chars") or 0
                for c in (commands or []):
                    # Skip file_read/file_read_batch commands — their output is already counted via file objects
                    if c.get("classified_action") in ("file_read", "file_read_batch"):
                        continue
                    total_group_out_len += c.get("output_length_chars") or 0

                def _make_context_contribution(obj: dict[str, Any]) -> dict[str, Any]:
                    out_len = obj.get("output_length_chars") or 0
                    est_tokens = round(out_len / 4) if out_len > 0 else None
                    share = round(out_len / total_group_out_len, 4) if total_group_out_len > 0 and out_len > 0 else None
                    contrib: dict[str, Any] = {
                        "individual_cost_available": False,
                        "included_in_ai_call": ai_call_idx,
                        "linked_ai_total_cost_usd": total_cost,
                        "linked_ai_input_tokens": total_input,
                        "linked_ai_non_cached_input_tokens": total_nc,
                        "linked_ai_cached_tokens": total_cached,
                        "linked_ai_output_tokens": total_output,
                        "linked_ai_reasoning_tokens": total_reasoning,
                        "output_length_chars": out_len if out_len > 0 else None,
                        "estimated_text_tokens": est_tokens,
                        "share_of_tool_output_text": share,
                    }
                    if out_len > 0:
                        contrib["note_ru"] = "Вклад в текстовый контекст этапа по размеру вывода. Не telemetry-стоимость."
                    else:
                        contrib["note_ru"] = "Нет данных для оценки вклада в контекст."
                    return contrib

                for f in (files or []):
                    f["context_contribution"] = _make_context_contribution(f)
                for c in (commands or []):
                    c["context_contribution"] = _make_context_contribution(c)

                # ── v2.12: token cost breakdown + estimated file contribution ──
                if lai and total_group_out_len > 0:
                    pricing_all = _load_pricing()
                    # _load_pricing returns the prices_per_1m dict directly; find model by prefix match
                    model_prices: dict[str, float] = {}
                    matched_model = ""
                    if step_model and pricing_all:
                        # 1) exact match
                        if step_model in pricing_all:
                            model_prices = pricing_all[step_model]
                            matched_model = step_model
                        else:
                            # 2) prefix match: e.g. "gpt-5.4" matches "gpt-5.4-thinking-high"
                            for config_key in sorted(pricing_all.keys(), key=len, reverse=True):
                                if step_model.startswith(config_key):
                                    model_prices = pricing_all[config_key]
                                    matched_model = config_key
                                    break
                    input_price = model_prices.get("input")
                    cached_price = model_prices.get("cached_input")
                    output_price = model_prices.get("output")

                    if input_price and cached_price and output_price:
                        nc_tokens = lai.get("non_cached_input_tokens", 0)
                        cached_tokens = lai.get("cached_tokens", 0)
                        out_tokens = lai.get("output_tokens", 0)

                        new_input_cost = nc_tokens * input_price / 1_000_000
                        cached_cost = cached_tokens * cached_price / 1_000_000
                        output_cost = out_tokens * output_price / 1_000_000
                        breakdown_total = new_input_cost + cached_cost + output_cost

                        # Read currency from raw config file (pricing_all is only prices_per_1m)
                        raw_cfg = read_json_safe(CONFIG_DIR / "token_pricing.json") or {}
                        currency = raw_cfg.get("currency", "USD")

                        tcb: dict[str, Any] = {
                            "available": True,
                            "pricing_source": "token_pricing_json",
                            "currency": currency,
                            "matched_model_key": matched_model or step_model,
                            "items": [
                                {"kind": "new_input", "tokens": nc_tokens, "price_per_million": input_price, "cost_usd": round(new_input_cost, 6)},
                                {"kind": "cached_input", "tokens": cached_tokens, "price_per_million": cached_price, "cost_usd": round(cached_cost, 6)},
                                {"kind": "output", "tokens": out_tokens, "price_per_million": output_price, "cost_usd": round(output_cost, 6)},
                            ],
                            "reasoning_note": "Reasoning tokens are included in output pricing.",
                            "total_from_breakdown_usd": round(breakdown_total, 6),
                            "telemetry_total_usd": round(lai.get("cost_total_usd") or 0, 6),
                        }
                        item["token_cost_breakdown"] = tcb

                        # Estimated file contribution to new_input cost
                        if new_input_cost > 0:
                            for f in (files or []):
                                cc = f.get("context_contribution") or {}
                                if cc.get("estimated_text_tokens") and total_group_out_len > 0:
                                    share = (cc.get("estimated_text_tokens") or 0) / sum(
                                        (ff.get("context_contribution") or {}).get("estimated_text_tokens") or 0
                                        for ff in (files or [])
                                    ) if sum((ff.get("context_contribution") or {}).get("estimated_text_tokens") or 0 for ff in (files or [])) > 0 else 0
                                    cc["estimated_new_input_cost_usd"] = round(new_input_cost * share, 6)
                                    cc["note_ru"] = "Оценка: распределение New input cost пропорционально объёму tool-output текста. Не точная цена файла."

            # ── raw_evidence ──
            raw_evidence: list[dict[str, Any]] = []
            if has_tools:
                ev_indices = tev.get("event_indices", [])
                for ev_idx in ev_indices:
                    te = ev_map.get(ev_idx)
                    if not te:
                        continue
                    is_apply_patch = te.get("classified_action") == "apply_patch"
                    re = {
                        "event_index": ev_idx,
                        "timestamp": te.get("timestamp", ""),
                        "payload_type": te.get("payload_type", "function_call"),
                        "kind": "tool_call" if te.get("payload_type") == "function_call" else "tool_output",
                        "tool_name": te.get("tool_name", ""),
                        "call_id": te.get("call_id", ""),
                    }
                    if is_apply_patch and te.get("kind") == "tool_call":
                        re["raw_arguments_preview"] = te.get("raw_arguments_preview", "")[:500]
                        re["output_found"] = te.get("output_found", False)
                        re["output_length"] = te.get("output_length", 0)
                        re["success"] = te.get("success", None)
                        re["output_preview"] = te.get("output_preview", "")[:200]
                    raw_evidence.append(re)
            elif linked_ai_call:
                raw_evidence.append({
                    "event_index": linked_ai_call["event_index"],
                    "timestamp": linked_ai_call["timestamp"],
                    "payload_type": "model_response",
                    "kind": "ai_response",
                    "tool_name": "",
                    "call_id": "",
                })
            item["raw_evidence"] = raw_evidence if raw_evidence else None

            # ── v2.10: apply_patch_output for items with apply_patch files ──
            if item.get("action_type") == "apply_patch" or any(
                f.get("source") == "patch_header" for f in (files or [])
            ):
                ev_indices = tev.get("event_indices", [])
                total_out_len = 0
                total_patch_input = 0
                all_success: list[bool] = []
                args_previews: list[str] = []
                patch_statuses: list[str] = []
                for ev_idx in ev_indices:
                    te = ev_map.get(ev_idx)
                    if not te:
                        continue
                    if te.get("kind") == "tool_call":
                        rap = te.get("raw_arguments_preview", "")
                        if rap:
                            args_previews.append(rap[:500])
                        total_patch_input += te.get("patch_input_chars", 0)
                        if te.get("output_found"):
                            total_out_len += te.get("output_length", 0)
                            s = te.get("success")
                            if s is not None:
                                all_success.append(s)
                        ps = te.get("patch_status", "unknown")
                        if ps != "unknown":
                            patch_statuses.append(ps)
                patch_data: dict[str, Any] = {
                    "available": True,
                    "output_length": total_out_len,
                    "patch_input_chars": total_patch_input,
                    "estimated_patch_tokens": max(1, total_patch_input // 4) if total_patch_input else None,
                    "estimated_tool_output_tokens": max(1, total_out_len // 4) if total_out_len else None,
                    "cost_note_ru": "Стоимость относится к AI-обращению целиком. Telemetry не содержит отдельной стоимости файла или patch output. Размер patch input/tool output — диагностический объём текста, не цена.",
                }
                if all_success:
                    patch_data["all_successful"] = all(all_success)
                    patch_data["any_failed"] = not all(all_success)
                if patch_statuses:
                    patch_data["patch_status"] = patch_statuses[-1]
                if args_previews:
                    patch_data["args_preview"] = args_previews[0][:500]
                patch_data["total_files"] = len(files) if files else 0
                item["apply_patch_data"] = patch_data

            # ── v2.10: plan_update details ──
            if item.get("display_title_ru", "").startswith("Обновил план"):
                ev_indices = tev.get("event_indices", [])
                for ev_idx in ev_indices:
                    te = ev_map.get(ev_idx)
                    if not te:
                        continue
                    if te.get("classified_action") == "plan_update":
                        item["plan_update_data"] = {
                            "available": True,
                            "explanation": te.get("plan_explanation", ""),
                            "plan_items": te.get("plan_items", []),
                            "note_ru": "Это служебное действие Codex update_plan. Оно не читает файлы и не запускает команды. Стоимость относится к AI-обращению, которое сформировало/обновило план.",
                        }
                        break

            # ── full_title_ru ──
            display_title = item.get("display_title_ru", "")
            if len(display_title) > 50:
                item["full_title_ru"] = display_title
                # Truncate display title for table
                item["display_title_ru"] = display_title[:47] + "…"
            else:
                item["full_title_ru"] = display_title

    def _build_smart_fallback_title(
        timeline_items: list[dict[str, Any]],
        rui_idx: int,
        rui: dict[str, Any],
        sia_stages: list[dict[str, Any]] | None = None,
        total_ai_calls: int = 0,
    ) -> tuple[str, str, str]:
        """v2.6: Build a smarter fallback title for AI call without tool evidence.

        Uses neighbor context from human_timeline_items, possible_stage_ru hints,
        token usage signals, and output size to pick a better title.

        Returns (title, recognition_confidence, recognition_source).
        """
        # Default fallback
        default_title = "Осмыслил промежуточный контекст"
        default_conf = "not_verified"
        default_src = "none"

        # Gather hints
        prev_action = ""
        next_action = ""
        all_actions: list[str] = []
        for it in timeline_items:
            t = it.get("display_title_ru") or it.get("recognized_action_ru", "")
            if t:
                all_actions.append(t)
        if all_actions:
            prev_action = all_actions[-1] if all_actions else ""

        output_tokens = rui.get("output_tokens", 0)
        non_cached = max(0, rui.get("input_tokens", 0) - rui.get("cached_tokens", 0))

        # Check possible_stage from text stages
        stage_hint = ""
        for s in (sia_stages or []):
            if (rui_idx + 1) in s.get("request_indices", []):
                stage_hint = s.get("title_ru", "")
                break

        # ── Rule-based smart titles ──
        title = default_title
        conf = default_conf
        src = default_src

        # 0. Last AI-call with visible output → final report / assistant message
        is_last = total_ai_calls > 0 and rui_idx == total_ai_calls - 1
        if is_last and output_tokens > 0:
            title = "Сформулировал итоговый отчёт"
            conf = "low"
            src = "last_ai_call_with_output"
        # 1. Large output → detailed conclusion
        elif output_tokens > 1500:
            title = "Сформулировал подробный вывод"
            conf = "low"
            src = "output_tokens_signal"
        # 2. High non-cached input → processing large context
        elif non_cached > 50000:
            title = "Обработал большой объём контекста"
            conf = "low"
            src = "non_cached_signal"
        # 3. After diagnostic/check pattern
        elif any(kw in prev_action for kw in ("Проверил", "Запустил тесты", "Запустил диагностический")):
            title = "Осмыслил результат проверки"
            conf = "low"
            src = "neighbor_prev_diagnostic"
        # 4. After file read / search
        elif any(kw in prev_action for kw in ("Прочитал", "Искал по коду")):
            title = "Анализировал прочитанный код"
            conf = "low"
            src = "neighbor_prev_read"
        # 5. After file write / patch
        elif any(kw in prev_action for kw in ("внёс правки", "Исправил")):
            title = "Проверил внесённые правки"
            conf = "low"
            src = "neighbor_prev_write"
        # 6. Stage hint from answer text
        elif stage_hint:
            title = f"Осмыслил этап: {stage_hint[:40]}"
            conf = "low"
            src = "stage_text_hint"
        # Keep default
        else:
            title = default_title

        return title, conf, src

    def _build_agent_activity(
        step: dict[str, Any],
        raw_items: list[dict[str, Any]],
        full_step_usage: dict[str, Any],
        event_range: dict[str, Any],
        request_usage_items: list[dict[str, Any]],
        live_tool_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Build agent_activity from raw events + prompt/answer text mining + live tool events.

        v2.5: Uses live_tool_events to build human_timeline with real tool evidence.
        """
        prompt_text = (step.get("user_prompt") or {}).get("text", "")
        answer_text = (step.get("assistant_answer") or {}).get("text", "")

        # Extract from text
        prompt_items = _extract_text_activity_items(prompt_text, "prompt")
        answer_items = _extract_text_activity_items(answer_text, "answer")

        # Merge: raw events first, then answer text, then prompt text
        all_items: list[dict[str, Any]] = list(raw_items) if raw_items else []
        all_items.extend(answer_items)
        all_items.extend(prompt_items)

        if not all_items:
            step["agent_activity"] = {
                "available": False,
                "activity_sources": {"raw_events_used": bool(raw_items), "answer_text_used": False, "prompt_text_used": False},
            }
            return

        # Count by category
        counts: dict[str, int] = {
            "model_requests": 0, "file_reads": 0, "file_writes": 0,
            "shell_commands": 0, "git_operations": 0, "test_runs": 0,
            "network_or_publish_actions": 0, "context_compactions": 0,
            "internal_prompts": 0, "environment_events": 0, "unknown_events": 0,
        }
        category_map = {
            "model_request": "model_requests", "file_read": "file_reads",
            "file_write": "file_writes", "shell_command": "shell_commands",
            "git_operation": "git_operations", "test_run": "test_runs",
            "network_or_publish_action": "network_or_publish_actions",
            "context_compaction": "context_compactions",
            "internal_prompt": "internal_prompts",
            "environment_event": "environment_events",
        }
        for item in all_items:
            key = category_map.get(item.get("category", "unknown"), "unknown_events")
            counts[key] = counts.get(key, 0) + 1

        # Count raw events that weren't classified by event-based extractor
        raw_count = event_range.get("raw_events_count", 0)
        event_classified_raw = sum(1 for it in raw_items if it.get("category") != "unknown")
        unclassified_raw = max(0, raw_count - len(raw_items)) if raw_items else raw_count

        # Summary lines
        summary_lines: list[str] = []
        answer_summary = [it for it in answer_items if it["category"] not in ("file_read",)]
        prompt_summary = [it for it in prompt_items if it["category"] not in ("file_read",)]
        seen_summaries: set[str] = set()
        for it in answer_summary + prompt_summary:
            t = it["title_ru"]
            if t not in seen_summaries:
                seen_summaries.add(t)
                summary_lines.append(t)
        if not summary_lines:
            if counts["file_writes"]:
                summary_lines.append(f"Вносил правки в код")
            if counts["test_runs"]:
                summary_lines.append("Запускал проверки и тесты")
            if counts["file_reads"]:
                summary_lines.append("Изучал контекст и код")
        if not summary_lines:
            summary_lines.append("Активность частично детализирована по тексту ответа")

        # Paths and commands
        paths: list[str] = []
        cmds: list[str] = []
        for it in all_items:
            p = it.get("path", "").strip()
            if p and p not in paths:
                paths.append(p)
            c = it.get("command", "").strip()
            if c and c not in cmds:
                cmds.append(c)

        confidence = "medium"
        if raw_items:
            confidence = "medium"
        else:
            confidence = "low"

        # ── v2.3: step_internal_actions — neutral titles, possible_stage_ru ──
        step_internal_actions: list[dict[str, Any]] = []
        meaningful_text = [ti for ti in (prompt_items + answer_items)
                          if ti.get("category") != "context_compaction"]
        all_text = prompt_items + answer_items
        rui_paths: list[str] = []
        rui_cmds: list[str] = []
        for ti in all_text:
            tp = ti.get("path", "").strip()
            if tp and tp not in rui_paths:
                rui_paths.append(tp)
            tc = ti.get("command", "").strip()
            if tc and tc not in rui_cmds:
                rui_cmds.append(tc)

        # Build stages from answer text — group by unique activity patterns
        stages: list[dict[str, Any]] = []
        seen_titles: list[str] = []
        for ti in meaningful_text:
            t = ti.get("title_ru", "")
            if t and t not in seen_titles:
                seen_titles.append(t)
        if seen_titles:
            # Create approximate stage grouping
            stage_map: dict[int, dict[str, Any]] = {}
            for idx, rui in enumerate(request_usage_items):
                # Assign request to nearest stage by proportional split
                stage_idx = min(len(seen_titles) - 1, int(idx * len(seen_titles) / max(1, len(request_usage_items))))
                if stage_idx not in stage_map:
                    stage_map[stage_idx] = {
                        "stage_index": stage_idx + 1,
                        "title_ru": seen_titles[stage_idx],
                        "request_indices": [],
                        "input_tokens": 0, "cached_tokens": 0,
                        "non_cached_input_tokens": 0, "output_tokens": 0,
                        "cost_total_usd": 0.0,
                    }
                sm = stage_map[stage_idx]
                sm["request_indices"].append(idx + 1)
                sm["input_tokens"] += rui.get("input_tokens", 0)
                sm["cached_tokens"] += rui.get("cached_tokens", 0)
                sm["output_tokens"] += rui.get("output_tokens", 0)
                ce = rui.get("estimated_cost", {})
                if isinstance(ce, dict) and ce.get("total_usd"):
                    sm["cost_total_usd"] += float(ce["total_usd"])
            for si in sorted(stage_map):
                sm = stage_map[si]
                ri = sm["request_indices"]
                sm["non_cached_input_tokens"] = max(0, sm["input_tokens"] - sm["cached_tokens"])
                sm["request_range"] = f"{ri[0]}-{ri[-1]}" if len(ri) > 1 else str(ri[0])
                sm["confidence"] = "low"
                sm["source"] = "answer_text_inferred"
                sm["notes_ru"] = ["Этапы построены по тексту ответа агента; точная привязка каждого внутреннего запроса не подтверждена."]
                stages.append(sm)

        fallback_titles = [
            "Внутренний запрос модели",
            "Промежуточный запрос модели",
        ]

        for idx, rui in enumerate(request_usage_items):
            inp = rui.get("input_tokens", 0)
            cached = rui.get("cached_tokens", 0)
            out = rui.get("output_tokens", 0)
            nc = max(inp - cached, 0)

            # Neutral title — NEVER use guessed text for low-confidence
            title = f"{fallback_titles[idx % len(fallback_titles)]} #{idx + 1}"

            # Find possible stage
            possible_stage = ""
            stage_conf = "not_verified"
            for s in stages:
                if (idx + 1) in s["request_indices"]:
                    possible_stage = s["title_ru"]
                    stage_conf = s.get("confidence", "low")
                    break

            # Expensive reason
            exp_reason = ""
            if nc > 50000:
                exp_reason = f"высокий non-cached input ({nc:,})"
            elif out > 5000:
                exp_reason = f"высокий output ({out:,})"
            elif inp > 200000:
                exp_reason = f"большой input ({inp:,})"

            cost_est = rui.get("estimated_cost", {})
            if not isinstance(cost_est, dict):
                cost_est = {}

            step_internal_actions.append({
                "index": idx + 1,
                "event_index": rui.get("event_index", 0),
                "timestamp": rui.get("timestamp", ""),
                "title_ru": title,
                "possible_stage_ru": possible_stage,
                "title_confidence": "not_verified",
                "stage_confidence": stage_conf,
                "action_category": "model_request",
                "source": "raw_event",
                "confidence": "low",
                "is_context_compaction": False,
                "usage": {
                    "available": True,
                    "input_tokens": inp,
                    "cached_tokens": cached,
                    "non_cached_input_tokens": nc,
                    "output_tokens": out,
                    "reasoning_tokens": rui.get("reasoning_tokens", 0),
                },
                "cost": {
                    "available": cost_est.get("total_usd") is not None,
                    "total_usd": cost_est.get("total_usd"),
                    "input_usd": cost_est.get("input_usd"),
                    "cached_input_usd": cost_est.get("cached_input_usd"),
                    "output_usd": cost_est.get("output_usd"),
                },
                "expensive_reason": exp_reason,
                "related_files": rui_paths[:5],
                "related_commands": rui_cmds[:3],
                "notes_ru": [],
            })

        top_expensive = sorted(
            [a for a in step_internal_actions if a["cost"]["total_usd"] is not None],
            key=lambda a: a["cost"]["total_usd"], reverse=True,
        )[:10]

        model_events_count = counts.get("model_requests", 0) + counts.get("internal_prompts", 0)
        requests_with_usage = len(request_usage_items)

        # ── v2.5: human_timeline from real tool evidence ──
        lte = live_tool_events if live_tool_events else []
        human_timeline_items: list[dict[str, Any]] = []

        # 1. Group tool events into batches before each AI call
        # For each AI call (request_usage_item), find preceding tool_events
        # that haven't been assigned to an earlier AI call.

        # First, build tool event groups: batch consecutive batch_candidate events
        # with same batch_group into one group
        tool_groups: list[dict[str, Any]] = []
        current_group: dict[str, Any] | None = None
        for te in lte:
            is_batch = te.get("is_batch_candidate", False)
            bg = te.get("batch_group", "")

            if current_group and is_batch and current_group.get("batch_group") == bg:
                # Extend existing batch group
                current_group["tool_events"].append(te)
                current_group["event_indices"].append(te.get("event_index", 0))
                if te.get("target_path") and te["target_path"] not in current_group["target_paths"]:
                    current_group["target_paths"].append(te["target_path"])
                if te.get("command") and te["command"] not in current_group["commands"]:
                    current_group["commands"].append(te["command"])
            else:
                # Start new group
                current_group = {
                    "batch_group": bg if is_batch else "",
                    "is_batch": is_batch,
                    "action_type": te.get("action_type", ""),
                    "classified_action": te.get("classified_action", ""),
                    "title_ru": te.get("title_ru", ""),
                    "tool_events": [te],
                    "event_indices": [te.get("event_index", 0)],
                    "first_event_index": te.get("event_index", 0),
                    "last_event_index": te.get("event_index", 0),
                    "timestamp": te.get("timestamp", ""),
                    "target_paths": [te.get("target_path", "")] if te.get("target_path") else [],
                    "commands": [te.get("command", "")] if te.get("command") and not is_batch else [],
                    "batch_objects": [],
                }
                tool_groups.append(current_group)

        # Extract batch objects (filenames) from batch groups
        for tg in tool_groups:
            if tg["is_batch"] and tg["target_paths"]:
                tg["batch_objects"] = [
                    p.split("\\")[-1].split("/")[-1] for p in tg["target_paths"] if p
                ][:10]

        # Track which tool groups have been assigned (for cost-linking)
        assigned_group_indices: set[int] = set()

        # 2. v2.5-fix: interval-based linking — all tool groups between AI calls
        prev_ai_ev = 0  # step start
        for rui_idx, rui in enumerate(request_usage_items):
            rui_ev = rui.get("event_index", 0)

            # Find ALL tool groups whose last_event_index is between prev_ai_ev and rui_ev
            interval_groups: list[int] = []
            for gi, tg in enumerate(tool_groups):
                if gi in assigned_group_indices:
                    continue
                if prev_ai_ev < tg["last_event_index"] < rui_ev:
                    interval_groups.append(gi)

            rui_cost = rui.get("estimated_cost", {})
            if not isinstance(rui_cost, dict):
                rui_cost = {}

            if interval_groups:
                # Mark all as assigned
                for gi in interval_groups:
                    assigned_group_indices.add(gi)

                # Aggregate: first group determines title and timestamp
                first_tg = tool_groups[interval_groups[0]]
                all_ev_indices: list[int] = []
                all_paths: list[str] = []
                all_cmds: list[str] = []
                all_batch_objects: list[str] = []
                total_tool_count = 0
                action_types: set[str] = set()

                for gi in interval_groups:
                    tg = tool_groups[gi]
                    all_ev_indices.extend(tg["event_indices"])
                    all_paths.extend(tg.get("target_paths", []))
                    all_cmds.extend(tg.get("commands", []))
                    all_batch_objects.extend(tg.get("batch_objects", []))
                    total_tool_count += len(tg["tool_events"])
                    action_types.add(tg["action_type"])

                # Build aggregate title — v2.6: smarter human-readable titles
                def _cmd_has(needle: str) -> bool:
                    return any(needle in (c or "") for c in all_cmds)

                def _path_has(needle: str) -> bool:
                    return any(needle.lower() in (p or "").lower() for p in all_paths)

                is_plan_update = "plan_update" in action_types or "update_plan" in action_types
                is_apply_patch = "apply_patch" in action_types
                is_diagnostic_python = _cmd_has("python") and (_path_has("rollout") or _path_has("otel") or _path_has("session") or _path_has("json") or _cmd_has("codex_token"))
                is_search = "code_search" in action_types or _cmd_has("rg") or _cmd_has("findstr") or _cmd_has("Select-String")
                is_unittest = _cmd_has("unittest") or _cmd_has("pytest") or _cmd_has("test_")
                is_node_check = _cmd_has("node --check") or _cmd_has("node -c")
                is_git = "git_operation" in action_types or _cmd_has("git")
                is_file_read = "file_read" in action_types or "file_read_batch" in action_types
                is_single_read = is_file_read and total_tool_count <= 2 and not all_batch_objects
                is_multi_read = is_file_read and (total_tool_count > 2 or all_batch_objects)
                is_diagnostic_cmd = bool(all_cmds) and not (is_file_read or is_search or is_unittest or is_node_check or is_git or is_apply_patch)

                # v2.9: check success for apply_patch
                if is_plan_update:
                    title = "Обновил план работы"
                elif is_apply_patch:
                    # Check if output has success flag
                    all_success = True
                    for gi in interval_groups:
                        for te in tool_groups[gi].get("tool_events", []):
                            if te.get("success") is False:
                                all_success = False
                                break
                    if all_paths:
                        if len(all_paths) == 1:
                            fname = all_paths[0].split("\\")[-1].split("/")[-1]
                            title = ("Изменил " + fname) if all_success else ("Пытался изменить " + fname)
                        else:
                            title = (f"Изменил {len(all_paths)} файлов") if all_success else (f"Пытался изменить {len(all_paths)} файлов")
                    else:
                        title = "Изменил файлы" if all_success else "Пытался изменить файлы"
                elif is_diagnostic_python:
                    title = "Проверил live telemetry диагностическим Python-скриптом"
                elif is_unittest:
                    title = "Запустил тесты"
                elif is_node_check:
                    title = "Проверил JavaScript синтаксис"
                elif is_search:
                    title = "Искал по коду"
                elif is_git:
                    title = "Проверил изменения в Git"
                elif is_multi_read:
                    title = "Прочитал первичный контекст проекта"
                elif is_single_read:
                    title = "Прочитал файл"
                elif is_diagnostic_cmd:
                    title = "Выполнил диагностические команды"
                else:
                    # v2.9: unknown/service tool — show as service action, not diagnostic
                    title = "Выполнил служебное действие"

                # Build objects label
                objects_label = ""
                unique_paths = list(dict.fromkeys(all_paths))[:5]  # dedup, limit
                if is_plan_update:
                    objects_label = "план работы"
                elif all_batch_objects:
                    objects_label = "Файлы: " + ", ".join(all_batch_objects[:5])
                elif unique_paths:
                    objects_label = unique_paths[0].split("\\")[-1].split("/")[-1][:80]
                    if len(unique_paths) > 1:
                        objects_label += f" + ещё {len(unique_paths) - 1}"
                elif all_cmds:
                    objects_label = all_cmds[0][:120]

                # Determine confidence
                confidence = "high" if any(
                    tg.get("is_batch") or tg.get("action_type") != "shell_command"
                    for gi in interval_groups for tg in [tool_groups[gi]]
                ) else "medium"

                is_batch_aggregate = any(tool_groups[gi].get("is_batch") for gi in interval_groups)

                timeline_item = {
                    "row_type": "tool_with_cost",
                    "event_index": first_tg["first_event_index"],
                    "timestamp": first_tg["timestamp"],
                    "action_type": "aggregate_tool_group",
                    "display_title_ru": title,
                    "recognized_action_ru": title,
                    "recognition_confidence": "high",
                    "recognition_source": "live_tool_events_interval",
                    "object_label": objects_label,
                    "linked_model_request_index": rui_idx + 1,
                    "cost_available": True,
                    "linked_request_usage": {
                        "available": True,
                        "input_tokens": rui.get("input_tokens", 0),
                        "cached_tokens": rui.get("cached_tokens", 0),
                        "non_cached_input_tokens": max(0, rui.get("input_tokens", 0) - rui.get("cached_tokens", 0)),
                        "output_tokens": rui.get("output_tokens", 0),
                        "reasoning_tokens": rui.get("reasoning_tokens", 0),
                    },
                    "linked_cost": {
                        "available": rui_cost.get("total_usd") is not None,
                        "total_usd": rui_cost.get("total_usd"),
                    },
                    "tool_evidence": {
                        "available": True,
                        "event_indices": all_ev_indices,
                        "tool_count": total_tool_count,
                        "is_batch": is_batch_aggregate,
                        "batch_objects": all_batch_objects[:10],
                    },
                    "path": all_paths[0] if all_paths else "",
                    "command": all_cmds[0] if all_cmds else "",
                    "confidence": confidence,
                    "notes_ru": [
                        f"Агрегировано {total_tool_count} tool-событий между AI #{rui_idx} и предыдущим.",
                        "Стоимость относится к AI-осмыслению результатов, не дублируется.",
                    ] if total_tool_count > 1 else [
                        "Стоимость относится к AI-осмыслению результатов, а не к самому выполнению команды.",
                    ],
                }
                human_timeline_items.append(timeline_item)
            else:
                # AI call without tool evidence — v2.6: smarter fallback from neighbor context
                title, recog_conf, recog_src = _build_smart_fallback_title(
                    human_timeline_items, rui_idx, rui, sia_stages=stages,
                    total_ai_calls=len(request_usage_items)
                )
                human_timeline_items.append({
                    "row_type": "ai_call_only",
                    "event_index": rui_ev,
                    "timestamp": rui.get("timestamp", ""),
                    "action_type": "model_request",
                    "display_title_ru": title,
                    "recognized_action_ru": title if recog_conf in ("low",) else "",
                    "recognition_confidence": recog_conf,
                    "recognition_source": recog_src,
                    "object_label": f"AI #{rui_idx + 1}",
                    "linked_model_request_index": rui_idx + 1,
                    "cost_available": True,
                    "linked_request_usage": {
                        "available": True,
                        "input_tokens": rui.get("input_tokens", 0),
                        "cached_tokens": rui.get("cached_tokens", 0),
                        "non_cached_input_tokens": max(0, rui.get("input_tokens", 0) - rui.get("cached_tokens", 0)),
                        "output_tokens": rui.get("output_tokens", 0),
                        "reasoning_tokens": rui.get("reasoning_tokens", 0),
                    },
                    "linked_cost": {
                        "available": rui_cost.get("total_usd") is not None,
                        "total_usd": rui_cost.get("total_usd"),
                    },
                    "tool_evidence": {"available": False},
                    "path": "",
                    "command": "",
                    "confidence": "low",
                    "notes_ru": [
                        f"Нет подтверждённых tool-событий перед AI-обращением #{rui_idx + 1}.",
                        "Действие реконструировано по соседним событиям и сигналам запроса.",
                    ],
                })

            prev_ai_ev = rui_ev  # v2.5-fix: update interval boundary

        # 3. Add unassigned tool groups as action-only rows (no cost)
        for gi, tg in enumerate(tool_groups):
            if gi in assigned_group_indices:
                continue
            human_timeline_items.append({
                "row_type": "action_only",
                "event_index": tg["first_event_index"],
                "timestamp": tg["timestamp"],
                "action_type": tg["action_type"],
                "display_title_ru": tg["title_ru"] if tg["title_ru"] else "Работал с инструментами",
                "recognized_action_ru": tg["title_ru"],
                "recognition_confidence": "high",
                "recognition_source": "live_tool_events",
                "object_label": tg["commands"][0][:120] if tg["commands"] else (tg["target_paths"][0][:120] if tg["target_paths"] else ""),
                "linked_model_request_index": None,
                "cost_available": False,
                "linked_request_usage": None,
                "linked_cost": None,
                "tool_evidence": {
                    "available": True,
                    "event_indices": tg["event_indices"],
                    "tool_count": len(tg["tool_events"]),
                    "is_batch": tg["is_batch"],
                },
                "path": tg["target_paths"][0] if tg["target_paths"] else "",
                "command": tg["commands"][0] if tg["commands"] else "",
                "confidence": "high",
                "notes_ru": [
                    "Tool-событие без связанного AI-обращения.",
                    "Возможно, следующее AI-обращение не зафиксировано в rollout, или это orphan tool event.",
                ],
            })

        # Sort by event_index
        human_timeline_items.sort(key=lambda x: x.get("event_index", 0))

        # Compute duration for items with timestamps
        prev_ts: float | None = None
        for item in human_timeline_items:
            ts_str = item.get("timestamp", "")
            cur_ts = None
            if ts_str:
                try:
                    from datetime import datetime as _dt2
                    cur_ts = _dt2.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    pass
            if prev_ts is not None and cur_ts is not None:
                item["duration"] = {
                    "available": True,
                    "seconds_since_previous_item": round(cur_ts - prev_ts, 3),
                }
            else:
                item["duration"] = {"available": False}
            if cur_ts is not None:
                prev_ts = cur_ts

        # Re-index
        for i, item in enumerate(human_timeline_items):
            item["index"] = i + 1

        human_timeline_summary = {
            "items_count": len(human_timeline_items),
            "tool_with_cost_count": sum(1 for it in human_timeline_items if it["row_type"] == "tool_with_cost"),
            "ai_call_only_count": sum(1 for it in human_timeline_items if it["row_type"] == "ai_call_only"),
            "action_only_count": sum(1 for it in human_timeline_items if it["row_type"] == "action_only"),
            "total_linked_cost_usd": sum(
                (it.get("linked_cost") or {}).get("total_usd") or 0
                for it in human_timeline_items if it.get("cost_available")
            ),
            "tool_events_total": len(lte),
            "tool_events_with_cost": sum(
                1 for it in human_timeline_items if it.get("tool_evidence", {}).get("available")
                and it.get("cost_available")
            ),
        }

        # ── v2.7: enrich timeline items with details, files, commands, raw_evidence ──
        _enrich_timeline_items(
            human_timeline_items, lte, tool_groups, request_usage_items,
            assigned_group_indices, step.get("model", "unknown"),
        )

        # ── v2.11: add assistant_message_data for final_report items ──
        assistant_text = step.get("assistant_answer", {}).get("text", "")
        for item in human_timeline_items:
            title = item.get("display_title_ru", "")
            if "Сформулировал" in title and item.get("row_type") == "ai_call_only":
                msg_len = len(assistant_text) if assistant_text else None
                preview = assistant_text[:300] if assistant_text else ""
                source = "step_assistant_answer" if assistant_text else "none"
                source_conf = "medium_inferred" if assistant_text else "none"
                cost_note = (
                    "Стоимость этого этапа — стоимость генерации видимого ответа. "
                    "В этом AI-call не было новых tool events: модель не читала файлы и не запускала команды. "
                    "Output tokens показывают объём написанного ответа. "
                    "Cached input показывает объём переиспользованного контекста. "
                    "New input показывает новый незакэшированный вход."
                )
                item["assistant_message_data"] = {
                    "available": bool(assistant_text),
                    "is_final_report": True,
                    "message_length_chars": msg_len,
                    "message_preview": preview,
                    "message_text_location_ru": "Полный текст находится в секции Answer",
                    "source": source,
                    "source_confidence": source_conf,
                    "has_new_tool_events": False,
                    "cost_explanation_ru": cost_note,
                }

        # ── Technical AI calls table (separate from human timeline) ──
        technical_ai_calls: list[dict[str, Any]] = []
        for idx, rui in enumerate(request_usage_items):
            rui_cost = rui.get("estimated_cost", {})
            if not isinstance(rui_cost, dict):
                rui_cost = {}
            technical_ai_calls.append({
                "ai_index": idx + 1,
                "event_index": rui.get("event_index", 0),
                "timestamp": rui.get("timestamp", ""),
                "display_title_ru": f"AI #{idx + 1}",
                "input_tokens": rui.get("input_tokens", 0),
                "cached_tokens": rui.get("cached_tokens", 0),
                "non_cached_input_tokens": max(0, rui.get("input_tokens", 0) - rui.get("cached_tokens", 0)),
                "output_tokens": rui.get("output_tokens", 0),
                "reasoning_tokens": rui.get("reasoning_tokens", 0),
                "cost_total_usd": rui_cost.get("total_usd"),
                "linked_to_human_item": any(
                    it.get("linked_model_request_index") == idx + 1 and it["row_type"] == "tool_with_cost"
                    for it in human_timeline_items
                ),
            })

        # ── v2.6: human_summary_ru — 1-3 sentence summary from timeline actions ──
        all_timeline_titles = [it.get("display_title_ru", "") for it in human_timeline_items if it.get("display_title_ru")]
        all_timeline_titles_dedup = list(dict.fromkeys(all_timeline_titles))

        summary_parts: list[str] = []
        has_read = any("Прочитал" in t for t in all_timeline_titles_dedup)
        has_search = any("Искал" in t for t in all_timeline_titles_dedup)
        has_diag = any("Проверил" in t or "Запустил тесты" in t or "Запустил диагностический" in t for t in all_timeline_titles_dedup)
        has_write = any("внёс правки" in t or "Исправил" in t for t in all_timeline_titles_dedup)
        has_test = any("Запустил тесты" in t for t in all_timeline_titles_dedup)
        has_git = any("изменения в Git" in t for t in all_timeline_titles_dedup)
        has_detail = any("подробный вывод" in t for t in all_timeline_titles_dedup)
        has_analyze = any("Анализировал" in t or "Осмыслил" in t for t in all_timeline_titles_dedup)

        if has_read:
            summary_parts.append("прочитал handoff и проектный контекст")
        if has_search:
            summary_parts.append("искал по коду")
        if has_diag and not (has_read or has_write):
            summary_parts.append("проверил live telemetry / raw rollout")
        if has_write:
            summary_parts.append("внёс правки в backend/frontend")
        if has_test:
            summary_parts.append("прогнал тесты")
        if has_git:
            summary_parts.append("проверил изменения в Git")
        if has_detail:
            summary_parts.append("сформулировал подробный вывод")
        if has_analyze and not has_write:
            summary_parts.append("проанализировал результаты")

        human_summary_text = ""
        if summary_parts:
            human_summary_text = "Агент " + ", ".join(summary_parts) + "."
        elif all_timeline_titles_dedup:
            human_summary_text = "Агент выполнил следующие действия: " + "; ".join(all_timeline_titles_dedup[:3]) + "."
        else:
            human_summary_text = "Агент выполнил работу по задаче."

        human_summary_ru = {
            "available": True,
            "text": human_summary_text,
            "source": "agent_activity_human_timeline",
            "confidence": "medium",
        }

        # ── v2.6: expensive_human_actions — top 5 by linked_cost from timeline ──
        costly_items = sorted(
            [it for it in human_timeline_items if it.get("cost_available") and (it.get("linked_cost") or {}).get("total_usd") is not None],
            key=lambda it: (it.get("linked_cost") or {}).get("total_usd") or 0,
            reverse=True,
        )[:5]
        expensive_human_actions: list[dict[str, Any]] = []
        for ci in costly_items:
            lc = ci.get("linked_cost") or {}
            lu = ci.get("linked_request_usage") or {}
            nc = lu.get("non_cached_input_tokens", 0) if lu.get("available") else 0
            out = lu.get("output_tokens", 0) if lu.get("available") else 0
            reason = ""
            if nc > 50000:
                reason = f"высокий новый input: {nc:,}"
            elif out > 1500:
                reason = f"высокий output: {out:,}"
            elif nc > 10000:
                reason = f"заметный новый input: {nc:,}"
            expensive_human_actions.append({
                "index": ci.get("index", 0),
                "display_title_ru": ci.get("display_title_ru", ""),
                "linked_model_request_index": ci.get("linked_model_request_index"),
                "total_usd": lc.get("total_usd"),
                "non_cached_input_tokens": nc,
                "cached_tokens": lu.get("cached_tokens", 0) if lu.get("available") else 0,
                "output_tokens": out,
                "reasoning_tokens": lu.get("reasoning_tokens", 0) if lu.get("available") else 0,
                "expensive_reason": reason,
                "confidence": ci.get("recognition_confidence") or ci.get("confidence", "medium"),
            })

        step["agent_activity"] = {
            "available": True,
            "activity_sources": {
                "raw_events_used": bool(raw_items),
                "answer_text_used": bool(answer_items),
                "prompt_text_used": bool(prompt_items),
                "live_tool_events_used": bool(lte),
            },
            "event_range": {
                "start_event_index": event_range.get("start_event_index", 0),
                "end_event_index": event_range.get("end_event_index", 0),
                "raw_events_count": raw_count,
            },
            "activity_counts": counts,
            "activity_items": all_items,
            "unclassified_raw_events": unclassified_raw,
            "activity_summary_ru": summary_lines,
            "human_summary_ru": human_summary_ru,
            "important_paths": paths[:20],
            "important_commands": cmds[:20],
            "confidence": confidence,
            "agent_timeline": {
                "available": True,
                "source": "live_tool_events" if lte else "raw_events_and_text",
                "confidence": "high" if lte else "medium",
                "items": human_timeline_items,
                "summary": human_timeline_summary,
            },
            "expensive_human_actions": expensive_human_actions,
            "technical_ai_calls": {
                "available": True,
                "items": technical_ai_calls,
                "note_ru": "Техническая таблица всех AI-обращений Codex. В хронологии работы используется как источник cost/usage для человеческих действий.",
            },
            "step_internal_actions": step_internal_actions,
            "agent_activity_stages": stages,
            "top_expensive_internal_actions": top_expensive,
            "is_technical": {
                "step_internal_actions": True,
                "agent_activity_stages": True,
                "top_expensive_internal_actions": True,
                "note_ru": "Эти блоки содержат технические данные для аудита. Основной человеческий отчёт — human_summary_ru, agent_timeline и expensive_human_actions.",
            },
            "requests_with_usage": requests_with_usage,
            "model_related_events": model_events_count,
            "notes_ru": [
                "Резюме действий построено по live_tool_events (function_call/function_call_output из rollout) и тексту ответа агента; оно объясняет работу шага, но не используется для расчёта стоимости.",
                "Хронология работы использует реальные tool-события, где они доступны.",
                "AI # — техническое обращение Codex к модели; в хронологии оно источник cost/usage для человеческого действия.",
                "Файлы из prompt/answer — упомянутые, не обязательно все были прочитаны.",
                "Команды из текста — reported_by_agent, не обязательно все были выполнены.",
            ],
        }

    def finalize_current_step(reason: str = "next_user") -> None:
        nonlocal current_step, pending_text, last_visible_step_index, prev_step_cumulative_after
        if not current_step:
            pending_text = []
            return
        current_step["assistant_answer"]["text"] = "\n".join(pending_text)
        current_step["assistant_answer"]["available"] = bool(pending_text)
        pending_text = []

        usage = current_step.get("usage", {})
        step_model = str(current_step.get("model") or "unknown")

        # ── v2.1: collect ALL request usages and total snapshots from this step ──
        all_request_usages: list[dict[str, Any]] = current_step.pop("_all_request_usages", [])
        all_total_snapshots: list[dict[str, Any]] = current_step.pop("_all_total_snapshots", [])
        start_event_index = current_step.pop("_start_event_index", None)
        end_event_index = current_step.pop("_end_event_index", None)

        # Build request_usage_items array
        request_usage_items = [_make_request_usage_item(r, step_model) for r in all_request_usages]

        # full_step_usage = sum of all request_usage_items
        full_step_usage = _sum_usage_items(request_usage_items)

        # full_step_cost from full_step_usage
        fsu = full_step_usage
        fsc_est = _estimate_usage_costs(step_model, fsu["input_tokens"], fsu["cached_tokens"], fsu["output_tokens"])
        full_step_cost = {
            "source": "estimated_from_full_step_usage",
            "total_usd": fsc_est.get("estimated_total_cost_usd"),
            "input_usd": fsc_est.get("estimated_input_cost_usd"),
            "cached_input_usd": fsc_est.get("estimated_cached_input_cost_usd"),
            "output_usd": fsc_est.get("estimated_output_cost_usd"),
            "confidence": "estimated_from_local_pricing_config",
        }

        # primary_request_usage = last request in the step (for backwards comparison)
        primary_request_usage = None
        last_req = request_usage_items[-1] if request_usage_items else None
        if last_req:
            primary_request_usage = {
                "source": "live_last_token_usage",
                "input_tokens": last_req["input_tokens"],
                "cached_tokens": last_req["cached_tokens"],
                "output_tokens": last_req["output_tokens"],
                "reasoning_tokens": last_req["reasoning_tokens"],
                "tool_tokens": last_req["tool_tokens"],
            }

        # Populate legacy usage block from primary_request_usage (backwards compat)
        if isinstance(usage, dict) and primary_request_usage:
            inp = primary_request_usage["input_tokens"]
            cached = primary_request_usage["cached_tokens"]
            out = primary_request_usage["output_tokens"]
            reas = primary_request_usage["reasoning_tokens"]
            tool = primary_request_usage["tool_tokens"]
            nc = max(inp - cached, 0)
            has_nz = any(v > 0 for v in (inp, cached, out, reas, tool))
            usage.update({
                "input_tokens": inp if has_nz else 0,
                "cached_tokens": cached if has_nz else 0,
                "non_cached_input_tokens": nc if has_nz else 0,
                "cached_ratio": (cached / inp) if has_nz and inp > 0 else 0,
                "output_tokens": out if has_nz else 0,
                "reasoning_tokens": reas if has_nz else 0,
                "tool_tokens": tool if has_nz else 0,
                "available": has_nz,
                "confirmation_status": "confirmed_request_usage" if has_nz else "missing_request_usage",
                "source": "live_last_token_usage" if has_nz else "missing",
                "note": "" if has_nz else "no confirmed last_token_usage for this step",
                **(
                    _estimate_usage_costs(step_model, inp, cached, out)
                    if has_nz
                    else {"estimated_total_cost_usd": None, "estimated_input_cost_usd": None,
                          "estimated_cached_input_cost_usd": None, "estimated_output_cost_usd": None}
                ),
            })

        # cumulative_after_step from last total_token_usage snapshot
        last_total = all_total_snapshots[-1] if all_total_snapshots else None
        cumulative_after_step = _make_cumulative_dict(last_total)
        usage["cumulative_usage_after_step"] = cumulative_after_step

        # cumulative cost
        if isinstance(last_total, dict) and cumulative_after_step.get("available"):
            cum_costs = _estimate_usage_costs(step_model,
                to_int(last_total.get("input_tokens"), 0),
                to_int(last_total.get("cached_tokens"), 0),
                to_int(last_total.get("output_tokens"), 0))
            usage["estimated_cumulative_cost_usd"] = cum_costs.get("estimated_total_cost_usd")
        else:
            usage["estimated_cumulative_cost_usd"] = None

        # cumulative_before_step from previous visible step
        cumulative_before_step = ({"available": True, **{k: v for k, v in prev_step_cumulative_after.items() if k != "available"}}
                                 if prev_step_cumulative_after and prev_step_cumulative_after.get("available")
                                 else {"available": False})

        # cumulative_delta = after - before
        cumulative_delta = _delta_cumulative(cumulative_after_step, cumulative_before_step)

        # unattributed_delta = cumulative_delta - full_step_usage
        unattributed_delta = _delta_unattributed(cumulative_delta, full_step_usage)

        # cost_scope
        cost_scope = _build_cost_scope(len(request_usage_items))

        # event_range
        si = start_event_index if start_event_index is not None else 0
        ei = end_event_index if end_event_index is not None else 0
        event_range = {
            "start_event_index": si,
            "end_event_index": ei,
            "raw_events_count": (ei - si + 1) if (si is not None and ei is not None) else 0,
        }

        # ── write v2.1 fields into step ──
        current_step["request_usage_items"] = request_usage_items
        current_step["full_step_usage"] = full_step_usage
        current_step["full_step_cost"] = full_step_cost
        if primary_request_usage:
            current_step["primary_request_usage"] = primary_request_usage
        current_step["cumulative_before_step"] = cumulative_before_step
        current_step["cumulative_after_step"] = cumulative_after_step
        current_step["cumulative_delta"] = cumulative_delta
        current_step["unattributed_delta"] = unattributed_delta
        current_step["cost_scope"] = cost_scope
        current_step["event_range"] = event_range

        # ── v2.2: build agent_activity from classified events ──
        raw_activity_items: list[dict[str, Any]] = current_step.pop("_activity_items", [])
        live_tool_events_raw: list[dict[str, Any]] = current_step.pop("_live_tool_events", [])

        # ── v2.5: process live_tool_events — link tool_call ↔ tool_output by call_id ──
        processed_tool_events: list[dict[str, Any]] = []
        # Index tool_outputs by call_id (function_call_output, custom_tool_call_output, patch_apply_end)
        outputs_by_call_id: dict[str, dict[str, Any]] = {}
        for te in live_tool_events_raw:
            if te.get("kind") == "tool_output":
                cid = te.get("call_id", "")
                if cid:
                    # Prefer patch_apply_end over custom_tool_call_output over function_call_output
                    existing = outputs_by_call_id.get(cid)
                    if not existing or te.get("payload_type") == "patch_apply_end":
                        outputs_by_call_id[cid] = te

        for te in live_tool_events_raw:
            kind = te.get("kind", "")
            if kind in ("tool_call",):  # includes function_call and custom_tool_call
                cid = te.get("call_id", "")
                linked_output = outputs_by_call_id.get(cid)
                te_copy = dict(te)
                if linked_output:
                    te_copy["output_found"] = True
                    te_copy["output_event_index"] = linked_output.get("event_index", 0)
                    te_copy["output_exit_code"] = linked_output.get("exit_code", 0)
                    te_copy["output_preview"] = linked_output.get("output_preview", "")
                    te_copy["output_length"] = linked_output.get("output_length", 0)
                    te_copy["success"] = linked_output.get("success", te.get("success"))
                    # v2.10: detect apply_patch status and update title
                    if te.get("classified_action") == "apply_patch":
                        out_text = linked_output.get("output_preview", "")
                        succ_flag = linked_output.get("success")
                        # Use patch_status from output if available, else compute from text
                        patch_status = linked_output.get("patch_status") or _detect_patch_status(out_text, succ_flag)
                        te_copy["patch_status"] = patch_status
                        file_infos = te.get("patch_file_infos", [])
                        new_title = _build_apply_patch_title(file_infos, patch_status)
                        te_copy["title_ru"] = new_title
                else:
                    te_copy["output_found"] = False
                    te_copy["output_event_index"] = None
                    te_copy["output_exit_code"] = None
                    te_copy["output_preview"] = ""
                    te_copy["output_length"] = 0
                processed_tool_events.append(te_copy)
            elif te.get("kind") == "tool_output":
                # Only include outputs that don't have matching calls (orphans)
                cid = te.get("call_id", "")
                if cid not in {t.get("call_id", "") for t in live_tool_events_raw if t.get("kind") == "tool_call"}:
                    processed_tool_events.append(dict(te))

        # Sort by event_index
        processed_tool_events.sort(key=lambda x: x.get("event_index", 0))

        current_step["live_tool_events"] = processed_tool_events

        # Build human_timeline from live_tool_events + request_usage_items
        _build_agent_activity(current_step, raw_activity_items, full_step_usage, event_range, request_usage_items, processed_tool_events)

        # Fallback: no request usage at all
        if not primary_request_usage and isinstance(usage, dict):
            usage["available"] = False
            usage["confirmation_status"] = "missing_request_usage"
            usage["source"] = "missing"
            notes = {"next_user": "next turn started before token checkpoint for this step",
                     "task_complete": "task completed without last_token_usage checkpoint",
                     "session_end": "session ended without last_token_usage checkpoint"}
            usage["note"] = notes.get(reason, "no confirmed last_token_usage for this step")

        # Update prev_step_cumulative_after for next step
        if cumulative_after_step.get("available"):
            prev_step_cumulative_after = cumulative_after_step

        steps.append(current_step)
        last_visible_step_index = to_int(current_step.get("step_index"), last_visible_step_index)
        current_step = None

    for ev in events:
        global_event_index += 1
        outer_type = ev.get("type", "")
        pl = ev.get("payload", {})
        if not isinstance(pl, dict):
            continue

        # turn_context carries model/effort for subsequent steps
        if outer_type == "turn_context":
            current_turn_context = pl
            current_model = str(pl.get("model", current_model))
            current_reasoning = str(pl.get("effort", pl.get("reasoning_effort", current_reasoning)))
            continue

        if outer_type == "event_msg":
            event_type = str(pl.get("type", ""))
            if event_type == "task_started":
                active_task_turn_id = str(pl.get("turn_id", "") or "")
            elif event_type == "task_complete":
                if current_step:
                    current_step.setdefault("environment", {})["task_turn_id"] = str(pl.get("turn_id", "") or active_task_turn_id)
                    finalize_current_step("task_complete")
                active_task_turn_id = ""
            elif event_type == "context_compacted":
                if steps:
                    last_step = steps[-1]
                    badges = last_step.setdefault("post_step_badges", [])
                    if "контекст сжат после этого хода" not in badges:
                        badges.append("контекст сжат после этого хода")
                timeline_events.append(
                    {
                        "event_type": "context_compacted",
                        "label": "Сжатие контекста",
                        "timestamp": str(ev.get("timestamp", "")),
                        "after_step_index": last_visible_step_index,
                        "compaction_task_id": active_task_turn_id or None,
                        "after_step_turn_id": (steps[-1].get("turn_id") if steps else None),
                    }
                )

        # response_item routing by outer type, role from payload
        is_user = (outer_type == "response_item" and pl.get("role") == "user")
        is_assistant = (outer_type == "response_item" and pl.get("role") == "assistant")

        # token_count in event_msg: prefer payload.info.last_token_usage for per-step live usage
        token_count = None
        total_token_snapshot = None
        model_context_window = 0
        if outer_type == "event_msg":
            info = pl.get("info", {})
            if isinstance(info, dict):
                token_count = info.get("last_token_usage") or info.get("total_token_usage")
                total_token_snapshot = info.get("total_token_usage")
                model_context_window = to_int(info.get("model_context_window"), 0)

        if is_user:
            user_text = ""
            # response_item payload: {type, role, content: [{text: ...}]}
            content_parts = pl.get("content", [])
            user_text = _extract_content_text(content_parts)

            # turn_id from turn_context event or fallback
            turn_id = pl.get("turn_id", f"turn-{step_index + 1}")
            finalize_current_step("next_user")
            if _is_internal_live_user_prompt(user_text):
                continue

            step_index += 1

            current_step = {
                "step_index": step_index,
                "turn_id": str(turn_id),
                "timestamp": str(pl.get("timestamp", ev.get("timestamp", ""))),
                "model": current_model,
                "reasoning_effort": current_reasoning,
                "user_prompt": {
                    "available": bool(user_text.strip()),
                    "text": user_text.strip(),
                    "hidden_by_default": True,
                    "kind": "user_message",
                },
                "assistant_answer": {
                    "available": False,
                    "text": "",
                    "hidden_by_default": True,
                },
                "usage": {
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "non_cached_input_tokens": 0,
                    "cached_ratio": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "tool_tokens": 0,
                    "available": False,
                    "note": "per-step token mapping may be cumulative; use session totals",
                    "estimated_total_cost_usd": None,
                    "estimated_input_cost_usd": None,
                    "estimated_cached_input_cost_usd": None,
                    "estimated_output_cost_usd": None,
                },
                "environment": {
                    "thread_id": thread_id,
                    "cwd": str(current_turn_context.get("cwd", "")),
                    "workspace_roots": current_turn_context.get("workspace_roots")
                    if isinstance(current_turn_context.get("workspace_roots"), list)
                    else [],
                    "current_date": str(current_turn_context.get("current_date", "")),
                    "timezone": str(current_turn_context.get("timezone", "")),
                    "approval_policy": str(current_turn_context.get("approval_policy", "")),
                    "sandbox_policy": (
                        current_turn_context.get("sandbox_policy", {}).get("type", "")
                        if isinstance(current_turn_context.get("sandbox_policy"), dict)
                        else ""
                    ),
                    "permission_profile": (
                        current_turn_context.get("permission_profile", {}).get("type", "")
                        if isinstance(current_turn_context.get("permission_profile"), dict)
                        else ""
                    ),
                    "observed_mcp_server_count": 0,
                    "observed_mcp_servers": [],
                    "enabled_plugins_count": 0,
                    "enabled_skills_count": 0,
                    "global_user_instructions_status": "unknown",
                    "repo_context_status": "unknown",
                },
                "warnings": [],
                "post_step_badges": [],
                # v2.1: track all usages and event range
                "_all_request_usages": [],
                "_all_total_snapshots": [],
                "_start_event_index": global_event_index,
                "_end_event_index": global_event_index,
                # v2.2: agent activity items
                "_activity_items": [],
                # v2.5: live_tool_events from raw function_call/function_call_output
                "_live_tool_events": [],
            }

        # ── v2.5: capture function_call / function_call_output ──
        is_function_call = (outer_type == "response_item" and pl.get("type") == "function_call")
        is_function_output = (outer_type == "response_item" and pl.get("type") == "function_call_output")

        if current_step and (is_function_call or is_function_output):
            tool_event: dict[str, Any] = {
                "event_index": global_event_index,
                "timestamp": str(ev.get("timestamp", "")),
            }
            if is_function_call:
                tool_name = str(pl.get("name", ""))
                call_id = str(pl.get("call_id", ""))
                # Parse arguments — may be dict or JSON string
                raw_args = pl.get("arguments", {})
                args: dict[str, Any] = {}
                if isinstance(raw_args, dict):
                    args = raw_args
                elif isinstance(raw_args, str) and raw_args.strip():
                    try:
                        args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                command = str(args.get("command", ""))
                workdir = str(args.get("workdir", ""))
                timeout_ms = args.get("timeout_ms", 0)
                classification = _classify_shell_command(command) if command else _classify_service_call(tool_name, args)
                # Apply classification fields first, then override with tool_call specifics
                tool_event.update(classification)
                tool_event.update({
                    "kind": "tool_call",
                    "payload_type": "function_call",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "command": command,
                    "workdir": workdir,
                    "timeout_ms": timeout_ms,
                    "raw_arguments_preview": str(raw_args)[:300],
                })
            else:  # function_call_output
                call_id = str(pl.get("call_id", ""))
                output_text = str(pl.get("output", pl.get("text", pl.get("result", ""))))
                exit_code = pl.get("exit_code", pl.get("exitCode", 0))
                if isinstance(exit_code, (int, float)):
                    exit_code = int(exit_code)
                else:
                    exit_code = 0
                # v2.5-fix: parse Exit code from output string if not in payload
                if exit_code == 0 and output_text:
                    import re as _re_ec
                    ec_match = _re_ec.search(r'Exit code:\s*(-?\d+)', output_text)
                    if ec_match:
                        exit_code = int(ec_match.group(1))
                tool_event.update({
                    "kind": "tool_output",
                    "payload_type": "function_call_output",
                    "call_id": call_id,
                    "exit_code": exit_code,
                    "output_preview": output_text[:300] if output_text else "",
                    "output_length": len(output_text) if output_text else 0,
                    "classified_action": "tool_output",
                    "action_type": "tool_output",
                    "title_ru": "",
                    "target_path": "",
                    "is_batch_candidate": False,
                    "batch_group": "",
                    "raw_arguments_preview": "",
                })
            current_step["_live_tool_events"].append(tool_event)

        # ── v2.9: custom_tool_call / custom_tool_call_output / patch_apply_end ──
        is_custom_call = (outer_type == "response_item" and pl.get("type") == "custom_tool_call")
        is_custom_output = (outer_type == "response_item" and pl.get("type") == "custom_tool_call_output")
        is_patch_end = (outer_type == "event_msg" and isinstance(pl.get("info"), dict) and pl["info"].get("type") == "patch_apply_end")

        if current_step and (is_custom_call or is_custom_output or is_patch_end):
            tool_event: dict[str, Any] = {
                "event_index": global_event_index,
                "timestamp": str(ev.get("timestamp", "")),
            }
            if is_custom_call:
                name = str(pl.get("name", ""))
                call_id = str(pl.get("call_id", ""))
                # custom_tool_call uses "input" key in Codex rollout, not "arguments"
                raw_args = pl.get("arguments") or pl.get("input") or {}
                if isinstance(raw_args, dict):
                    args = raw_args
                elif isinstance(raw_args, str) and raw_args.strip():
                    try:
                        args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                else:
                    args = {}
                # Extract file paths with roles from patch input
                file_infos = _extract_patch_target_files(args)
                # v2.10: if args search found nothing, search entire pl payload
                if not file_infos:
                    file_infos = _extract_patch_target_files(dict(pl))
                target_paths = [fi["path"] for fi in file_infos]
                patch_status = "unknown"  # set by linker when output is available
                patch_input_chars = len(json.dumps(raw_args) if isinstance(raw_args, dict) else str(raw_args))
                title = _build_apply_patch_title(file_infos, patch_status)
                tool_event.update({
                    "kind": "tool_call",
                    "payload_type": "custom_tool_call",
                    "tool_name": name,
                    "call_id": call_id,
                    "command": "",
                    "workdir": str(args.get("workdir", args.get("cwd", ""))),
                    "timeout_ms": 0,
                    "classified_action": "apply_patch",
                    "action_type": "apply_patch",
                    "title_ru": title,
                    "target_path": target_paths[0] if target_paths else "",
                    "target_paths": target_paths,
                    "patch_file_infos": file_infos,
                    "patch_status": patch_status,
                    "patch_input_chars": patch_input_chars,
                    "is_batch_candidate": False,
                    "batch_group": "",
                    "raw_arguments_preview": str(args)[:300],
                })
            elif is_custom_output:
                call_id = str(pl.get("call_id", ""))
                output_text = str(pl.get("output", pl.get("text", pl.get("result", ""))))
                explicit_success = pl.get("success", pl.get("patch_applied"))
                success_flag = explicit_success if isinstance(explicit_success, bool) else None
                patch_status = _detect_patch_status(output_text, success_flag)
                tool_event.update({
                    "kind": "tool_output",
                    "payload_type": "custom_tool_call_output",
                    "call_id": call_id,
                    "exit_code": 0 if patch_status == "success" else (1 if patch_status == "failed" else 0),
                    "output_preview": output_text[:300] if output_text else "",
                    "output_length": len(output_text) if output_text else 0,
                    "classified_action": "apply_patch",
                    "action_type": "tool_output",
                    "title_ru": "",
                    "target_path": "",
                    "is_batch_candidate": False,
                    "batch_group": "",
                    "raw_arguments_preview": "",
                    "success": patch_status == "success" if patch_status != "unknown" else None,
                    "patch_status": patch_status,
                })
            elif is_patch_end:
                info = pl.get("info", {})
                call_id = str(info.get("call_id", info.get("patch_call_id", "")))
                success = info.get("success", info.get("patch_applied", True))
                changed = info.get("changed_files", info.get("files_changed", []))
                if isinstance(changed, str):
                    changed = [p.strip() for p in changed.split(",") if p.strip()]
                tool_event.update({
                    "kind": "tool_output",
                    "payload_type": "patch_apply_end",
                    "call_id": call_id,
                    "exit_code": 0 if success else 1,
                    "output_preview": str(info.get("message", info.get("result", "")))[:300],
                    "output_length": len(str(info.get("message", info.get("result", "")))) if info.get("message") or info.get("result") else 0,
                    "classified_action": "apply_patch",
                    "action_type": "tool_output",
                    "title_ru": "",
                    "target_path": changed[0] if changed else "",
                    "target_paths": changed if changed else [],
                    "is_batch_candidate": False,
                    "batch_group": "",
                    "raw_arguments_preview": "",
                    "success": success,
                })
            current_step["_live_tool_events"].append(tool_event)

        elif is_assistant:
            content_parts = pl.get("content", [])
            if isinstance(content_parts, list):
                for c in content_parts:
                    if isinstance(c, dict):
                        txt = c.get("text", "") or c.get("output_text", "")
                        if txt:
                            pending_text.append(str(txt))

        if token_count and isinstance(token_count, dict) and current_step:
            current_step.setdefault("_all_request_usages", []).append({
                "event_index": global_event_index,
                "timestamp": str(ev.get("timestamp", "")),
                "input_tokens": to_int(token_count.get("input_tokens", token_count.get("input_token_count", 0))),
                "cached_tokens": to_int(token_count.get("cached_input_tokens", token_count.get("cached_input_token_count", 0))),
                "output_tokens": to_int(token_count.get("output_tokens", token_count.get("output_token_count", 0))),
                "reasoning_tokens": to_int(token_count.get("reasoning_output_tokens", token_count.get("reasoning_token_count", 0))),
                "tool_tokens": to_int(token_count.get("tool_tokens", token_count.get("tool_token_count", 0))),
            })
            current_step.setdefault("environment", {})["model_context_window"] = model_context_window

        if total_token_snapshot and isinstance(total_token_snapshot, dict) and current_step:
            current_step.setdefault("_all_total_snapshots", []).append({
                "event_index": global_event_index,
                "timestamp": str(ev.get("timestamp", "")),
                "input_tokens": to_int(total_token_snapshot.get("input_tokens", total_token_snapshot.get("input_token_count", 0))),
                "cached_tokens": to_int(total_token_snapshot.get("cached_input_tokens", total_token_snapshot.get("cached_input_token_count", 0))),
                "output_tokens": to_int(total_token_snapshot.get("output_tokens", total_token_snapshot.get("output_token_count", 0))),
                "reasoning_tokens": to_int(total_token_snapshot.get("reasoning_output_tokens", total_token_snapshot.get("reasoning_token_count", 0))),
                "tool_tokens": to_int(total_token_snapshot.get("tool_tokens", total_token_snapshot.get("tool_token_count", 0))),
            })

        # v2.2: classify raw event for agent activity breakdown
        if current_step:
            classified = _classify_event(ev, global_event_index)
            if classified:
                if isinstance(classified, list):
                    current_step["_activity_items"].extend(classified)
                else:
                    current_step["_activity_items"].append(classified)

        # v2.1: update _end_event_index for current step
        if current_step:
            current_step["_end_event_index"] = global_event_index

    finalize_current_step("session_end")

    return steps, timeline_events
# ── HTTP Handler ──


def _estimate_usage_costs(
    model: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
) -> dict[str, float | None]:
    pricing = _load_pricing()
    prices = pricing.get(model)
    if not prices:
        return {
            "estimated_total_cost_usd": None,
            "estimated_input_cost_usd": None,
            "estimated_cached_input_cost_usd": None,
            "estimated_output_cost_usd": None,
        }
    non_cached_tokens = max(input_tokens - cached_tokens, 0)
    input_cost = (non_cached_tokens / 1_000_000) * prices.get("input", 0)
    cached_cost = (cached_tokens / 1_000_000) * prices.get("cached_input", 0)
    output_cost = (output_tokens / 1_000_000) * prices.get("output", 0)
    return {
        "estimated_total_cost_usd": input_cost + cached_cost + output_cost,
        "estimated_input_cost_usd": input_cost,
        "estimated_cached_input_cost_usd": cached_cost,
        "estimated_output_cost_usd": output_cost,
    }

class MonitorHandler(SimpleHTTPRequestHandler):
    """Simple HTTP handler with JSON API endpoints + static file serving."""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Suppress default logs for cleaner output
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _parse_query(self) -> dict[str, list[str]]:
        parsed = urlparse(self.path)
        return parse_qs(parsed.query)

    def _load_own_config(self) -> dict[str, Any]:
        config_path = CONFIG_DIR / "codex_token_monitor_projects.json"
        return load_config(config_path)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/sources":
            config = self._load_own_config()
            self._send_json({
                "default_source_id": config.get("default_source_id", ""),
                "sources": config.get("sources", []),
            })

        elif path == "/api/sessions":
            qs = self._parse_query()
            source_id = qs.get("source_id", [""])[0]
            show_archived = qs.get("show_archived", ["0"])[0] == "1"
            config = self._load_own_config()
            source = find_source(config, source_id)
            if not source:
                self._send_error_json(f"Source '{source_id}' not found")
                return

            if source.get("kind") == "live":
                sessions = discover_live_sessions(source)
            else:
                sessions = discover_archive_sessions(source)

            if not show_archived:
                sessions = [s for s in sessions if not is_archived(source_id, str(s.get("id", "")))]

            self._send_json({"sessions": sessions})

        elif path == "/api/session":
            qs = self._parse_query()
            source_id = qs.get("source_id", [""])[0]
            session_id = qs.get("session_id", [""])[0]
            config = self._load_own_config()
            source = find_source(config, source_id)
            if not source:
                self._send_error_json(f"Source '{source_id}' not found")
                return

            if source.get("kind") == "live":
                detail = build_live_session_detail(source, session_id)
            else:
                detail = build_archive_session_detail(source, session_id)

            if detail is None:
                self._send_error_json(f"Session '{session_id}' not found", 404)
                return

            detail["archived"] = is_archived(source_id, session_id)
            self._send_json(detail)

        elif path == "/api/status":
            self._send_json({
                "collector": "running",
                "prompt_logging": True,
                "last_update": datetime.now(timezone.utc).isoformat(),
            })

        elif path == "/api/audit":
            qs = self._parse_query()
            source_id = qs.get("source_id", [""])[0]
            session_id = qs.get("session_id", [""])[0]
            config = self._load_own_config()
            source = find_source(config, source_id)
            if not source:
                self._send_error_json(f"Source '{source_id}' not found")
                return

            if source.get("kind") == "live":
                detail = build_live_session_detail(source, session_id)
            else:
                detail = build_archive_session_detail(source, session_id)

            if detail is None:
                self._send_error_json(f"Session '{session_id}' not found", 404)
                return

            try:
                from scripts.codex_token_monitor_audit import run_audit
                result = run_audit(detail, source_kind=source.get("kind", ""))
                self._send_json(result)
            except ImportError:
                self._send_error_json("Audit module not available", 500)

        elif path in ("/", "/index.html"):
            self._serve_static("index.html")

        elif path.startswith("/static/") or path == "/favicon.ico":
            self._serve_static(path.lstrip("/"))

        elif path == "/api/shutdown":
            self._send_json({"status": "shutdown_endpoint_requires_post"})

        else:
            # Try to serve as static
            self._serve_static(path.lstrip("/"))

    def _serve_static(self, rel_path: str) -> None:
        if rel_path == "favicon.ico":
            rel_path = "static/codex-token-monitor/favicon.ico"
        if rel_path.startswith("static/"):
            rel_path = rel_path[len("static/"):]

        full_path = (STATIC_DIR / rel_path).resolve()
        # Security: only serve inside STATIC_DIR
        if not str(full_path).startswith(str(STATIC_DIR.resolve())):
            self.send_error(403)
            return

        if not full_path.exists() or not full_path.is_file():
            self.send_error(404)
            return

        ext = full_path.suffix.lower()
        mime_map = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".svg": "image/svg+xml",
        }
        content_type = mime_map.get(ext, "application/octet-stream")

        try:
            data = full_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(404)
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/refresh":
            self._send_json({"status": "refreshed"})

        elif path == "/api/archive":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length)) if content_length else {}
                source_id = body.get("source_id", "")
                session_id = body.get("session_id", "")
                set_archived(source_id, session_id, True)
                self._send_json({"status": "archived"})
            except Exception as e:
                self._send_error_json(str(e))

        elif path == "/api/unarchive":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length)) if content_length else {}
                source_id = body.get("source_id", "")
                session_id = body.get("session_id", "")
                set_archived(source_id, session_id, False)
                self._send_json({"status": "unarchived"})
            except Exception as e:
                self._send_error_json(str(e))

        elif path == "/api/shutdown":
            self._send_json({"status": "shutting_down"})
            # Schedule server shutdown in a separate thread
            threading.Thread(target=lambda: self.server.shutdown(), daemon=True).start()

        else:
            self._send_error_json("Not found", 404)


# ── Server ──


def _rebind_server(
    port: int = 8765,
    host: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MonitorHandler)
    server.timeout = 0.5
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex Token Monitor v2")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--open-browser", action="store_true", help="Open browser on start")
    return parser.parse_args(argv or sys.argv[1:])


def main() -> None:
    args = parse_args()
    server = _rebind_server(port=args.port, host=args.host)

    if args.open_browser:
        url = f"http://{args.host}:{args.port}"
        webbrowser.open(url)

    print(f"Serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        server.server_close()


if __name__ == "__main__":
    main()
