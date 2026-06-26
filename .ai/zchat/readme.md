# Zchat

## What is Zchat

Zchat is a structured protocol for external-to-Codex task delivery. It defines modes
for packaging tasks, receiving results into quarantine, verifying deliverables, inspecting
verification files, and making decisions — all within the codex-token-monitor repository.

A human launches `/Zchat` explicitly. The human delivers a prompt to an external chat, receives
a ZIP back, and runs receive/verify/inspect/decision stages through Codex. The external chat has no
repo authority and ZIPs are treated as untrusted.

## Why ZIP is Untrusted

- The external chat cannot run git, tests, or access runtime state.
- Checksums may be fabricated; every file is verified before acceptance.
- `imported != accepted`: import success means only structural validation passed.
  Human review and a formal decision are still required.
- `received != applied`: ZIP extraction goes to quarantine, never directly to repo.

## Pipeline (v2)

### Current (implemented)

| Stage | Mode | What it does | Output dir |
|---|---|---|---|
| 1. Prompt | `zchat_prompt_pack` | Creates prompt artifacts with policy encoding | `runtime/requests/<slug>/` |
| 2. Receive | `zchat_receive_pack` | Validates ZIP, extracts to quarantine ONLY | `runtime/quarantine/<slug>/` |
| 3. Inspect | `zchat_inspect_verification_pack` | Reads verification_files, scans for dangerous patterns | Inline in quarantine dir |
| 4. Verify | `zchat_verify_pack` | Verifies pack directory, produces machine verdict | `runtime/reviews/<slug>/` |
| 5. Decision | `zchat_decision_pack` | Final Codex decision (accepted/rejected/needs_revision) | `runtime/{accepted,rejected,reviews}/<slug>/` |

### Planned (not yet implemented)

| Stage | Mode | What it will do |
|---|---|---|
| 6. Apply | `zchat_apply_pack` | Apply verified+accepted files from quarantine to repo |

### Legacy (still supported)

| Mode | What it does | Output dir |
|---|---|---|
| `zchat_import_pack` | Legacy direct-apply import (bypasses quarantine) | `runtime/imports/<slug>/` |

## Roles

- **Human**: launches `/Zchat`, delivers prompt to external chat, receives ZIP, runs receive/inspect/verify/decision.
- **External chat**: receives prompt, produces ZIP, has NO repo authority, must not fabricate file contents.
- **Codex/OpenCode**: runs receive (quarantine validation), inspect (safety scan), verify (machine verdict), decision (final ruling).

## Path Policy

Zchat enforces strict path rules on all imports:

- **Global forbidden** (always applied): `.git/`, `.env*`, `.ai/zchat/`, absolute paths, `..` traversal, paths escaping repo root.
- **allowed_paths** (manifest-level, optional): if set, every payload file must match at least one prefix.
- **forbidden_paths** (manifest-level, optional): if set, no payload file may match any prefix.
- Global rules always override manifest-level policies.

## Manifest v2

In addition to v1.0 fields, manifest v2.0 requires:

- `zchat_result_type` in {`advice`, `review`, `package`}
- `run_policy`: `never_auto_run` (default and only valid value)
- `context_readback`: path to context readback file (or via `metadata.context_readback`)
- Optional: `verification_files`: list of paths for safety inspection

## Trust Chain

- **external answer != accepted**: The external chat's response is untrusted by default.
- **created ZIP != received**: Must pass structural validation before receipt.
- **received to quarantine != applied to repo**: Quarantine is a sandbox; apply is separate.
- **verification code exists != safe to run**: Inspection must confirm safety.
- **verified != accepted**: Machine verdict is a checkpoint, not final acceptance.
- **accepted != committed**: Human decision and git commit are separate steps.

## ZIP Intake Contract

Every import ZIP must contain:
- `manifest.json` — metadata with `payload_files` list, each entry has `path` and `sha256`. v2 adds `zchat_result_type`, `run_policy`, `context_readback`, optional `verification_files`.
- `checksums.sha256` — per-file SHA256 verification digests.
- `payload/` — directory containing all deliverable files, relative to repo root. v2 requires `payload/context_readback.md` (or metadata pointer).
- `payload/context_readback.md` (v2 required) — Confirmed/Inferred/Not verified/Needs local verification breakdown.

