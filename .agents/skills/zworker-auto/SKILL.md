---
name: zworker-auto
description: Use when the user explicitly invokes `/zworker-auto` or when the main routing skill deliberately selects Route W / Web Zworker Auto for a high-reasoning phase with sufficient published GitHub context.
---

# Zworker Auto

## Purpose

Load this skill only for the explicit `zworker-auto` route or when the main
route planner deliberately selects Route W / Web Zworker Auto for a meaningful
phase.

Do not load it for ordinary local repo work.
Do not load it merely for ordinary OpenCode delegation.
Do not load it for manual `/zworker`.
Do not load it when GitHub context is not publishable for the needed Web phase.

`/zworker-auto` means Codex should execute the external ChatGPT Web route
itself:

- build the request artifacts with the existing zworker stage;
- connect to a live Chrome session or start the known Plus profile;
- send the prepared prompt to ChatGPT Web;
- wait for the ZIP;
- download and validate the ZIP;
- run the existing unpack/process handoff locally;
- report the accepted result or the blocker.

Keep the current zworker stages as the source of truth:

- `zworker_prompt_pack`
- `zworker_result_unpack`
- `zworker_process_result`
- `zworker_revision_prompt`

Do not reimplement their logic inside the skill.

## Route W preference

Route W is the preferred strongest-model phase when all are true:

- the task benefits from high reasoning quality;
- GitHub context is current and sufficient;
- the output can be returned as a zworker ZIP.

Before sending a prompt to ChatGPT Web:

- run Route A reconnaissance if repo facts are needed;
- ensure GitHub/raw URLs are current;
- use a temporary context branch when needed;
- do not send local-only assumptions.

## Published GitHub Context Rule

Before the ChatGPT Web phase, Codex MUST ensure that all required repository
context is available through externally-readable GitHub/raw URLs.

If required files or changes exist only locally, or local state is newer than
GitHub, Codex MUST use OpenCode to publish the minimum required context before
running `zworker-auto`.

Preferred method:

- create or update `zworker-context/<request-id>`;
- push only the files required by the Web phase;
- place raw GitHub URLs from that branch into the prompt.

If the needed context cannot be safely published, Route W is blocked for that
phase and Codex should use Route A / Route C locally or stop with a clear
blocker.

## Phase Composition Rule

`/zworker-auto` does not replace the main route planner.

This skill governs only the specialized external web-execution phase:

- request artifacts
- ChatGPT Web run
- ZIP download
- local handoff

All repo/workspace analysis, context gathering, post-handoff code changes,
verification, and follow-up fixes must still use per-phase routing from
`opencode-mcp-windows-control`.

Within one user request, Codex MAY combine:

- Route A for reconnaissance, reading, and verification
- GitHub/context sync through OpenCode when Web needs fresher published context
- `zworker-auto` for the external ChatGPT Web run
- Route C for hard local post-handoff implementation or fixes
- Route A again for final verification

Do not treat `/zworker-auto` as an exclusive whole-task route.
Treat it as a specialized execution phase inside a multi-route workflow.

## Route W Entrypoint

Route W execution MUST use the MCP tool `opencode_zworker_auto_run`
(namespace `mcp__opencode_jobs`).

Codex MUST call this tool immediately after selecting Route W. If Route W is
selected and no hard blocker exists, the same model turn MUST produce a tool
call — commentary-only "запускаю Route W" without a tool call is forbidden.

If `opencode_zworker_auto_run` is unavailable, Codex MUST stop and report the
blocker. Do not fall back to `zworker_chatgpt_web_runner.py` without explicit
user permission.

The raw `zworker_chatgpt_web_runner.py` script is a manual/diagnostic fallback
only — for human-driven debugging, not for primary Codex execution.

## Route Boundaries

`/zworker` and `/zworker-auto` are different routes.

- `/zworker` = prepare artifacts for a human-mediated external chat
- `/zworker-auto` = Codex performs the web chat flow itself

If the user invoked `/zworker-auto`, do not fall back to the manual `/zworker`
flow unless the user explicitly asks for that fallback.

Example route chain for one request:

1. Route A -> inspect current repo state and gather bounded context
2. GitHub/context sync -> publish the minimum required context when GitHub is stale
3. `zworker-auto` -> run the external ChatGPT Web flow and download the ZIP
4. Route A -> review the ZIP, apply safe changes, and verify
5. Route C -> repair hard local issues if needed
6. Codex -> issue the final decision

## Browser Policy

Use only:

- Google Chrome
- headful mode
- ChatGPT Web
- Playwright attach-mode via CDP when possible

Attach-mode rule:

- always open a dedicated new page in the attached Chrome context
- do not reuse or close the user's existing ChatGPT tab
- do not close an externally owned browser/context on success or failure

Do not use:

- headless mode
- another browser
- password automation
- 2FA automation
- CAPTCHA automation
- private ChatGPT APIs

## Preferred Local Profiles On This Machine

