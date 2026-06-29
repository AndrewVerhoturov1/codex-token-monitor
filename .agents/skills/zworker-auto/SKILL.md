---
name: zworker-auto
description: Use when the user explicitly invokes `/zworker-auto` or asks Codex to run the fully automated zworker ChatGPT Web route with browser reuse, ZIP download, and automatic handoff into the local repository.
---

# Zworker Auto

## Purpose

Load this skill only for the explicit `zworker-auto` route.

Do not load it for ordinary local repo work.
Do not load it for ordinary OpenCode delegation.
Do not load it for manual `/zworker`.

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

## Preferred Entry On This Machine

For the current workstation, prefer this concrete route:

1. `zworker_prompt_pack`
2. direct `zworker_chatgpt_web_runner.py --cdp-url ... --handoff`
3. existing local handoff through `result_unpack` and `process_result`

Treat this as the primary operational path even though the repository also has
broader `zworker-auto` orchestration code and an MCP wrapper.

## Route Boundaries

`/zworker` and `/zworker-auto` are different routes.

- `/zworker` = prepare artifacts for a human-mediated external chat
- `/zworker-auto` = Codex performs the web chat flow itself

If the user invoked `/zworker-auto`, do not fall back to the manual `/zworker`
flow unless the user explicitly asks for that fallback.

## Browser Policy

Use only:

- Google Chrome
- headful mode
- ChatGPT Web
- Playwright attach-mode via CDP when possible

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

Use the direct web-runner with attach-mode and handoff:

```powershell
python scripts/zworker_chatgpt_web_runner.py `
  --request-id <request-id> `
  --repo-root . `
  --runtime-root .ai/zworker/runtime/web `
  --cdp-url <ws://127.0.0.1:9222/devtools/browser/...> `
  --handoff `
  --chat-timeout-ms 60000 `
  --answer-timeout-ms 720000 `
  --download-timeout-ms 300000
```

Important:

- prefer the direct web-runner attach path for the real browser flow
- do not start with `zworker-auto` launch-mode that opens a fresh browser
- keep the 12-minute answer timeout for ChatGPT Web work

### 5. Read result artifacts

Check the runtime outputs:

- `.ai/zworker/runtime/web/sessions/<request-id>/run_state.json`
- `.ai/zworker/runtime/web/output/<request-id>/<request-id>.zip`
- `.ai/zworker/runtime/inbox/<request-id>/process_report.md`

Treat `HANDOFF_DONE` plus process decision `accepted` as success.

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
