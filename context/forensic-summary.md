# Forensic Summary: Zworker-Auto Launch Failure Cluster

## Overview

A recurring failure cluster affects the fully automated Route W / zworker-auto flow (Codex -> ChatGPT Web via Playwright -> ZIP download -> local handoff). The automated launch fails at one of three predictable phases; manual human-mediated recovery (Route A reconnaissance + manual browser paste) consistently succeeds where auto fails. Below is the evidence from local runtime artifacts.

## Session Table

| Request ID | Phase Reached | Terminal State / Error | First Real Blocker | Why It Matters |
|---|---|---|---|---|
| `ZWORKER-20260630-233810-zworker-auto-codex-thread-019f1904-19b9-79e1-a8f` | Browser bring-up / CDP attach | Chrome session not found or hung; CDP `webSocketDebuggerUrl` unreachable | `chrome-zworker-plus` profile state invalid after OS sleep/suspend | Core infra failure — auto cannot recover a suspended browser session |
| `ZWORKER-20260630-233217-analyze-a-recurring-zworker-auto-launch-failure` | Analysis phase only (never reached launch) | Route W blocked early — stale PID accumulation in MCP startup log | `stale_pid_file` + `sibling_starter_best_effort` cascade blocks clean MCP init | MCP transport lifecycle is itself a failure precondition for Route W |
| `ZWORKER-20260630-token-monitor-call-timeline-format` (inbox answer.md) | N/A (manual zworker) | Successful manual run — human-mediated | None (manual worked) | Control case: same infra, human-in-the-loop succeeds |
| `ZWORKER-20260630-151827-token-monitor-raw-markdown-markdown-1-token-moni` (manifest) | Prompt pack only | Never launched (manual audit request) | Context branch not created (`create_branch: false`) | Route W cannot proceed without published GitHub context |
| `codex-token-monitor-opencode-jobs-mcp-startup.log` (2026-06-30 23:25—23:34) | MCP startup | Repeated PID staleness; 8+ sibling starter skip entries per cycle | `stale_pid_file` for pid 28936, then 32060 | MCP process lifecycle management is systematically broken |
| `route_c_round_robin_state.json` (ollama1, ollama2) | Route C fallback | `timed_out` — consecutive timeout failures | `last_error_category: timed_out` on both accounts | Route C (minimax-m2.5) has intermittent availability; compounds W failure |

## Root-Cause Ranking

1. **MCP transport PID lifecycle (Rank 1).** The `opencode-jobs-mcp-startup.log` shows a repeating pattern: stale PID files, sibling starter detection loops, and process accumulation. Each restart appends to the skip list instead of cleaning up. This blocks the MCP transport that Route W and Route C depend on.

2. **Chrome session fragility after OS sleep (Rank 2).** The `chrome-zworker-plus` CDP session does not survive Windows sleep/resume. Auto-recovery (restart Chrome + reconnect) sometimes works but often produces a logged-out or blank session that the Playwright attach cannot authenticate.

3. **Published GitHub context gap (Rank 3).** All zworker-auto requests with `create_branch: false` and no `source_urls` cannot be serviced by Route W. The skill requires externally-readable GitHub URLs, but the auto pipeline skips the context-publish step (Route A -> GitHub sync branch) that would enable it.

4. **Route C timeout compounding (Rank 4).** When Route W fails, the route planner falls back to Route C (minimax-m2.5 via Ollama). But `ollama1` and `ollama2` show consecutive timeouts, creating a double-failure that forces a hard stop with no fallback.

## Why Manual Recovery Works Better Than Auto

| Aspect | Auto (zworker-auto / Route W) | Manual (/zworker + human browser) |
|---|---|---|
| **Chrome session** | Must find/reuse CDP; fragile across suspend | Human opens browser once; no CDP needed |
| **Context publishing** | Often skipped (no GitHub branch created) | Human manually checks GitHub URLs or pastes excerpts |
| **Prompt delivery** | Playwright types into ChatGPT; anti-bot risk | Human copy-pastes; zero anti-bot |
| **ZIP download** | Playwright must detect and download; brittle | Human clicks download; saves reliably |
| **Session recovery** | No retry logic for pre-PROMPT_SENT failures | Human retries by re-pasting in the same tab |
| **MCP dependency** | Requires healthy MCP transport; often broken | Uses none (direct terminal commands) |

The auto path adds three layers of brittleness (CDP session management, anti-bot detection, MCP transport health) that the manual path sidesteps entirely. Until the MCP lifecycle is fixed and the Chrome session has a suspend-resume recovery path, manual `/zworker` will remain the reliable route for external web phases.
