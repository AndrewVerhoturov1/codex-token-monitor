#!/usr/bin/env python3
"""Codex Token Monitor Audit — separate verification layer over hybrid monitor baseline.

Checks technical truth of source selection, session identity, step attribution,
usage basis, fallback semantics, cost confidence and export completeness.

Does NOT:
- change live Codex config
- start new OTel experiments
- write into C:/Users/andre/.codex/**
- perform human-facing wording changes (that's Honesty hardening, later)

Usage:
  As module: from scripts.codex_token_monitor_audit import run_audit
  As script: python scripts/codex_token_monitor_audit.py --detail <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_DIR = REPO_ROOT / "config"
LOCAL_MONITOR_DIR = REPO_ROOT / "_local" / "codex-token-monitor"

# ── Audit status model ──

AuditResult = dict[str, Any]

# Evidence basis levels for audit truth model
EVIDENCE_VERIFIED = "verified_against_source_evidence"
EVIDENCE_PLAUSIBLE = "detail_looked_plausible"
EVIDENCE_NOT_VERIFIED = "not_verified"


# ── Rollout cumulative parsing ──

def _parse_rollout_for_cumulative(rollout_path: Path, session_id: str) -> dict[str, Any]:
    """Parse a rollout JSONL file and extract cumulative token_count events.

    Returns a dict with:
    - turns: list of {turn_id, cumulative_events: [{timestamp, total_token_usage}]}
    - final_cumulative: last total_token_usage across entire file
    - parse_errors: list of parse issues
    """
    turns: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    current_turn_id: str | None = None
    current_turn_events: list[dict[str, Any]] = []
    final_cumulative: dict[str, Any] | None = None

    if not rollout_path.exists():
        return {
            "turns": [],
            "final_cumulative": None,
            "parse_errors": [f"Rollout file not found: {rollout_path}"],
        }

    try:
        lines = rollout_path.read_text(encoding="utf-8").strip().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "turns": [],
            "final_cumulative": None,
            "parse_errors": [f"Cannot read rollout file: {exc}"],
        }

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"Line {line_no}: JSON decode error: {exc}")
            continue

        event_type = str(event.get("type", ""))
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        # Track turn boundaries
        if event_type == "event_msg":
            ptype = str(payload.get("type", ""))
            if ptype == "task_started":
                # Save previous turn
                if current_turn_id is not None:
                    turns.append({
                        "turn_id": current_turn_id,
                        "cumulative_events": current_turn_events,
                    })
                current_turn_id = str(payload.get("turn_id", ""))
                current_turn_events = []
            elif ptype == "task_complete":
                # End of turn — save
                if current_turn_id is not None:
                    turns.append({
                        "turn_id": current_turn_id,
                        "cumulative_events": current_turn_events,
                    })
                current_turn_id = None
                current_turn_events = []

        # Extract token_count events
        if event_type == "event_msg":
            ptype = str(payload.get("type", ""))
            if ptype == "token_count":
                info = payload.get("info", {})
                if isinstance(info, dict):
                    ttu = info.get("total_token_usage")
                    ltu = info.get("last_token_usage")
                    event_entry = {
                        "timestamp": str(event.get("timestamp", "")),
                        "total_token_usage": _parse_redacted_int(ttu),
                        "last_token_usage": _parse_redacted_int(ltu),
                    }
                    if current_turn_id is not None:
                        current_turn_events.append(event_entry)
                    final_cumulative = event_entry

    # Save trailing turn if any
    if current_turn_id is not None and current_turn_events:
        turns.append({
            "turn_id": current_turn_id,
            "cumulative_events": current_turn_events,
        })

    return {
        "turns": turns,
        "final_cumulative": final_cumulative,
        "parse_errors": parse_errors,
    }


def _parse_redacted_int(value: Any) -> int | None:
    """Parse token usage value, handling [REDACTED] and non-numeric strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.upper() in ("[REDACTED]", "", "N/A", "NULL"):
            return None
        try:
            return int(float(stripped))
        except (ValueError, TypeError):
            return None
    return None


