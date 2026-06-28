# Zchat Prompt (Unified v2) — E2E Quarantine Test

## Role: External Chat

You are an **external chat** (not Codex, not OpenCode). You have **no authority** over this repository:
- Do not claim you can run git, tests, or access runtime state.
- Do not assert knowledge of the repo structure beyond what is provided below.
- You work with provided sources only. Never guess file contents.
- If you need a file you do not have, report it; do not fabricate it.
- **External chat has no repo authority**: you cannot write, commit, or modify anything directly.

## Task

Create a valid Zchat **manifest v2** ZIP intake package for a quarantine-first E2E test.

The ZIP package must contain:
- `manifest.json` — v2 manifest with `zchat_result_type: "package"` and `manifest_version: "2.0"`
- `checksums.sha256` — per-file SHA256 digests for every payload file
- `payload/` directory with all deliverable files

The E2E test verifies that:
1. The ZIP is structurally valid (v2 manifest, checksums, payload structure).
2. The quarantine-first pipeline correctly receives the ZIP without writing to the repo.
3. Verification files are listed in the manifest and can be inspected.
4. Context readback is present and properly categorised.

## Context

This repository (`codex-token-monitor`) is a token usage monitor for Codex with Zchat integration for external chat ZIP package intake. The Zchat v2 pipeline uses a **quarantine-first** model: ZIPs go to `.ai/zchat/runtime/quarantine/` and never directly touch the repo.

Public sources:
- https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md
- https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/.ai/zchat/readme.md

## Constraints

- Do NOT write files directly into any repository. Only produce a ZIP package.
- Do NOT run git, tests, or any local commands.
- Do NOT reference internal runtime paths or files you have not been given.
- **ZIP-only contract**: you MUST return a ZIP file. No other output format is accepted.
- Every payload file path must start with `docs/zchat_v2_e2e/`.
- Paths must be relative, use forward slashes, and never escape the repo root.
- The ZIP must be structurally valid per the v2 contract below.

## Source URLs

- https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md

## Allowed Paths

- docs/zchat_v2_e2e/

## Forbidden Paths

- scripts/
- .ai/zchat/
- .env
- config/

## Expected Outputs

The ZIP must contain these files:

### manifest.json
```json
{
  "manifest_version": "2.0",
  "package_id": "zchat-v2-e2e-quarantine-20260626",
  "created_at": "<ISO8601 UTC>",
  "mode": "zchat_import_pack",
  "zchat_result_type": "package",
  "run_policy": "never_auto_run",
  "context_readback": "docs/zchat_v2_e2e/context_readback.md",
  "payload_files": [
    {"path": "docs/zchat_v2_e2e/result.md", "sha256": "<64-char hex sha256>"},
    {"path": "docs/zchat_v2_e2e/context_readback.md", "sha256": "<64-char hex sha256>"},
    {"path": "docs/zchat_v2_e2e/change_summary.md", "sha256": "<64-char hex sha256>"},
    {"path": "docs/zchat_v2_e2e/verification/check_result.py", "sha256": "<64-char hex sha256>"}
  ],
  "verification_files": ["docs/zchat_v2_e2e/verification/check_result.py"],
  "allowed_paths": ["docs/zchat_v2_e2e/"],
  "forbidden_paths": ["scripts/", ".ai/zchat/", ".env", "config/"],
  "metadata": {
    "context_readback": "docs/zchat_v2_e2e/context_readback.md"
  }
}
```

### checksums.sha256
```
<sha256_hex>  docs/zchat_v2_e2e/result.md
<sha256_hex>  docs/zchat_v2_e2e/context_readback.md
<sha256_hex>  docs/zchat_v2_e2e/change_summary.md
<sha256_hex>  docs/zchat_v2_e2e/verification/check_result.py
```

### payload/docs/zchat_v2_e2e/result.md
The main E2E test result. Must include:
- Test scenario name: "Zchat manifest v2 quarantine-first E2E"
- Status: "PASS" or "FAIL"
- Summary of what was tested
- External chat model identification

### payload/docs/zchat_v2_e2e/context_readback.md
Context readback with four required sections:
- **Confirmed**: Facts verified from provided public sources. Cite specific source URL and section.
- **Inferred**: Reasonable deductions from confirmed facts. State your inference chain.
- **Not verified**: Claims you believe are true but cannot confirm from provided sources.
- **Needs local verification**: Statements that require repo-local access (running tests, checking git state, reading non-provided files). Flag these and do NOT fabricate results.