Use this order on the current workstation:

1. `C:\Users\andre\AppData\Local\Temp\chrome-zworker-plus`
2. attach to an already-running Chrome on `127.0.0.1:9222` if it already shows a live Plus session

Known non-primary profiles:

- `C:\Users\andre\AppData\Local\Temp\chrome-zworker-test` may point to a free account
- `D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\.ai\zworker\runtime\web\profiles\chatgpt-main` was observed logged out

Do not assume any non-primary profile is valid for ZIP-producing work without a
live check.

## Working Flow

### 1. Build the request

Create request artifacts with the existing prompt-pack stage first.

Primary command pattern:

```powershell
python scripts/codex_token_monitor_opencode_jobs.py `
  --zworker-prompt-pack `
  --zworker-task "<task>" `
  --zworker-context "<context>" `
  --zworker-allowed-paths "<allowed paths>" `
  --zworker-expected-outputs "<expected outputs>"
```

Read the generated request artifacts from:

- `.ai/zworker/runtime/requests/<request-id>/prompt.md`
- `.ai/zworker/runtime/requests/<request-id>/request_manifest.json`

### 2. Bring up the correct Chrome session

First check whether CDP is already alive:

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9222/json/version'
```

If CDP is offline, start Chrome with the known Plus profile:

```powershell
$profileDir = 'C:\Users\andre\AppData\Local\Temp\chrome-zworker-plus'
Start-Process chrome.exe -ArgumentList @(
  '--remote-debugging-port=9222',
  "--user-data-dir=$profileDir",
  'https://chatgpt.com/'
)
```

Then read `webSocketDebuggerUrl` from:

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9222/json/version'
```

### 3. Verify the account before sending work

Before the real run, verify the browser state:

- ChatGPT composer is visible
- the page is not on a login screen
- the page shows a Plus session signal such as `ChatGPT Plus`, `Plus`, or the
  generic model picker state like `High`

If the page is logged out, stop and ask the user to log in manually in that
browser window.

If an anti-bot challenge appears, the human may need to click through it.
After that, retry the same browser session instead of switching profiles.

### 4. Execute the automated web run

Use `opencode_zworker_auto_run` (primary — Codex execution path):

```text
mcp__opencode_jobs.opencode_zworker_auto_run(
  task_text="<task>",
  context="<context>",
  cdp_url="<ws://...>",
  use_web_runner=true,
  allowed_paths="<paths>",
  source_urls="<raw GitHub URLs>",
  timeout_seconds=1200
)
```

Do NOT call `zworker_chatgpt_web_runner.py` directly in the Codex turn. That
script is a manual diagnostic fallback only (see diagnostic-check sections).

Important:

- keep the 12-minute answer timeout for ChatGPT Web work
- a successful web-runner return must also yield a valid ZIP; `exit 0` without a valid ZIP is a failure, not `awaiting_zip`
- canonical ZIP name is `.ai/zworker/runtime/web/output/<request-id>/<request-id>-zworker-result.zip`
- legacy `<request-id>.zip` may be accepted only for compatibility during transition

### 5. Read result artifacts

Check the runtime outputs:

- `.ai/zworker/runtime/web/sessions/<request-id>/run_state.json`
- `.ai/zworker/runtime/web/output/<request-id>/<request-id>-zworker-result.zip`
- `.ai/zworker/runtime/inbox/<request-id>/process_report.md`

Treat `HANDOFF_DONE` plus process decision `accepted` as success.

## Web-Runner State Progression (Critical Diagnostic Context)

The web-runner follows a strict sequential state machine. Understanding this
progression is essential to avoid false "chat creation failed" diagnosis on
sequential Route W runs.

### State Machine (creation → prompt → answer → download → handoff)

```
CREATED → CHAT_OPENING → CHAT_CREATED
  → MODEL_CHECKING → MODEL_SELECTED
  → PROMPT_SENDING → PROMPT_SENT (/c/... URL appears here)
  → ANSWER_STREAMING → ANSWER_READY
  → ZIP_LINK_WAITING → ZIP_LINK_FOUND
  → ZIP_DOWNLOAD_STARTING → ZIP_DOWNLOAD_STARTED → ZIP_DOWNLOADED
  → ZIP_VALIDATING → ZIP_VALID
  → HANDOFF_UNPACKING → HANDOFF_UNPACKED → HANDOFF_PROCESSING → HANDOFF_DONE
```

### Key Diagnostic Rules (prevents false "chat creation failed" on re-runs)

1. **`CHAT_CREATED` + homepage composer = success**, not failure.
   `open_new_chat` treats a visible homepage composer (textarea/contenteditable)
   as a ready chat input. It sets `CHAT_CREATED` immediately, even when the URL
   is still `https://chatgpt.com/` without a `/c/...` path.

2. **`/c/...` URL appears only after prompt send**, never during `open_new_chat`.
   The first time a `/c/...` conversation URL is written to state is inside
   `send_prompt` → `PROMPT_SENT`. Do not wait for a `/c/...` URL before
   considering chat creation complete.