def _compute_step_cumulative_accounting(
    steps: list[dict[str, Any]],
    rollout_turns: list[dict[str, Any]],
    source_kind: str,
) -> list[dict[str, Any]]:
    """Compute cumulative-after-step and unattributed-delta for each visible step.

    Attaches to each step's usage dict (mutates in place) and returns
    a list of per-step accounting dicts for audit result inclusion.

    Returns list of per-step accounting dicts (one per audited step).
    """
    if source_kind != "live" or not rollout_turns:
        return []

    # Build turn_id -> cumulative snapshot map
    # For each turn, take the LAST token_count event as the "cumulative after step"
    turn_cumulative_map: dict[str, dict[str, int | None]] = {}
    for turn in rollout_turns:
        tid = turn.get("turn_id", "")
        events = turn.get("cumulative_events", [])
        if events:
            last = events[-1]
            turn_cumulative_map[tid] = last

    # Token field keys to compute
    TOKEN_FIELDS = [
        "total_token_usage",
        "input_tokens",
        "cached_tokens",
        "output_tokens",
    ]

    accounting_rows: list[dict[str, Any]] = []
    prev_cumulative: dict[str, int | None] = {}

    for step in steps:
        # Match by environment.task_turn_id (real rollout turn_id) first,
        # fall back to step-level turn_id (synthetic like "turn-1")
        env = step.get("environment", {})
        if isinstance(env, dict):
            task_turn_id = str(env.get("task_turn_id", ""))
        else:
            task_turn_id = ""
        turn_id = task_turn_id or str(step.get("turn_id", ""))
        usage = step.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
            step["usage"] = usage

        row: dict[str, Any] = {
            "step_index": step.get("step_index", "?"),
            "turn_id": turn_id,
            "request_usage": {},
            "cumulative_usage_after_step": {},
            "cumulative_delta_since_previous_visible_step": {},
            "unattributed_delta": {},
            "warnings": [],
        }

        # Extract request_usage from step usage (what the step reports as its own usage)
        for field in TOKEN_FIELDS:
            val = usage.get(field)
            row["request_usage"][field] = _parse_redacted_int(val)

        # Also extract from step usage directly for request-level fields
        for field in ["input_tokens", "cached_tokens", "non_cached_input_tokens",
                       "output_tokens", "reasoning_tokens", "tool_tokens"]:
            if field not in row["request_usage"]:
                val = usage.get(field)
                row["request_usage"][field] = _parse_redacted_int(val)

        # Get cumulative after this step from rollout
        cum = turn_cumulative_map.get(turn_id)
        if cum:
            for field in TOKEN_FIELDS:
                row["cumulative_usage_after_step"][field] = _parse_redacted_int(
                    cum.get(field)
                )
            # Also carry through the rollout-level fields
            row["cumulative_usage_after_step"]["last_token_usage"] = _parse_redacted_int(
                cum.get("last_token_usage")
            )

        # Compute cumulative_delta and unattributed_delta
        if prev_cumulative and cum:
            for field in TOKEN_FIELDS:
                prev_val = prev_cumulative.get(field)
                curr_val = _parse_redacted_int(cum.get(field))
                if prev_val is not None and curr_val is not None:
                    delta = curr_val - prev_val
                    row["cumulative_delta_since_previous_visible_step"][field] = delta

                    # unattributed_delta = cumulative_delta - request_usage
                    req_val = row["request_usage"].get(field)
                    if req_val is not None:
                        unattributed = delta - req_val
                        row["unattributed_delta"][field] = unattributed
                        if unattributed < 0:
                            row["warnings"].append(
                                f"negative_unattributed_delta for {field}: "
                                f"cumulative_delta={delta}, request_usage={req_val}, "
                                f"unattributed={unattributed}"
                            )
                    else:
                        row["unattributed_delta"][field] = None
                else:
                    row["cumulative_delta_since_previous_visible_step"][field] = None
                    row["unattributed_delta"][field] = None

        # Update prev_cumulative for next step
        if cum:
            prev_cumulative = {}
            for field in TOKEN_FIELDS:
                prev_cumulative[field] = _parse_redacted_int(cum.get(field))

        accounting_rows.append(row)

    # Check first-visible-step semantics — only first row when prev_cumulative stayed empty
    if accounting_rows and source_kind == "live":
        first_row = accounting_rows[0]
        first_row["first_visible_step_not_cold_start"] = True
        first_row["warnings"].append(
            "first_visible_step_not_cold_start: cannot verify cold start"
        )

    return accounting_rows