Extra files in `payload/` not listed in manifest are rejected. Import is fully atomic:
all validation happens in memory first; if any check fails, no file is written to disk.
Receive extracts only to quarantine.

## Verdicts

### Import/Receive/Verify verdicts:
- `accepted_for_review` — all checks passed, ready for human review.
- `rejected_structural` — ZIP structure, manifest schema-like validation, checksum, or extra file failure.
- `rejected_scope` — path traversal, forbidden path, or policy violation.
- `needs_codex_decision` — ambiguous case requiring manual decision.

### Inspection verdicts:
- `safe_to_run` — no dangerous patterns detected in verification files.
- `unsafe` — critical dangerous patterns found (shell, exec, git push, secrets, install, deletion).
- `needs_human_decision` — warning patterns found, human judgment required.
- `not_present` — no verification files specified or directory not found.

### Decision verdicts:
- `accepted` — final acceptance, journaled to `runtime/accepted/`.
- `rejected` — final rejection, journaled to `runtime/rejected/`.
- `needs_revision` — revision needed, journaled to `runtime/reviews/`.

## What the External Chat Must NOT Do

- Claim repo authority or knowledge of repo internals.
- Fabricate file contents without reading actual sources.
- Assert it can run git, tests, or access runtime state.
- Write files directly into the repo (always produce ZIP only).
- Create branches automatically (managed by the prompt passport logic).
- Skip context readback or fact separation requirements.

## Usage

### Via MCP
- `opencode_zchat_prompt_pack(task_text, context, constraints, source_urls, allowed_paths, forbidden_paths, expected_outputs)`
- `opencode_zchat_receive_pack(zip_path, target_root)` — v2 receive to quarantine
- `opencode_zchat_inspect_verification_pack(quarantine_dir)` — v2 safety inspection
- `opencode_zchat_import_pack(zip_path, target_root)` — legacy direct-apply
- `opencode_zchat_verify_pack(pack_dir)`
- `opencode_zchat_decision_pack(subject_id, verdict, rationale, evidence, reviewer)`

### Via CLI
```
python scripts/codex_token_monitor_opencode_jobs.py --zchat-prompt-pack --zchat-task "..." --zchat-allowed-paths "src/,tests/" --zchat-forbidden-paths "secrets/"
python scripts/codex_token_monitor_opencode_jobs.py --zchat-receive-pack <zip>
python scripts/codex_token_monitor_opencode_jobs.py --zchat-inspect-verification-pack <quarantine_dir>
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
  rules/             # Unified contract definition
  runtime/           # Runtime artifacts (gitignored)
    requests/        # prompt_pack outputs
    quarantine/      # receive_pack quarantine inbox (v2)
    imports/         # import_pack reports (legacy)
    reviews/         # verify_pack reports, needs_revision decisions
    accepted/        # accepted decisions
    rejected/        # rejected decisions
    branches/        # branch metadata/passport artifacts
```

## ZCHAT Slug ID

Format: `ZCHAT-YYYYMMDD-HHMMSS-<sha256hex8>`. Generated by `git_utils.zchat_slug_id()`.

## Legacy vs v2

### What was brought from legacy V1/V2/V3
- ZIP contract with manifest.json + checksums.sha256 + payload/
- Path traversal and scope protection (global forbidden paths)
- Allowed/forbidden path policies
- Atomic commit: all validation in memory before writing
- Extra payload detection
- Machine verdicts (accepted_for_review, rejected_structural, rejected_scope)
- Decision journaling (accepted/rejected/reviews)
- Prompt passport with branch decision logic
- Source URL policy (public GitHub raw first)

### What was consciously NOT brought
- Old hierarchy structures — kept current flat zchat system
- Direct file system writes outside repository root (always blocked)
- Auto-apply on receive — replaced with quarantine + planned apply
- Auto-execution of verification scripts — replaced with text-only inspection
- Arbitrary run_policy values — locked to never_auto_run
