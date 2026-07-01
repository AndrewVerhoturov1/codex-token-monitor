# Forensic Summary: zworker-auto Launch Failure Cluster

## Overview

A recurring failure pattern in zworker-auto orchestration — observed across 8+
recent sessions between 2026-06-30T12:00 and 2026-07-01T00:00. The common
signature: prompt_pack succeeds, then web-runner is invoked but fails before
any meaningful web session (no PROMPT_SENT, no ZIP, no handoff). Manual
recovery via direct `zworker_chatgpt_web_runner.py --cdp-url ... --handoff`
succeeds reliably on the same machine.

## Relevant Sessions

| Request ID | Phase Reached | Terminal State / Error | First Real Blocker | Why It Matters |
|---|---|---|---|---|
| `ZWORKER-20260630-233810-zworker-auto-codex-thread-019f1904-19b9-79e1-a8f` | prompt_pack complete → web-runner invoked | `FAILED_ATTACH_REQUIRED` — runner requires `--cdp-url` in zworker-auto mode | zworker-auto orchestration invoked web-runner in launch-mode without resolving CDP `webSocketDebuggerUrl` first | Most recent example; prompt_pack + manifest created but auto-runner cannot attach to live Chrome |
| `ZWORKER-20260630-233217-analyze-a-recurring-zworker-auto-launch-failure` | prompt_pack complete | `AWAITING_ZIP` (stuck) | Diagnostic request itself; no ZIP intake happened. Demonstrates the diagnostic cycle also stalls. | Shows the auto state machine can hang waiting for ZIP that never arrives |
| `ZWORKER-20260630-173900-token-monitor-truthful-raw-session-step-model-ca` | prompt_pack complete → web-runner invoked | `FAILED_ATTACH_REQUIRED` — same CDP resolution failure | _Same root cause_: auto orchestration called runner without attach-mode CDP url | Second independent auto-run with identical CDP failure. Not a one-off glitch. |
| `ZWORKER-20260630-181946-token-monitor-truthful-timeline-implement-token` | prompt_pack may not have completed | `FAILED_REQUEST_NOT_FOUND` — web-runner could not find `prompt.md` | Request artifacts missing or slug validation blocked prompt_pack. Web-runner started with no prompt. | Chain failure: stage 1 (prompt_pack) silently incomplete, stage 2 (web-runner) proceeds anyway |
| `ZWORKER-20260630-125612-implement-the-full-first-playable-browser-rts-pr` | prompt_pack complete | `FAILED` (auto state machine terminal) | Web-runner state shows HANDOFF_DONE but auto-orchestrator still recorded FAILED, suggesting orchestration vs web-runner state divergence | Proof that auto and web-runner run_state.json are not reconciled |
| `ZWORKER-20260630-130500-token-monitor-truthful-timeline-implement` | prompt_pack complete | `FAILED` (auto state machine terminal) | No web-runner session artifacts created at all | Silent failure: auto-orchestrator marked FAILED without a clear web-runner error trail |
| `ZWORKER-20260701-003700-current-md-step-detail-export-fix` | prompt_pack complete | `FAILED` (auto state machine terminal) | Second-most-recent auto FAILED with no web session evidence | Pattern persists into latest runs |
| `ZWORKER-20260701-003815-current-md-token-monitor-markdown-step-ui-repo-a` | prompt_pack complete | `FAILED` (auto state machine terminal) | Same as above — no web-runner session artifacts | Tight temporal clustering with previous row |

## Root Cause Ranking

1. **CDP resolution gap (most frequent, highest confidence)**: zworker-auto
   orchestration calls the web-runner without resolving/forwarding the CDP
   `webSocketDebuggerUrl`. The skill says "prefer attach-mode" and "check
   `http://127.0.0.1:9222/json/version` first", but the auto-orchestrator code
   path does not implement this preflight. The runner then fails with
   `FAILED_ATTACH_REQUIRED` because `zworker-auto` mode forbids launching a
   fresh browser.

2. **Silent prompt_pack failure (high severity)**: `_zworker_validate_request_id_slug`
   can block prompt.md creation. When the slug validation rejects the request_id,
   the prompt_pack stage returns `status: failed` but the auto-orchestrator may
   still invoke the web-runner, which then cannot find prompt.md.

3. **Split state blindness (medium severity)**: The auto-orchestrator writes to
   `runtime/auto/<id>/run_state.json` while the web-runner writes to
   `runtime/web/sessions/<id>/run_state.json`. Neither reads the other's state
   as primary truth. The auto-orchestrator effectively only polls for ZIP
   existence, missing web-runner progression entirely.

4. **Slug validation fragility (medium severity)**: `_zworker_validate_request_id_slug`
   enforces that the request_id must end with the task-derived slug. When the
   auto-orchestrator generates a request_id from a Codex thread context (like
   `...-codex-thread-019f1904-19b9-79e1-a8f`), the slug validation can reject
   it because the slug does not match the task text.

5. **No preflight artifact check (low-medium severity)**: Before invoking the
   web-runner, the auto-orchestrator does not verify that prompt.md exists,
   manifest is valid, or CDP is reachable. Missing any one of these preconditions
   guarantees failure.

## Why Manual Recovery Works Better Than Auto

When a human (or Codex following the skill's explicit instructions) runs the
recovery path directly:

- CDP URL is explicitly resolved via `Invoke-WebRequest` against
  `http://127.0.0.1:9222/json/version` before calling the web-runner.
- The direct `zworker_chatgpt_web_runner.py --cdp-url ws://... --handoff`
  invocation is used, bypassing the auto-orchestrator's launch-mode logic.
- No slug validation gate blocks the request — the direct runner accepts any
  valid request_id.
- State is observed from a single source (web-runner run_state.json) rather
  than split across two independent state machines.
- The human can verify prompt.md existence before launching the web phase.

In auto mode, none of these preconditions are checked. The orchestration
proceeds blindly, making failure inevitable when any precondition is unmet.
