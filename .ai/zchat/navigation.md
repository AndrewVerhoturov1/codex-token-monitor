# Zchat Navigation

## Entry Points

| Entry | Path | Description |
|---|---|---|
| Templates | `.ai/zchat/templates/` | Prompt-pack artifact templates |
| Schemas | `.ai/zchat/schemas/` | JSON schema definitions for manifest validation |
| Docs | `.ai/zchat/docs/` | Skill contracts, v1 created doc, and documentation |
| Skills | `.ai/zchat/skills/` | OpenCode skill files for Zchat operations |
| Runtime | `.ai/zchat/runtime/` | Runtime artifacts (gitignored) |

## Runtime Layout

```
.ai/zchat/runtime/
  requests/<ZCHAT-slug>/     # prompt_pack outputs
  imports/<ZCHAT-slug>/      # import_pack reports
  reviews/<ZCHAT-slug>/      # verify_pack reports, needs_revision decisions
  accepted/<ZCHAT-slug>/     # accepted decisions
  rejected/<ZCHAT-slug>/     # rejected decisions
  branches/<ZCHAT-slug>/     # branch metadata/passport artifacts
```

## MCP Tools

- `opencode_zchat_prompt_pack` -- Create prompt artifacts with ZCHAT slug ID
- `opencode_zchat_import_pack` -- Strict ZIP intake with contract validation
- `opencode_zchat_verify_pack` -- Verify pack directory, produce machine verdict
- `opencode_zchat_decision_pack` -- Final Codex decision stage (accepted/rejected/needs_revision)

## CLI Entry Points

```
python scripts/codex_token_monitor_opencode_jobs.py --zchat-prompt-pack ...
python scripts/codex_token_monitor_opencode_jobs.py --zchat-import-pack <zip>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-verify-pack <dir>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-decision-pack --zchat-subject-id <id> --zchat-decision-verdict <verdict>
```

## Core Implementation

- `scripts/codex_token_monitor_opencode_jobs.py` -- All zchat logic
- `scripts/codex_token_monitor_opencode_jobs_mcp.py` -- MCP wrapper
- `scripts/git_utils.py` -- ZCHAT slug IDs, branch automation helpers

## Tests

- `tests/test_zchat.py` -- Unit tests for zchat operations
- `tests/test_opencode_jobs_mcp.py` -- MCP integration tests
