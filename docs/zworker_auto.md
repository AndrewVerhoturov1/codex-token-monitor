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

## Limitations

- No browser automation for password/2FA/CAPTCHA
- No headless mode (Chrome headful only)
- No multi-browser support
- No permanent environment config changes
- web-runner requires playwright and Chrome