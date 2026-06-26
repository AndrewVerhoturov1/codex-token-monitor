# Zchat Navigation

## Entry Points

| Entry | Path | Description |
|---|---|---|
| Templates | `.ai/zchat/templates/` | Prompt-pack artifact templates (v2 unified) |
| Schemas | `.ai/zchat/schemas/` | JSON schema definitions for manifest validation |
| Docs | `.ai/zchat/docs/` | Skill contracts, v1 created doc, and documentation |
| Skills | `.ai/zchat/skills/` | OpenCode skill files for Zchat operations |
| Rules | `.ai/zchat/rules/` | Unified contract definition |
| Runtime | `.ai/zchat/runtime/` | Runtime artifacts (gitignored) |

## Runtime Layout

```
.ai/zchat/runtime/
  requests/<ZCHAT-slug>/     # prompt_pack outputs
  quarantine/<ZCHAT-slug>/   # receive_pack quarantine inbox (v2)
  imports/<ZCHAT-slug>/      # import_pack reports (legacy direct-apply)
  reviews/<ZCHAT-slug>/      # verify_pack reports, needs_revision decisions
  accepted/<ZCHAT-slug>/     # accepted decisions
  rejected/<ZCHAT-slug>/     # rejected decisions
  branches/<ZCHAT-slug>/     # branch metadata/passport artifacts
```

## Pipeline (v2)

```
prompt_pack -> [external chat produces ZIP] -> receive_pack (quarantine) -> inspect_verification_pack -> verify_pack -> decision_pack -> [apply_pack planned]
```

## MCP Tools

- `opencode_zchat_prompt_pack` -- Create prompt artifacts with ZCHAT slug ID
- `opencode_zchat_receive_pack` -- Receive ZIP to quarantine (v2, never writes to repo)
- `opencode_zchat_inspect_verification_pack` -- Scan verification files for dangerous patterns (v2)
- `opencode_zchat_import_pack` -- Legacy direct-apply ZIP intake
- `opencode_zchat_verify_pack` -- Verify pack directory, produce machine verdict
- `opencode_zchat_decision_pack` -- Final Codex decision stage (accepted/rejected/needs_revision)

## CLI Entry Points

```
python scripts/codex_token_monitor_opencode_jobs.py --zchat-prompt-pack ...
python scripts/codex_token_monitor_opencode_jobs.py --zchat-receive-pack <zip>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-inspect-verification-pack <quarantine_dir>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-import-pack <zip>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-verify-pack <dir>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-decision-pack --zchat-subject-id <id> --zchat-decision-verdict <verdict>
```

## Core Implementation

- `scripts/codex_token_monitor_opencode_jobs.py` -- All zchat logic including v2 modes
- `scripts/codex_token_monitor_opencode_jobs_mcp.py` -- MCP wrapper with v2 tools
- `scripts/git_utils.py` -- ZCHAT slug IDs, branch automation helpers

## Tests

- `tests/test_zchat.py` -- Unit tests for all zchat operations including v2
- `tests/test_opencode_jobs_mcp.py` -- MCP integration tests including v2 tools