3. **On sequential Route W runs**, the browser reuses the same ChatGPT session.
   After a prior run, the browser may already be at a `/c/...` URL from the
   previous chat. `open_new_chat` navigates to the homepage — the composer
   appears, `CHAT_CREATED` is set (homepage URL, no new `/c/...` yet). This is
   **normal** and not a failure.

4. **`MODEL_CHECK_DONE` or `MODEL_SELECTED` before prompt send is also normal**
   on a reused session. Do not treat reaching these states as "stuck" or
   "creation failed."

### Distinguish Creation Phase vs Later Phases

| Phase | States | `/c/...` URL? | Meaning |
|---|---|---|---|
| **Creation** | `CHAT_OPENING` → `CHAT_CREATED` | No (homepage) | Chat input ready; model check follows |
| **Model check** | `MODEL_CHECKING` → `MODEL_SELECTED` | No | Model verified on current session |
| **Prompt send** | `PROMPT_SENDING` → `PROMPT_SENT` | Yes (appears here) | Prompt submitted; conversation exists |
| **Answer** | `ANSWER_STREAMING` → `ANSWER_READY` | Yes | ChatGPT producing/generated reply |
| **Download** | `ZIP_LINK_WAITING` → `ZIP_DOWNLOADED` | Yes | ZIP link tracked and ZIP downloaded |
| **Handoff** | `ZIP_VALIDATING` → `HANDOFF_DONE` | Yes | ZIP validated and processed locally |

### Troubleshooting / Diagnostic Checklist

When a run appears stuck or failed, use this checklist to determine whether it
is a real chat-creation failure vs a later-phase wait:

| Observation | Most Likely Cause | Action |
|---|---|---|
| State ≤ `CHAT_CREATED`, homepage visible, composer absent | Real creation failure — sidebar "New chat" also failed | Check browser for login/anti-bot; restart Chrome if needed |
| State = `CHAT_CREATED` or `MODEL_CHECK_DONE`, homepage+composer visible, no `/c/...` | **Not a failure** — creation phase complete, awaiting prompt send | Runner will proceed to prompt send; do not abort |
| State = `PROMPT_SENT`, no `/c/...` URL in state | Prompt sent but /c/ URL not yet captured; may be transient | Check `wait_for_valid_chat_url` in logs; wait for answer phase |
| State = `ANSWER_STREAMING` or `ANSWER_READY`, no ZIP yet | Normal — ChatGPT still generating or ZIP not yet posted | Wait for download phase; check answer timeout |
| State = `ZIP_LINK_WAITING`, no ZIP file on disk | Normal — ZIP link not yet detected in page | Wait for download timeout; check ChatGPT output for ZWORKER_ZIP_READY |
| State = `FAILED` with `FAILED_LOGIN_REQUIRED` | Real login failure | Ask user to log in manually in Chrome |
| State = `FAILED` with `FAILED_MODEL_NOT_VERIFIED` | Model not found | May need `--allow-unverified-model` or different preferred model |

**Golden rule**: If the state log shows `CHAT_CREATED` followed by
`MODEL_CHECKING`/`MODEL_SELECTED`, the creation phase succeeded. The run is
proceeding normally into the prompt phase. Do not restart or re-create the chat.

## Recovery Rules

If the browser was closed:

1. restart Chrome with `chrome-zworker-plus`
2. reconnect via CDP
3. rerun the same request

Usually this does not require a fresh login if the Plus session is still stored
in that profile.

If the run failed before `PROMPT_SENT`, rerun normally.

If the run reached `PROMPT_SENT` or later, do not resend blindly. Reuse the
recorded state and chat whenever possible.

If outer `zworker-auto` state and inner web-runner state disagree, trust the
inner web state from `.ai/zworker/runtime/web/sessions/<request-id>/run_state.json`.

If a ZIP was downloaded but naming/layout differs, prefer the current semantic
handoff logic and evaluate the result by substance, not by cosmetic filenames
alone.

## Result Policy

Accept the run as successful when all are true:

- ChatGPT Web path completed end-to-end
- ZIP was downloaded
- ZIP passed validation/handoff
- `process_result` returned `accepted`

If `process_result` returns `needs_revision`, prepare the revision with the
existing revision stage instead of improvising a new contract.

If `needs_clarification` appears, stop and return the question to the user.

## References

- Local zworker-auto doc: [zworker_auto.md](D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\docs\zworker_auto.md)
- Local web automation doc: [zworker_chatgpt_web_automation.md](D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\docs\zworker_chatgpt_web_automation.md)
- Web runner: [zworker_chatgpt_web_runner.py](D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\scripts\zworker_chatgpt_web_runner.py)
- Prompt/processing entrypoint: [codex_token_monitor_opencode_jobs.py](D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\scripts\codex_token_monitor_opencode_jobs.py)
