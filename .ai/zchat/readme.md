# Zchat

## What is Zchat

Zchat is a structured protocol for external-to-Codex task delivery. It defines four modes
for packaging tasks, importing results, verifying deliverables, and making decisions — all
within the codex-token-monitor repository.

A human launches `/Zchat` explicitly. The human delivers a prompt to an external chat, receives
a ZIP back, and runs import/verify/decision stages through Codex. The external chat has no
repo authority and ZIPs are treated as untrusted.

## Why ZIP is Untrusted

- The external chat cannot run git, tests, or access runtime state.
- Checksums may be fabricated; every file is verified before acceptance.
- `imported != accepted`: import success means only structural validation passed.
  Human review and a formal decision are still required.

## Modes

| Mode | What it does | Output dir |
|---|---|---|
| `zchat_prompt_pack` | Creates prompt artifacts with policy encoding | `runtime/requests/<slug>/` |
| `zchat_import_pack` | Validates ZIP and atomically imports payload | `runtime/imports/<slug>/` |
| `zchat_verify_pack` | Verifies pack directory, produces machine verdict | `runtime/reviews/<slug>/` |
| `zchat_decision_pack` | Final Codex decision (accepted/rejected/needs_revision) | `runtime/{accepted,rejected,reviews}/<slug>/` |

## Roles

- **Human**: launches `/Zchat`, delivers prompt to external chat, receives ZIP, runs import/verify/decision.
- **External chat**: receives prompt, produces ZIP, has NO repo authority, must not fabricate file contents.
- **Codex/OpenCode**: runs import (structural + scope + checksum validation), verify (machine verdict), decision (final ruling).

## Path Policy

Zchat enforces strict path rules on all imports:

- **Global forbidden** (always applied): `.git/`, `.env*`, `.ai/zchat/`, absolute paths, `..` traversal, paths escaping repo root.
- **allowed_paths** (manifest-level, optional): if set, every payload file must match at least one prefix.
- **forbidden_paths** (manifest-level, optional): if set, no payload file may match any prefix.
- Global rules always override manifest-level policies.

## ZIP Intake Contract

Every import ZIP must contain:
- `manifest.json` — metadata with `payload_files` list, each entry has `path` and `sha256`.
- `checksums.sha256` — per-file SHA256 verification digests.
- `payload/` — directory containing all deliverable files, relative to repo root.

Extra files in `payload/` not listed in manifest are rejected. Import is fully atomic:
all validation happens in memory first; if any check fails, no file is written to disk.

## Verdicts

Import/Verify verdicts:
- `accepted_for_review` — all checks passed, ready for human review.
- `rejected_structural` — ZIP structure, manifest schema-like validation, checksum, or extra file failure.
- `rejected_scope` — path traversal, forbidden path, or policy violation.
- `needs_codex_decision` — ambiguous case requiring manual decision.

Decision verdicts:
- `accepted` — final acceptance, journaled to `runtime/accepted/`.
- `rejected` — final rejection, journaled to `runtime/rejected/`.
- `needs_revision` — revision needed, journaled to `runtime/reviews/`.

## What the External Chat Must NOT Do

- Claim repo authority or knowledge of repo internals.
- Fabricate file contents without reading actual sources.
- Assert it can run git, tests, or access runtime state.
- Write files directly into the repo (always produce ZIP only).
- Create branches automatically (managed by the prompt passport logic).

## Usage

### Via MCP
- `opencode_zchat_prompt_pack(task_text, context, constraints, source_urls, allowed_paths, forbidden_paths, expected_outputs)`
- `opencode_zchat_import_pack(zip_path, target_root)`
- `opencode_zchat_verify_pack(pack_dir)`
- `opencode_zchat_decision_pack(subject_id, verdict, rationale, evidence, reviewer)`

### Via CLI
```
python scripts/codex_token_monitor_opencode_jobs.py --zchat-prompt-pack --zchat-task "..." --zchat-allowed-paths "src/,tests/" --zchat-forbidden-paths "secrets/"
python scripts/codex_token_monitor_opencode_jobs.py --zchat-import-pack <zip>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-verify-pack <dir>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-decision-pack --zchat-subject-id <id> --zchat-decision-verdict <verdict>
```

## Directory Structure

```
.ai/zchat/
  templates/         # Templates for prompt-pack artifacts
  schemas/           # JSON schema definitions for manifest validation
  docs/              # Contracts and documentation
  skills/            # OpenCode skill files
  runtime/           # Runtime artifacts (gitignored)
    requests/        # prompt_pack outputs
    imports/         # import_pack reports
    reviews/         # verify_pack reports, needs_revision decisions
    accepted/        # accepted decisions
    rejected/        # rejected decisions
    branches/        # branch metadata/passport artifacts
```

## ZCHAT Slug ID

Format: `ZCHAT-YYYYMMDD-HHMMSS-<sha256hex8>`. Generated by `git_utils.zchat_slug_id()`.