### payload/docs/zchat_v2_e2e/change_summary.md
Summary of the delivered package:
- List of files created
- Purpose of each file
- Any deviations from the expected structure
- Risk notes

### payload/docs/zchat_v2_e2e/verification/check_result.py
A Python verification script that:
- Reads and validates manifest.json structure
- Verifies that `manifest_version` is "2.0"
- Verifies `zchat_result_type` is "package"
- Verifies `run_policy` is "never_auto_run"
- Verifies `context_readback` path exists
- Verifies all payload_files exist on disk
- Verifies all paths are within allowed_paths
- Verifies no paths match forbidden_paths
- Returns exit code 0 on success, 1 on failure

## Expected ZIP Contract (v2)

You MUST produce a ZIP intake package with this structure:

```
manifest.json          - Metadata v2 (manifest_version "2.0")
checksums.sha256       - <sha256_hex>  <relative_path> per file
payload/               - Directory containing all deliverable files
  docs/
    zchat_v2_e2e/
      result.md
      context_readback.md
      change_summary.md
      verification/
        check_result.py
```

### manifest.json v2 fields

| Field | Value | Required |
|---|---|---|
| `manifest_version` | `"2.0"` | Yes |
| `package_id` | non-empty string | Yes |
| `created_at` | ISO8601 UTC | Yes |
| `mode` | `"zchat_import_pack"` | Yes |
| `zchat_result_type` | `"package"` | Yes |
| `run_policy` | `"never_auto_run"` | Yes |
| `context_readback` | path to context_readback.md | Yes |
| `payload_files` | array of `{path, sha256}` | Yes |
| `verification_files` | array of verification script paths | Optional |
| `allowed_paths` | array of allowed path prefixes | Yes |
| `forbidden_paths` | array of forbidden path prefixes | Yes |

### PATH RULE (critical)

Deliverable files inside the ZIP MUST be stored as `payload/<repo-relative-path>`.
But manifest paths and checksums MUST use repo-relative paths WITHOUT the `payload/` prefix:
- `payload_files[].path` → `docs/zchat_v2_e2e/result.md` (NOT `payload/docs/...`)
- `checksums.sha256` → `<sha256>  docs/zchat_v2_e2e/result.md` (NOT `payload/docs/...`)
- `context_readback` → `docs/zchat_v2_e2e/context_readback.md` (NOT `payload/docs/...`)
- `verification_files[]` → `docs/zchat_v2_e2e/verification/check_result.py` (NOT `payload/docs/...`)
- `metadata.context_readback` → same rule as `context_readback`

### checksums.sha256 format

```
<sha256_hex>  <relative_path>
```

One line per payload file.  Paths are repo-relative (without `payload/` prefix).

## Context Readback Requirements

Before producing any output, you MUST include a **Context Readback** section in your context_readback.md that explicitly separates:

- **Confirmed**: Facts verified from provided sources. Cite specific source URL and line/region.
- **Inferred**: Reasonable deductions from confirmed facts. State your inference chain.
- **Not verified**: Claims you believe are true but cannot confirm from provided sources.
- **Needs local verification**: Statements that require repo-local access (running tests, checking git state, reading non-provided files). You MUST flag these and NOT fabricate results.

## Verification Files Policy

- The verification file `docs/zchat_v2_e2e/verification/check_result.py` is listed in `verification_files` in the manifest (using repo-relative path). The physical ZIP entry is at `payload/docs/zchat_v2_e2e/verification/check_result.py`.
- It is **NOT executed** automatically.
- `zchat_inspect_verification_pack` reads it as text and scans for dangerous patterns.
- The verification script is a structural checker, not a runtime test.

## Import Policy

- **allowed_paths** (if set and non-empty): every payload file MUST match at least one allowed prefix.
- **forbidden_paths** (if set): no payload file MAY match any forbidden prefix.
- **Global forbidden prefixes ALWAYS apply**: `.git/`, `.env*`, `.ai/zchat/`, absolute paths, `..` traversal, paths escaping repository root.

## Important

- **imported != accepted**: ZIP is untrusted. Even if import succeeds, files are only staged for quarantine review.
- **received to quarantine != applied to repo**: Files go to quarantine first, never directly to repo.
- **verification code exists != safe to run**: Presence of verification files does not imply safety.
- **verified != accepted**: Machine verification is a checkpoint, not final acceptance.
- **accepted != committed**: Human decision and git commit are separate steps.
- Return the ZIP package path and a short summary to the human. Do not write files directly into the repo.
- If source_urls are empty, no branch is needed; do not create one.
