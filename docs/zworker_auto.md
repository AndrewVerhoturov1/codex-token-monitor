# zworker-auto Mode

zworker-auto is an orchestration mode that runs on top of the existing zworker stages (prompt_pack, result_unpack, process_result, revision_prompt) without rewriting them.

## Overview

zworker-auto orchestrates the full workflow:
1. **prompt_pack** - Creates prompt.md, prompt_passport.md, request_manifest.json
2. **zip intake** - Accepts a pre-existing ZIP path OR invokes web-runner (optional)
3. **zip pre-validation** - Validates ZIP structure using zworker_web_zip before unpack
4. **result_unpack** - Safely extracts ZIP to inbox directory
5. **process_result** - Reads answer.md, validates sources report, auto-applies in-scope files
6. **auto-revision** - Up to N revision loops if needs_revision (max=2 default)

Stops on: accepted / needs_clarification / revision limit / failures.

## Runtime Artifacts

Created in `.ai/zworker/runtime/auto/<request-id>/`:
- `run_state.json` - Runtime state machine (PROMPT_SENT, AWAITING_ZIP, PROCESSED, etc.)
- `events.jsonl` - Event log for debugging and resume

## Resume-Safe Behavior

- Does NOT resend prompt if state is PROMPT_SENT (unless force_resend=true)
- Resuming reads existing state and returns immediately with await_zip decision

## ZIP Pre-Validation

Before calling result_unpack, zworker-auto validates via `zworker_web_zip.validate_zip`:
- ZIP is valid and readable
- ZIP is not empty
- answer.md exists at ZIP root (not in subdirectory)
- No unsafe paths (absolute, traversal, forbidden prefixes)
- No forbidden paths per manifest
- No files outside allowed scope

This prevents wasted unpack cycles on malformed results.

## State Machine

```
PROMPT_SENT -> AWAITING_ZIP -> ZIP_RECEIVED -> PROCESSED
                                              |
                                    +----------+----------+
                                    |          |          |
                              ACCEPTED   CLARIFICATION  NEEDS_REVISION
                                    |                     |
                              (done)            REVISION_REQUESTED -> AWAITING_ZIP
                                    |                     |
                                    +--- max revisions ---+
                                              |
                                           FAILED
```

## Usage

### CLI
```bash
python scripts/codex_token_monitor_opencode_jobs.py \
    --zworker-auto \
    --zworker-auto-task "Fix login bug" \
    --zworker-auto-context "Use existing auth module" \
    --zworker-auto-max-revisions 2

# Resume from existing run
python scripts/codex_token_monitor_opencode_jobs.py \
    --zworker-auto \
    --zworker-auto-resume ZWORKER-20260629-120000-test
```

### MCP
```python
from mcp import MCPClient

client = MCPClient("opencode_jobs")
result = client.call("opencode_zworker_auto_run", {
    "task_text": "Fix login bug",
    "context": "Use existing auth module",
    "max_revisions": 2,
})

# Pass a pre-existing ZIP (e.g., from manual ChatGPT download)
result = client.call("opencode_zworker_auto_run", {
    "task_text": "Fix login bug",
    "zip_path": "/path/to/result.zip",
})

# Use web-runner for automated ChatGPT interaction
result = client.call("opencode_zworker_auto_run", {
    "task_text": "Fix login bug",
    "use_web_runner": True,
})
```

## Chat Readiness

When using the web-runner (`--use-web-runner`), the runner checks for a visible
homepage composer before attempting any sidebar "New chat" click. If the
composer is present on the homepage, the sidebar click is skipped. This
composer-first strategy prevents unnecessary navigation steps when the chat
input is already available.

## Web-Runner State Progression

The web-runner state machine (from `zworker_chatgpt_web_runner.py` and
`zworker_web_state.py`) follows this sequence:

```
CREATED → CHAT_OPENING → CHAT_CREATED → MODEL_CHECKING → MODEL_SELECTED
  → PROMPT_SENDING → PROMPT_SENT → ANSWER_STREAMING → ANSWER_READY
  → ZIP_LINK_WAITING → ZIP_LINK_FOUND → ZIP_DOWNLOAD_STARTING
  → ZIP_DOWNLOAD_STARTED → ZIP_DOWNLOADED → ZIP_VALIDATING → ZIP_VALID
  → HANDOFF_UNPACKING → HANDOFF_UNPACKED → HANDOFF_PROCESSING → HANDOFF_DONE
```

### Critical: `/c/...` URL appears only after prompt send

The `is_valid_chat_url()` check matches URLs containing `/c/<alphanumeric>`.
This pattern **never** appears during `open_new_chat` — that function navigates
to the homepage and considers a visible composer sufficient to set
`CHAT_CREATED`. The `/c/...` URL is first captured inside `send_prompt` when
state transitions to `PROMPT_SENT`.

**Do not diagnose homepage+composer or `CHAT_CREATED` as "chat creation
failed"**. This is the normal creation-phase terminal state.

### Sequential Route W runs

On a second sequential Route W run, the browser navigates to the ChatGPT
homepage from a prior `/c/...` conversation URL. The composer appears on the
homepage, `open_new_chat` sets `CHAT_CREATED` (homepage URL, no `/c/...`),
`ensure_model` transitions to `MODEL_CHECK_DONE`. This entire sequence is
**normal and correct**. The run proceeds to prompt send, which then captures
the new `/c/...` URL.

### Diagnostic checklist

| State observed | Diagnosis |
|---|---|
| `CHAT_CREATED` + homepage composer visible | Creation succeeded; awaiting model check + prompt send |
| `MODEL_CHECK_DONE` + homepage composer visible | Model verified; ready for prompt send — do not abort |
| `PROMPT_SENT` + `/c/...` URL present | Prompt delivered; awaiting answer/download |
| `ANSWER_READY` + no ZIP yet | ChatGPT finished answering; waiting for ZIP link or download |
| `FAILED` with `FAILED_LOGIN_REQUIRED` | Real failure — user must log in |
| `FAILED` with no prior `CHAT_CREATED` | Real creation failure — browser may be stuck |

## Limitations

- No browser automation for password/2FA/CAPTCHA
- No headless mode (Chrome headful only)
- No multi-browser support
- No permanent environment config changes
- web-runner requires playwright and Chrome