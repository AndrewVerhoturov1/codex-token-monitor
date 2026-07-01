# Zworker ChatGPT Web Automation Helper

Дата документа: 2026-06-29.

Этот helper-slice добавляет сложный слой `ChatGPT Web + Playwright` для будущего режима `zworker-auto`. Он не заменяет существующие стадии zworker и не меняет их runtime contract.

## Scope

Реализуется только:

- Google Chrome;
- headful-режим;
- ручной первичный логин в отдельный профиль;
- Playwright Python;
- реальный ZIP, скачанный из ChatGPT Web;
- pre-validation ZIP до handoff;
- state/runtime слой (`run_state.json`, `events.jsonl`);
- resume-safe защита от повторной отправки prompt.

Не реализуется:

- multi-browser;
- headless;
- Computer Use;
- приватный API ChatGPT;
- автоматизация пароля/2FA/CAPTCHA;
- изменение текущего zworker core.

## Runtime layout

```text
.ai/zworker/runtime/web/
  profiles/chatgpt-main/
  sessions/<request-id>/
    run_state.json
    events.jsonl
    chat_url.txt
    prompt.final.md
    screenshots/
    dom_snapshots/
    traces/
  downloads/<request-id>/
  output/<request-id>/
    <request-id>-zworker-result.zip
    zip_report.json
```

## First manual login

Run:

```bash
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-20260629-000000-login-check ^
  --login-check
```

Use the opened Chrome window to log in manually if needed. The runner must never type password, 2FA code, or solve CAPTCHA.

## Normal run

```bash
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-20260628-193833-2026-06-29-complex-zworker-auto-zworker-scriptsc
```

Without `--handoff`, the runner only downloads and validates the ZIP.

## Run with handoff

```bash
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-20260628-193833-2026-06-29-complex-zworker-auto-zworker-scriptsc ^
  --handoff
```

## Resume

```bash
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-... ^
  --resume ^
  --handoff
```

After `PROMPT_SENT`, the runner must not send the prompt again unless `--force-resend` is explicitly set.

## Chat creation strategy: composer-first, sidebar-fallback

When opening a new chat, the runner follows this order:

1. Navigate to `https://chatgpt.com/`.
2. If the homepage composer (textarea, contenteditable div, or role="textbox")
   is already visible, treat the page as ready — no sidebar interaction needed.
3. Only if the composer is not visible after navigation, fall back to clicking
   a sidebar "New chat" link/button.

This avoids redundant sidebar clicks that can interfere with an already-ready
chat input state.

## Attach-mode ownership rule

When attaching over CDP, the runner must open a dedicated new page in the
existing browser context instead of reusing the first already-open page. It
must close only the page it created itself. It must not close an externally
owned browser window or context unless it had to create a brand-new context.

### Critical: `/c/...` URL never appears during `open_new_chat`

The `open_new_chat` function considers a visible homepage composer a success
and sets state `CHAT_CREATED` **without** requiring or waiting for a `/c/...`
conversation URL. The `/c/...` pattern (matched by `is_valid_chat_url()` in
`zworker_web_state.py`) first appears only after `send_prompt` transitions
state to `PROMPT_SENT`.

**Diagnostic implication**: On sequential Route W runs, the sequence
`CHAT_CREATED` → `MODEL_CHECK_DONE` with a homepage URL (no `/c/...`) is
normal. Do not diagnose this as "chat creation
failed".

### Sequential Route W runs

When the web-runner is invoked repeatedly on the same Chrome session:

1. Prior run left the browser at a `/c/...` conversation URL.
2. `open_new_chat` navigates to `https://chatgpt.com/`.
3. Homepage composer appears → `CHAT_CREATED` (homepage URL).
4. `ensure_model` verifies the model → `MODEL_CHECK_DONE`.
5. `send_prompt` submits the prompt → `PROMPT_SENT` (new `/c/...` captured).
6. Normal answer/download/handoff phases follow.

Steps 2–4 are **not** a creation failure — they are the expected pre-prompt
setup for a fresh conversation on a reused session.

## Model policy

Preferred model labels:

1. `Pro Extended`
2. `Pro Standard`

If neither can be verified, the runner fails with `FAILED_MODEL_NOT_VERIFIED` unless `--allow-unverified-model` is passed for local debugging.

## ZIP markers added to prompt

The runner appends an automation contract that asks ChatGPT Web to attach a ZIP named:

```text
<request-id>-zworker-result.zip
```

and then print:

```text
ZWORKER_ZIP_MANIFEST_BEGIN
request_id: <request-id>
zip_filename: <request-id>-zworker-result.zip
zip_kind: zworker_result
required_root_file: answer.md
ZWORKER_ZIP_MANIFEST_END
ZWORKER_ZIP_READY
```

These markers are text anchors for Playwright. The real acceptance condition is
the downloaded ZIP passing `zworker_web_zip.validate_zip`. Zero-byte files,
non-ZIP downloads, or other invalid artifacts fail the run before handoff.

## Integration status

Current local integration points:

- `scripts/codex_token_monitor_opencode_jobs.py` invokes the web-runner for `zworker-auto`;
- the outer auto-runner treats exit `0` without a valid ZIP as a contract failure;
- `zworker_prompt_pack`, `zworker_result_unpack`, `zworker_process_result`, and `zworker_revision_prompt` remain the source of truth.

## Verification

Unit tests in this helper slice do not require a browser:

```bash
python -m pytest tests/test_zworker_web_state.py tests/test_zworker_web_zip.py
```

Live browser POC is manual/local only:

```bash
python scripts/zworker_chatgpt_web_runner.py --request-id <id> --login-check
python scripts/zworker_chatgpt_web_runner.py --request-id <id> --model-check
python scripts/zworker_chatgpt_web_runner.py --request-id <id> --handoff
```

## Attach Mode (CDP)

Instead of launching a new Chrome browser, you can attach to an already-running Chrome via CDP (Chrome DevTools Protocol). This bypasses anti-bot detection that may occur during browser cold-start launch.

### Start Chrome with remote debugging

```bash
# Windows: start Chrome with remote debugging port
start chrome --remote-debugging-port=9222 --user-data-dir="%TEMP%\chrome-zworker-debug"

# Or use existing profile
start chrome --remote-debugging-port=9222 --user-data-dir="C:\Path\To\Your\Profile"
```

The CDP WebSocket URL will be something like:
- `ws://localhost:9222/devtools/browser/abc123-...`

### Run attach-mode via CLI

```bash
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-20260629-123456-test ^
  --cdp-url ws://localhost:9222/devtools/browser/abc123
```

### Run attach-mode via MCP

```python
result = client.call("opencode_zworker_auto_run", {
    "task_text": "Fix login bug",
    "use_web_runner": True,
    "cdp_url": "ws://localhost:9222/devtools/browser/abc123",
})
```

### State metadata

When using attach-mode, the runtime state will contain:
- `browser_mode: "attach"`
- `cdp_url: "<ws://...">`

When using normal launch-mode:
- `browser_mode: "launch"` (not explicitly set, implied)
- `profile_dir: "<path>"`

### Attach smoke test

```bash
# First, start Chrome manually
start chrome --remote-debugging-port=9222 --user-data-dir="%TEMP%\chrome-zworker-test"

# Then run attach-mode check (no login required)
python scripts/zworker_chatgpt_web_runner.py ^
  --request-id ZWORKER-TEST-CDPTEST ^
  --cdp-url ws://localhost:9222/devtools/browser/xxx ^
  --login-check
```