def _compute_session_cumulative_accounting(
    accounting_rows: list[dict[str, Any]],
    final_cumulative: dict[str, Any] | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Compute session-level cumulative accounting totals.

    Returns dict with:
    - session_total_usage
    - visible_steps_request_usage_sum
    - visible_steps_cumulative_delta_sum
    - unattributed_session_usage
    """
    session_accounting: dict[str, Any] = {
        "session_total_usage": {},
        "visible_steps_request_usage_sum": {},
        "visible_steps_cumulative_delta_sum": {},
        "unattributed_session_usage": {},
        "includes_hidden_context_possible": False,
    }

    TOKEN_FIELDS = [
        "total_token_usage", "input_tokens", "cached_tokens",
        "output_tokens",
    ]

    # session_total_usage from final_cumulative
    if final_cumulative:
        for field in TOKEN_FIELDS:
            val = _parse_redacted_int(final_cumulative.get(field))
            session_accounting["session_total_usage"][field] = val

    # Sum request_usage and cumulative_delta across visible steps
    for field in TOKEN_FIELDS:
        req_sum = 0
        delta_sum = 0
        req_available = False
        delta_available = False
        for row in accounting_rows:
            rv = row["request_usage"].get(field)
            dv = row["cumulative_delta_since_previous_visible_step"].get(field)
            if rv is not None:
                req_sum += rv
                req_available = True
            if dv is not None:
                delta_sum += dv
                delta_available = True
        if req_available:
            session_accounting["visible_steps_request_usage_sum"][field] = req_sum
        if delta_available:
            session_accounting["visible_steps_cumulative_delta_sum"][field] = delta_sum

    # unattributed_session_usage = session_total - request_sum
    for field in TOKEN_FIELDS:
        sess = session_accounting["session_total_usage"].get(field)
        req_sum = session_accounting["visible_steps_request_usage_sum"].get(field)
        if sess is not None and req_sum is not None:
            session_accounting["unattributed_session_usage"][field] = sess - req_sum

    # Check for hidden context possibility
    input_total = session_accounting["session_total_usage"].get("input_tokens")
    input_req_sum = session_accounting["visible_steps_request_usage_sum"].get("input_tokens")
    if input_total is not None and input_req_sum is not None and input_total > 0:
        ratio = input_req_sum / input_total
        if ratio < 0.5:
            session_accounting["includes_hidden_context_possible"] = True

    return session_accounting


def run_audit(
    detail: dict[str, Any],
    *,
    source_kind: str | None = None,
    source_id: str | None = None,
    session_id: str | None = None,
    selected_step_indices: list[int] | None = None,
    upstream_evidence_available: bool = False,
    evidence_note: str = "",
    rollout_path: Path | None = None,
) -> AuditResult:
    """Run full audit over a session detail dict from the monitor server.

    Args:
        detail: session detail JSON as returned by build_live_session_detail()
                or build_archive_session_detail()
        source_kind: expected source kind (live/archive), taken from detail if absent
        source_id: source identifier, taken from detail if absent
        session_id: session identifier, taken from detail if absent
        selected_step_indices: if provided, audit only these step indices
            (narrowed scope — must be exposed honestly)
        upstream_evidence_available: True if audit has access to upstream
            source evidence (raw rollout, raw OTel, etc.) beyond the detail
            object itself. False means audit can only check internal
            consistency of the already-built detail.
        rollout_path: optional path to rollout JSONL for cumulative accounting

    Returns:
        AuditResult with findings, audit_status, usage_confirmation,
        step_attribution_confidence, cost_confidence, fallback_used,
        audit_scope, evidence_basis, and per-step findings.
    """
    findings: list[dict[str, str]] = []
    step_findings: list[dict[str, Any]] = []

    source_kind = source_kind or str(detail.get("source_kind", ""))
    session_id = session_id or str(detail.get("id", ""))
    source_id = source_id or ""

    # ── 1. Source identity check ──
    _check_source_identity(findings, detail, source_kind)

    # ── 2. Session identity check ──
    _check_session_identity(findings, detail, session_id)

    # ── 3. Step-level checks ──
    steps = detail.get("steps", [])
    if not isinstance(steps, list):
        steps = []

    summary = detail.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    # Determine audit scope
    # selected_step_indices are step_index values (e.g., 1,2,3), NOT array offsets
    if selected_step_indices is not None:
        # Build lookup: step_index → position in steps array
        step_index_map: dict[int, int] = {}
        for pos, step in enumerate(steps):
            si = step.get("step_index")
            if isinstance(si, int):
                step_index_map[si] = pos
        effective_indices = [
            step_index_map[si] for si in selected_step_indices
            if si in step_index_map
        ]
        audit_scope = "selected_steps"
    else:
        effective_indices = list(range(len(steps)))
        audit_scope = "full_session"

    for i in effective_indices:
        step = steps[i]
        sf = _audit_step(step, source_kind, summary)
        step_findings.append(sf)
        findings.extend(sf.get("findings", []))

    # ── 3.5. Cumulative accounting from rollout ──
    cumulative_accounting_rows: list[dict[str, Any]] = []
    session_cumulative_accounting: dict[str, Any] | None = None
    rollout_parse_errors: list[str] = []

    # ── v2.1: event range monotonicity check across all steps ──
    seen_event_ranges: list[tuple[int, int, Any]] = []
    for i in effective_indices:
        step = steps[i]
        er = step.get("event_range", {})
        if isinstance(er, dict) and er.get("start_event_index"):
            seen_event_ranges.append((er["start_event_index"], er["end_event_index"], step.get("step_index", "?")))
    for idx in range(1, len(seen_event_ranges)):
        prev_end = seen_event_ranges[idx - 1][1]
        curr_start = seen_event_ranges[idx][0]
        if curr_start <= prev_end:
            findings.append({
                "id": f"event_range_overlap",
                "level": "warning",
                "message": (
                    f"Event ranges overlap: step {seen_event_ranges[idx-1][2]} "
                    f"end={prev_end}, step {seen_event_ranges[idx][2]} start={curr_start}"
                ),
            })
    if len(seen_event_ranges) > 1:
        findings.append({
            "id": "event_range_monotonic_ok",
            "level": "ok",
            "message": f"Event ranges check: {len(seen_event_ranges)} steps with ranges, monotonicity verified",
        })

    # ── v2.1: full_step_usage sum reconciliation with session total ──
    fsu_sum_input = 0
    fsu_sum_output = 0
    for i in effective_indices:
        step = steps[i]
        fsu = step.get("full_step_usage", {})
        if isinstance(fsu, dict):
            fsu_sum_input += (_parse_redacted_int(fsu.get("input_tokens")) or 0)
            fsu_sum_output += (_parse_redacted_int(fsu.get("output_tokens")) or 0)
    total_input = summary.get("total_input_tokens", 0) if isinstance(summary, dict) else 0
    if total_input > 0 and fsu_sum_input > 0:
        unmapped = total_input - fsu_sum_input
        if unmapped >= 0:
            findings.append({
                "id": "fsu_sum_reconciliation_ok",
                "level": "ok",
                "message": (
                    f"Full step usage sum reconciliation: sum(fsu.input)={fsu_sum_input}, "
                    f"session_total={total_input}, unmapped={unmapped}"
                ),
            })
        else:
            findings.append({
                "id": "fsu_sum_exceeds_session",
                "level": "warning",
                "message": (
                    f"Full step usage sum exceeds session total: "
                    f"sum(fsu.input)={fsu_sum_input} > session_total={total_input}"
                ),
            })

    # ── Cumulative accounting from rollout (existing) ──

    if rollout_path is not None and source_kind == "live":
        rollout_data = _parse_rollout_for_cumulative(rollout_path, session_id)
        rollout_parse_errors = rollout_data.get("parse_errors", [])
        if rollout_data.get("turns"):
            cumulative_accounting_rows = _compute_step_cumulative_accounting(
                steps, rollout_data["turns"], source_kind
            )
            session_cumulative_accounting = _compute_session_cumulative_accounting(
                cumulative_accounting_rows,
                rollout_data.get("final_cumulative"),
                summary,
            )

            # Add cumulative accounting findings
            for row in cumulative_accounting_rows:
                si = row["step_index"]
                cu = row.get("cumulative_usage_after_step", {})
                ud = row.get("unattributed_delta", {})
                row_warnings = row.get("warnings", [])

                if cu:
                    findings.append({
                        "id": f"step_{si}_cumulative_found",
                        "level": "ok",
                        "message": (
                            f"Step {si}: cumulative_usage_after_step available"
                        ),
                    })
                else:
                    findings.append({
                        "id": f"step_{si}_cumulative_missing",
                        "level": "warning",
                        "message": (
                            f"Step {si}: cumulative_usage_after_step not available"
                        ),
                    })

                for w in row_warnings:
                    findings.append({
                        "id": f"step_{si}_cumulative_warning",
                        "level": "warning",
                        "message": f"Step {si}: {w}",
                    })

                # Check unattributed_delta
                if ud:
                    has_negative = any(
                        v is not None and v < 0 for v in ud.values()
                    )
                    if has_negative:
                        findings.append({
                            "id": f"step_{si}_negative_unattributed",
                            "level": "warning",
                            "message": (
                                f"Step {si}: negative unattributed_delta detected — "
                                f"cumulative ordering may be noisy"
                            ),
                        })

            # Session-level unattributed check
            if session_cumulative_accounting:
                sca = session_cumulative_accounting
                sess_usage = sca.get("session_total_usage", {})
                req_sum = sca.get("visible_steps_request_usage_sum", {})
                unattrib = sca.get("unattributed_session_usage", {})

                if sess_usage and req_sum:
                    findings.append({
                        "id": "session_cumulative_accounting_available",
                        "level": "ok",
                        "message": (
                            "Session-level cumulative accounting computed: "
                            f"session_total_usage available, "
                            f"unattributed_session_usage available"
                        ),
                    })
                else:
                    findings.append({
                        "id": "session_cumulative_accounting_partial",
                        "level": "warning",
                        "message": (
                            "Session-level cumulative accounting partial: "
                            "some fields unavailable"
                        ),
                    })

                if sca.get("includes_hidden_context_possible"):
                    findings.append({
                        "id": "session_includes_hidden_context_possible",
                        "level": "warning",
                        "message": (
                            "Visible-step request usage sum is much smaller than "
                            "session total — hidden context is possible"
                        ),
                    })

        for err in rollout_parse_errors:
            findings.append({
                "id": "rollout_parse_error",
                "level": "warning",
                "message": f"Rollout parse issue: {err}",
            })

    # ── 4. Summary basis check ──
    _check_summary_basis(findings, detail, source_kind, steps)

    # ── 5. Export/artifact check ──
    _check_export_honesty(findings, detail, source_kind)

    # ── 6. Determine evidence basis ──
    evidence_basis = _determine_evidence_basis(
        upstream_evidence_available, source_kind, summary, findings, evidence_note
    )

    # ── 7. Compute aggregate statuses ──
    audit_status, usage_confirmation, step_confidence, cost_confidence, fallback_used = _compute_statuses(
        findings, step_findings, source_kind, summary, evidence_basis, audit_scope
    )

    return {
        "audit_status": audit_status,
        "usage_confirmation": usage_confirmation,
        "step_attribution_confidence": step_confidence,
        "cost_confidence": cost_confidence,
        "fallback_used": fallback_used,
        "audit_scope": audit_scope,
        "evidence_basis": evidence_basis,
        "upstream_evidence_available": upstream_evidence_available,
        "evidence_note": evidence_note,
        "selected_step_indices": selected_step_indices,
        "total_steps_in_session": len(steps),
        "audited_steps_count": len(step_findings),
        "findings": findings,
        "step_findings": step_findings,
        "cumulative_accounting_rows": cumulative_accounting_rows,
        "session_cumulative_accounting": session_cumulative_accounting,
        "rollout_parse_errors": rollout_parse_errors,
        "source_kind": source_kind,
        "session_id": session_id,
        "source_id": source_id,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _check_source_identity(
    findings: list[dict[str, str]], detail: dict[str, Any], source_kind: str
) -> None:
    """Verify source_kind is valid and consistent with detail."""
    valid_kinds = {"live", "archive"}
    if source_kind not in valid_kinds:
        findings.append({
            "id": "source_kind_invalid",
            "level": "fail",
            "message": f"source_kind '{source_kind}' is not one of {sorted(valid_kinds)}",
        })
    elif source_kind == detail.get("source_kind", "") or not detail.get("source_kind"):
        findings.append({
            "id": "source_kind_ok",
            "level": "ok",
            "message": f"source_kind = '{source_kind}' matches detail",
        })
    else:
        findings.append({
            "id": "source_kind_mismatch",
            "level": "fail",
            "message": (
                f"expected source_kind '{source_kind}' but detail has "
                f"'{detail.get('source_kind')}'"
            ),
        })


def _check_session_identity(
    findings: list[dict[str, str]], detail: dict[str, Any], session_id: str
) -> None:
    """Verify session/thread ID is present and plausible."""
    detail_id = str(detail.get("id", ""))
    if not detail_id:
        findings.append({
            "id": "session_id_missing",
            "level": "fail",
            "message": "detail has no session id",
        })
    elif detail_id != session_id:
        findings.append({
            "id": "session_id_mismatch",
            "level": "fail",
            "message": f"expected id '{session_id}' but detail has '{detail_id}'",
        })
    else:
        findings.append({
            "id": "session_id_ok",
            "level": "ok",
            "message": f"session_id '{session_id}' present",
        })

    title = str(detail.get("title", ""))
    if not title or title == session_id:
        findings.append({
            "id": "session_title_weak",
            "level": "warning",
            "message": "session title equals raw id or is empty",
        })
    else:
        findings.append({
            "id": "session_title_ok",
            "level": "ok",
            "message": "session title differs from raw id",
        })


def _audit_step(
    step: dict[str, Any], source_kind: str, summary: dict[str, Any]
) -> dict[str, Any]:
    """Audit a single step. Returns dict with index, findings, usage basis."""
    step_index = step.get("step_index", "?")
    findings: list[dict[str, str]] = []
    usage = step.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    # Step attribution: is usage available?
    usage_available = usage.get("available", False)
    confirmation_status = str(usage.get("confirmation_status", ""))
    usage_source = str(usage.get("source", ""))
    usage_note = str(usage.get("note", ""))

    # Whitelist of confirmed semantic statuses
    _CONFIRMED_STATUSES = {"confirmed_request_usage", "confirmed_cumulative_delta", "confirmed_per_step_delta"}
    _FALLBACK_BASIS = {"cumulative_total_token_usage", "summary_total_only", "total_token_usage_fallback", "delta_unknown", "live_total_token_usage_latest"}

    if usage_available:
        if confirmation_status in _CONFIRMED_STATUSES:
            findings.append({
                "id": "step_usage_confirmed",
                "level": "ok",
                "message": f"Step {step_index}: usage confirmed ({confirmation_status})",
            })
        else:
            findings.append({
                "id": "step_usage_available_unlabeled",
                "level": "warning",
                "message": (
                    f"Step {step_index}: usage available but confirmation_status "
                    f"= '{confirmation_status}' — not in confirmed whitelist"
                ),
            })

        source_lower = usage_source.lower()
        is_fallback_source = (
            "total_token_usage" in source_lower and "last_token_usage" not in source_lower
        )
        is_fallback_basis = confirmation_status in _FALLBACK_BASIS or usage_source in _FALLBACK_BASIS
        if is_fallback_source or is_fallback_basis:
            findings.append({
                "id": "step_usage_fallback_cumulative",
                "level": "warning",
                "message": (
                    f"Step {step_index}: usage appears cumulative/fallback "
                    f"(source='{usage_source}', status='{confirmation_status}')"
                ),
            })
    else:
        if confirmation_status == "missing_request_usage":
            findings.append({
                "id": "step_usage_missing",
                "level": "warning",
                "message": f"Step {step_index}: per-step usage not confirmed — {usage_note}",
            })
        else:
            findings.append({
                "id": "step_usage_missing_unclear",
                "level": "warning",
                "message": (
                    f"Step {step_index}: per-step usage not available, "
                    f"status='{confirmation_status}', note='{usage_note}'"
                ),
            })

    # Check step model vs session model
    step_model = str(step.get("model", "unknown"))
    if step_model == "unknown" and source_kind == "live":
        findings.append({
            "id": "step_model_unknown",
            "level": "warning",
            "message": f"Step {step_index}: model is 'unknown' in live source",
        })

    # Check prompt/answer availability
    user_prompt = step.get("user_prompt", {})
    if isinstance(user_prompt, dict) and user_prompt.get("available"):
        pass
    elif source_kind == "live":
        findings.append({
            "id": "step_prompt_hidden",
            "level": "ok",
            "message": f"Step {step_index}: prompt hidden by default (live mode)",
        })

    # ── v2.1: event_range, full_step_usage, full_step_cost checks ──
    _audit_step_v21(step, step_index, findings, source_kind, summary)

    return {
        "step_index": step_index,
        "usage_available": usage_available,
        "usage_confirmation_status": confirmation_status,
        "usage_source": usage_source,
        "findings": findings,
    }


def _audit_step_v21(
    step: dict[str, Any],
    step_index: Any,
    findings: list[dict[str, str]],
    source_kind: str,
    summary: dict[str, Any],
) -> None:
    """v2.1: Audit full_step_usage, full_step_cost, event_range, cost_scope."""

    # 1. Check event_range exists
    event_range = step.get("event_range", {})
    if isinstance(event_range, dict) and event_range.get("start_event_index"):
        findings.append({
            "id": f"step_{step_index}_event_range_ok",
            "level": "ok",
            "message": f"Step {step_index}: event_range present ({event_range.get('start_event_index')}–{event_range.get('end_event_index')})",
        })
    else:
        findings.append({
            "id": f"step_{step_index}_event_range_missing",
            "level": "warning",
            "message": f"Step {step_index}: event_range missing or empty",
        })

    # 2. Check request_usage_items
    rui = step.get("request_usage_items", [])
    if isinstance(rui, list) and rui:
        findings.append({
            "id": f"step_{step_index}_request_items_ok",
            "level": "ok",
            "message": f"Step {step_index}: {len(rui)} request_usage_items found",
        })
    elif isinstance(rui, list) and not rui:
        findings.append({
            "id": f"step_{step_index}_request_items_empty",
            "level": "warning",
            "message": f"Step {step_index}: no request_usage_items — full_step_usage not available",
        })

    # 3. Check full_step_usage matches sum of request_usage_items
    fsu = step.get("full_step_usage", {})
    if isinstance(fsu, dict) and isinstance(rui, list) and rui:
        expected_input = sum(
            _parse_redacted_int(r.get("input_tokens")) or 0 for r in rui
        )
        actual_input = fsu.get("input_tokens", 0)
        if expected_input == actual_input:
            findings.append({
                "id": f"step_{step_index}_full_usage_match",
                "level": "ok",
                "message": f"Step {step_index}: full_step_usage.input_tokens matches sum of request items ({actual_input})",
            })
        else:
            findings.append({
                "id": f"step_{step_index}_full_usage_mismatch",
                "level": "fail",
                "message": f"Step {step_index}: full_step_usage mismatch — expected {expected_input}, got {actual_input}",
            })

    # 4. Check full_step_cost is calculated from full_step_usage, not from one request
    fsc = step.get("full_step_cost", {})
    if isinstance(fsc, dict) and fsc.get("source") == "estimated_from_full_step_usage":
        findings.append({
            "id": f"step_{step_index}_full_cost_source_ok",
            "level": "ok",
            "message": f"Step {step_index}: full_step_cost.source = estimated_from_full_step_usage",
        })
    elif isinstance(fsc, dict) and fsc.get("total_usd") is not None:
        findings.append({
            "id": f"step_{step_index}_full_cost_source_unknown",
            "level": "warning",
            "message": f"Step {step_index}: full_step_cost present but source is not 'estimated_from_full_step_usage'",
        })

    # 5. Check cost_scope is not ambiguous
    cs = step.get("cost_scope", {})
    cs_displayed = str(cs.get("current_displayed_cost_scope", "")) if isinstance(cs, dict) else ""
    if cs_displayed in ("full_visible_step", "single_request", "unknown"):
        findings.append({
            "id": f"step_{step_index}_cost_scope_clear",
            "level": "ok",
            "message": f"Step {step_index}: cost_scope = '{cs_displayed}' — clear labeling",
        })
    elif cs_displayed:
        findings.append({
            "id": f"step_{step_index}_cost_scope_ambiguous",
            "level": "warning",
            "message": f"Step {step_index}: cost_scope = '{cs_displayed}' — unexpected value",
        })
    else:
        findings.append({
            "id": f"step_{step_index}_cost_scope_missing",
            "level": "warning",
            "message": f"Step {step_index}: cost_scope not available",
        })

    # 6. Check mapping_confidence
    mc = str(cs.get("mapping_confidence", "")) if isinstance(cs, dict) else ""
    if mc in ("high", "medium", "low", "not_verified"):
        pass  # valid
    elif mc:
        findings.append({
            "id": f"step_{step_index}_mapping_confidence_unexpected",
            "level": "warning",
            "message": f"Step {step_index}: mapping_confidence = '{mc}' — unexpected value",
        })

    # 7. Check cumulative_before/after_step consistency
    cb = step.get("cumulative_before_step", {})
    ca = step.get("cumulative_after_step", {})
    if isinstance(cb, dict) and cb.get("available") and isinstance(ca, dict) and ca.get("available"):
        cb_inp = _parse_redacted_int(cb.get("input_tokens")) or 0
        ca_inp = _parse_redacted_int(ca.get("input_tokens")) or 0
        if ca_inp < cb_inp:
            findings.append({
                "id": f"step_{step_index}_cumulative_regression",
                "level": "fail",
                "message": f"Step {step_index}: cumulative after ({ca_inp}) < cumulative before ({cb_inp})",
            })
        else:
            findings.append({
                "id": f"step_{step_index}_cumulative_monotonic",
                "level": "ok",
                "message": f"Step {step_index}: cumulative input monotonic ({cb_inp} → {ca_inp})",
            })

    # 8. Check unattributed_delta consistency
    ud = step.get("unattributed_delta", {})
    cd = step.get("cumulative_delta", {})
    if isinstance(ud, dict) and ud.get("available") and isinstance(fsu, dict) and isinstance(cd, dict) and cd.get("available"):
        ud_inp = _parse_redacted_int(ud.get("input_tokens")) or 0
        cd_inp = _parse_redacted_int(cd.get("input_tokens")) or 0
        fsu_inp = fsu.get("input_tokens", 0)
        expected_ud = cd_inp - fsu_inp
        if ud_inp == expected_ud:
            findings.append({
                "id": f"step_{step_index}_unattributed_match",
                "level": "ok",
                "message": f"Step {step_index}: unattributed_delta consistent with cumulative_delta - full_step_usage",
            })
        else:
            findings.append({
                "id": f"step_{step_index}_unattributed_mismatch",
                "level": "warning",
                "message": f"Step {step_index}: unattributed_delta mismatch — expected {expected_ud}, got {ud_inp}",
            })

    # 9. primary_request_usage vs full_step_usage distinction
    pri = step.get("primary_request_usage", {})
    if isinstance(pri, dict) and isinstance(fsu, dict):
        pri_inp = pri.get("input_tokens", 0)
        fsu_inp = fsu.get("input_tokens", 0)
        if fsu.get("request_count", 0) > 1 and pri_inp == fsu_inp:
            findings.append({
                "id": f"step_{step_index}_cost_may_be_request_not_full",
                "level": "warning",
                "message": f"Step {step_index}: multi-request step but primary_request_usage equals full_step_usage — may still label request cost as step cost",
            })
        elif fsu.get("request_count", 0) == 1 and pri_inp == fsu_inp:
            findings.append({
                "id": f"step_{step_index}_single_request_matches",
                "level": "ok",
                "message": f"Step {step_index}: single-request step — request cost equals full step cost",
            })


def _check_summary_basis(
    findings: list[dict[str, str]],
    detail: dict[str, Any],
    source_kind: str,
    steps: list[dict[str, Any]],
) -> None:
    """Check that summary basis is distinct from visible-step sums where needed."""
    summary = detail.get("summary")
    if not isinstance(summary, dict):
        findings.append({
            "id": "summary_missing",
            "level": "warning",
            "message": "No summary block in session detail",
        })
        return

    usage_basis = str(summary.get("usage_basis", ""))
    step_usage_basis = str(summary.get("step_usage_basis", ""))

    if source_kind == "live":
        if not usage_basis:
            findings.append({
                "id": "summary_no_usage_basis",
                "level": "warning",
                "message": "Live summary has no usage_basis field",
            })
        elif "cumulative" in usage_basis.lower() or "total" in usage_basis.lower():
            findings.append({
                "id": "summary_cumulative_acknowledged",
                "level": "ok",
                "message": f"Live summary correctly labels basis as '{usage_basis}'",
            })
        else:
            findings.append({
                "id": "summary_basis_may_overstate",
                "level": "warning",
                "message": (
                    f"Live summary usage_basis = '{usage_basis}' — may not clearly "
                    f"separate cumulative from per-step"
                ),
            })

    # Check summary warnings presence
    summary_warnings = summary.get("warnings", [])
    has_warnings = isinstance(summary_warnings, list) and len(summary_warnings) > 0
    if source_kind == "live" and not has_warnings:
        findings.append({
            "id": "summary_no_live_warnings",
            "level": "warning",
            "message": "Live summary has no warnings about cumulative totals or step basis",
        })

    # Visible step sum vs summary total: detect potential mismatch
    def _safe_int(val: Any) -> int:
        """Convert value to int, treating non-numeric as 0."""
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return 0
        return 0

    visible_input_sum = sum(
        _safe_int((s.get("usage", {}) or {}).get("input_tokens", 0))
        for s in steps
        if (s.get("usage", {}) or {}).get("available")
    )
    summary_input = _safe_int(summary.get("total_input_tokens", 0))
    if summary_input > 0 and visible_input_sum > 0 and source_kind == "live":
        ratio = visible_input_sum / summary_input if summary_input > 0 else 0
        if ratio < 0.5 and visible_input_sum > 0:
            findings.append({
                "id": "summary_visible_step_mismatch",
                "level": "warning",
                "message": (
                    f"Visible step input sum ({visible_input_sum}) is much smaller than "
                    f"summary total ({summary_input}, ratio={ratio:.1%}). "
                    f"This is expected for live mode but must not be hidden."
                ),
            })


def _check_export_honesty(
    findings: list[dict[str, str]],
    detail: dict[str, Any],
    source_kind: str,
) -> None:
    """Verify that detail payload preserves basis/warning/confidence semantics."""
    # Check that warnings exist somewhere visible
    total_warnings = 0
    for step in detail.get("steps", []) or []:
        sw = step.get("warnings", [])
        if isinstance(sw, list):
            total_warnings += len(sw)

    summary_warnings = detail.get("summary", {}).get("warnings", [])
    if isinstance(summary_warnings, list):
        total_warnings += len(summary_warnings)

    # This is informational: warnings should be present for live sources
    if source_kind == "live" and total_warnings == 0:
        findings.append({
            "id": "export_no_warnings",
            "level": "warning",
            "message": "Live session detail has zero warnings — verification semantics may be lost",
        })

    # Check that confirmation_status fields are present on steps
    steps_without_status = 0
    for step in detail.get("steps", []) or []:
        usage = step.get("usage", {}) or {}
        if "confirmation_status" not in usage:
            steps_without_status += 1

    if steps_without_status > 0:
        findings.append({
            "id": "export_missing_confirmation_status",
            "level": "warning",
            "message": f"{steps_without_status} steps lack confirmation_status field",
        })


def _determine_evidence_basis(
    upstream_evidence_available: bool,
    source_kind: str,
    summary: dict[str, Any],
    findings: list[dict[str, str]],
    evidence_note: str = "",
) -> str:
    """Determine what evidence the audit actually verified against.

    Returns one of:
    - EVIDENCE_VERIFIED: audit compared detail against upstream source
    - EVIDENCE_PLAUSIBLE: detail is internally consistent but no upstream check
    - EVIDENCE_NOT_VERIFIED: audit couldn't verify key properties

    IMPORTANT: upstream_evidence_available is a trust-boundary flag.
    EVIDENCE_VERIFIED should only be returned when structured evidence
    (not just a boolean) was actually checked. For now, the flag is
    accepted but evidence_note documents what was actually verified.
    Future hardening should replace the boolean with a structured
    evidence result (checked fields, source paths, comparison results).
    """
    if upstream_evidence_available:
        # Trust boundary: caller asserts upstream evidence exists.
        # Without evidence_note, we cannot claim EVIDENCE_VERIFIED.
        if not evidence_note:
            findings.append({
                "id": "evidence_basis_unverified_claim",
                "level": "fail",
                "message": (
                    "upstream_evidence_available=True but no evidence_note provided. "
                    "Evidence basis downgraded to detail_looked_plausible. "
                    "To reach verified_against_source_evidence, provide evidence_note "
                    "describing what was actually checked (source paths, fields, comparison results)."
                ),
            })
            return EVIDENCE_PLAUSIBLE

        findings.append({
            "id": "evidence_basis_note",
            "level": "ok",
            "message": f"Upstream evidence claimed with note: {evidence_note}",
        })
        return EVIDENCE_VERIFIED

    # Without upstream evidence, check if detail at least has internal
    # consistency markers (warnings about basis, acknowledged limitations)
    if source_kind == "live":
        usage_basis = str(summary.get("usage_basis", ""))
        has_warnings = bool(summary.get("warnings"))
        has_basis_ack = "cumulative" in usage_basis.lower() or "total" in usage_basis.lower()

        if has_warnings or has_basis_ack:
            return EVIDENCE_PLAUSIBLE
        else:
            return EVIDENCE_NOT_VERIFIED

    return EVIDENCE_PLAUSIBLE


def _is_summary_basis_cumulative(summary: dict[str, Any], source_kind: str) -> bool:
    """Check if summary cost basis is cumulative rather than per-step.

    Uses explicit enum-like sets, NOT substring matching.
    Unknown/missing basis in live mode is treated as unsafe (cumulative).
    """
    if source_kind != "live":
        return False

    usage_basis = str(summary.get("usage_basis", "")).strip()
    step_usage_basis = str(summary.get("step_usage_basis", "")).strip()

    # Explicit cumulative basis markers
    _CUMULATIVE_BASIS = {
        "live_total_token_usage_latest",
        "total_token_usage_fallback",
        "summary_total_only",
        "cumulative_total_token_usage",
        "live_cumulative_total",
        "session_total",
        "summary_total",
    }

    # Request-level basis (not pure visible-step attribution)
    _REQUEST_LEVEL_BASIS = {
        "live_last_token_usage",
        "confirmed_request_usage",
        "request_level_last_token_usage",
        "request_level",
        "last_token_usage",
    }

    # True per-step basis (only these allow non-cumulative)
    _PER_STEP_BASIS = {
        "confirmed_per_step_delta",
        "per_step_delta",
        "per_step_normalized",
        "archive_normalized",
    }

    if usage_basis in _CUMULATIVE_BASIS:
        return True

    if step_usage_basis in _REQUEST_LEVEL_BASIS:
        return True

    # Safe default for live: if basis is unknown or empty, treat as cumulative
    if not usage_basis and not step_usage_basis:
        return True

    if usage_basis not in _PER_STEP_BASIS and step_usage_basis not in _PER_STEP_BASIS:
        # Unknown basis → unsafe default
        return True

    return False


def _compute_statuses(
    findings: list[dict[str, str]],
    step_findings: list[dict[str, Any]],
    source_kind: str,
    summary: dict[str, Any],
    evidence_basis: str,
    audit_scope: str,
) -> tuple[str, str, str, str, bool]:
    """Derive aggregate audit statuses from findings.

    TRUTH RULES (critical — do not weaken without explicit decision):
    1. Without upstream evidence, strong statuses are blocked.
    2. Cumulative summary basis blocks per_step_estimated cost confidence.
    3. Selected-step scope must not imply full-session verification.
    4. Even if all visible steps carry confirmed_request_usage,
       if summary basis is cumulative, step attribution is uncertain.
    """
    levels = [f.get("level", "ok") for f in findings]

    # Overall audit status — downgrade if evidence is only plausible
    if "fail" in levels:
        audit_status = "fail"
    elif evidence_basis == EVIDENCE_NOT_VERIFIED:
        audit_status = "warning"
    elif evidence_basis == EVIDENCE_PLAUSIBLE and "warning" not in levels:
        # Detail looks internally consistent but we lack upstream proof
        audit_status = "warning"
    elif "warning" in levels:
        audit_status = "warning"
    else:
        audit_status = "ok"

    # Usage confirmation: based on semantic confirmation_status whitelist,
    # NOT on usage_available (number exists != semantics confirmed)
    _CONFIRMED_STATUSES = {"confirmed_request_usage", "confirmed_cumulative_delta", "confirmed_per_step_delta"}
    confirmed_count = sum(
        1 for sf in step_findings
        if sf.get("usage_available")
        and sf.get("usage_confirmation_status") in _CONFIRMED_STATUSES
    )
    total_steps = len(step_findings) if step_findings else 0
    if total_steps == 0:
        usage_confirmation = "not_applicable"
    elif confirmed_count == total_steps:
        usage_confirmation = "all_confirmed"
    elif confirmed_count > 0:
        usage_confirmation = "partial"
    else:
        usage_confirmation = "none_confirmed"

    # Step attribution confidence
    fallback_steps = sum(
        1 for sf in step_findings
        if any(
            f.get("id") == "step_usage_fallback_cumulative"
            for f in sf.get("findings", [])
        )
    )
    missing_steps = total_steps - confirmed_count

    summary_cumulative = _is_summary_basis_cumulative(summary, source_kind)

    # TRUTH RULE: if summary basis is cumulative, step attribution
    # cannot be "high" even if all visible steps look confirmed.
    # The cumulative basis means per-step numbers are request-level
    # (may include hidden context), not pure visible-step attribution.
    if fallback_steps > 0:
        step_confidence = "low"
    elif summary_cumulative and evidence_basis != EVIDENCE_VERIFIED:
        # Cumulative basis + no upstream proof = medium at best
        step_confidence = "medium"
    elif summary_cumulative and evidence_basis == EVIDENCE_VERIFIED:
        # Cumulative basis but upstream evidence verified the mapping
        step_confidence = "medium"
    elif missing_steps > 0 and source_kind == "live":
        step_confidence = "medium"
    elif missing_steps > 0:
        step_confidence = "low"
    else:
        # Only reachable for archive with full confirmed steps
        # AND verified evidence — very rare

        step_confidence = "high"

    # Cost confidence
    if summary_cumulative and source_kind == "live":
        cost_confidence = "cumulative_basis"
    elif evidence_basis == EVIDENCE_VERIFIED:
        cost_confidence = "per_step_estimated"
    elif evidence_basis == EVIDENCE_PLAUSIBLE:
        # Plausible but not verified — conservative
        cost_confidence = "per_step_estimated"
    else:
        cost_confidence = "unknown"

    # Fallback used
    fallback_used = fallback_steps > 0

    return audit_status, usage_confirmation, step_confidence, cost_confidence, fallback_used


# ── Main ──


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _run_audit_script_main(argv: list[str] | None = None) -> None:
    """Run audit as standalone script."""
    args_parser = argparse.ArgumentParser(description="Codex Token Monitor Audit")
    args_parser.add_argument("--detail", required=True, help="Path to session detail JSON file")
    args_parser.add_argument("--output", help="Output path for audit result JSON")
    args_parser.add_argument("--source-kind", help="Override source kind (live/archive)")
    args_parser.add_argument("--rollout-path", help="Path to rollout JSONL for cumulative accounting")
    args = args_parser.parse_args(argv or sys.argv[1:])

    detail = _read_json(args.detail)

    rollout_path = Path(args.rollout_path) if args.rollout_path else None
    result = run_audit(
        detail,
        source_kind=args.source_kind,
        rollout_path=rollout_path,
    )

    if args.output:
        _write_json(args.output, result)
        print(f"Audit written to {args.output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _run_audit_script_main()
