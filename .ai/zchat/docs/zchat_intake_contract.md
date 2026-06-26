# Zchat ZIP Intake Contract (v2)

## Fixed Sequence (fail-fast preflight)

### 1. VALIDATE
Structural check of ZIP contents:
- ZIP MUST contain `manifest.json`, `checksums.sha256`, `payload/` directory.
- `manifest.json` MUST pass schema-like manifest validation.
  - For v1.0: manifest_version==1.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, non-empty payload_files list, each with path and 64-hex sha256.
  - For v2.0: manifest_version==2.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, zchat_result_type in {advice, review, package}, run_policy==never_auto_run, context_readback set (top-level or metadata), payload_files with path and 64-hex sha256.
- `checksums.sha256` MUST be present and non-empty.
- v2: `payload/context_readback.md` MUST be present (or pointed to by metadata.context_readback).
- Stop condition: missing required files or manifest schema violation -> `rejected_structural`.

### 2. SECURITY_SCAN
Path traversal, scope, and policy validation:
- Global forbidden: absolute paths, `..` traversal, `.git/`, `.env*`, `.ai/zchat/`, paths escaping repo root.
- **allowed_paths**: if set and non-empty in manifest, every payload file MUST match at least one allowed prefix.
- **forbidden_paths**: if set in manifest, no payload file MAY match any forbidden prefix.
- Global forbidden always stronger than manifest policy.
- Stop condition: any violation -> `rejected_scope`.

### 3. EXTRA_FILES_CHECK
- Any file in `payload/` not listed in `manifest.payload_files` -> `rejected_structural`.
- No silent ignoring of extra payload files.

### 4. CHECKSUMS
- Every file listed in manifest MUST exist in ZIP `payload/`.
- SHA256 in manifest and checksums.sha256 MUST match actual file data.
- Stop condition: checksum mismatch -> `rejected_structural`.

### 5. ATOMIC_COMMIT / QUARANTINE
v1 (legacy import_pack): All validation happens in memory first. Files written to target root ONLY after all checks pass. If any check fails, no file is written.

v2 (receive_pack): All validation happens in memory first. Files extracted ONLY to quarantine (`runtime/quarantine/<slug>/payload/`). NEVER written to repo. Must pass inspect_verification_pack, verify_pack, and decision_pack before any apply.

### 6. REPORT
Write `import_report.md` (legacy) or `receive_report.md` (v2):
- Summary of actions taken.
- File listing with checksums.
- Final verdict.
- v2: explicit quarantine location and next steps.

## Verdicts

### Import/Receive/Verify verdicts:
- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest schema, checksum failure, or extra payload files.
- `rejected_scope`: Path traversal, forbidden paths, scope/policy violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

### Inspection verdicts (v2):
- `safe_to_run`: No dangerous patterns detected in verification files.
- `unsafe`: Critical dangerous patterns found (shell, exec, git push, secrets, install, deletion).
- `needs_human_decision`: Warning patterns found, human judgment required.
- `not_present`: No verification files specified or directory not found.

### Decision verdicts:
- `accepted`: Final acceptance, journaled to `runtime/accepted/`.
- `rejected`: Final rejection, journaled to `runtime/rejected/`.
- `needs_revision`: Revision needed, journaled to `runtime/reviews/`.

## Security Rules

- No `.git/` files (protect git history).
- No `.env*` files (protect secrets).
- No absolute paths (protect filesystem).
- No `..` in paths (protect against traversal).
- No `.ai/zchat/` paths (protect zchat runtime).
- All extracted files must be within repository root bounds.
- Global forbidden paths always override manifest-level allowed_paths.
- `imported != accepted`: ZIP is untrusted; files are staged for human review only.
- `received != applied`: v2 receive extracts to quarantine only.
- Extra payload files not in manifest are always rejected (no silent acceptance).

## v2 Additions

### Manifest v2.0 required fields:
- `zchat_result_type`: one of `advice`, `review`, `package`
- `run_policy`: `never_auto_run` (only valid value)
- `context_readback`: path to context readback file, or via `metadata.context_readback`

### v2 optional fields:
- `verification_files`: list of repo-relative file paths (without `payload/` prefix) for safety inspection

### v2 required payload:
- `payload/context_readback.md`: with Confirmed/Inferred/Not verified/Needs local verification sections (physical ZIP path)

### Path Rule (v2 critical)

Files are stored in the ZIP as `payload/<repo-relative-path>` (physical path).
Manifest and checksum paths MUST be repo-relative WITHOUT the `payload/` prefix.

| Item | Physical ZIP | Manifest/Checksum path |
|---|---|---|
| Deliverable file | `payload/<path>` | `<path>` |
| checksums.sha256 entry | N/A | `<sha256>  <path>` |
| context_readback field | `payload/<path>` | `<path>` |

Example: a file physically at `payload/docs/result.md` appears as `docs/result.md` in `payload_files[].path` and `checksums.sha256`.

### v2 operations:
- `zchat_receive_pack`: extracts to quarantine only, never to repo
- `zchat_inspect_verification_pack`: reads verification files as text, scans for 20+ dangerous patterns

### Planned (not implemented):
- `zchat_apply_pack`: apply verified+accepted files from quarantine to repo (documented planned state only)

## Trust Chain

- external answer != accepted
- created ZIP != received
- received to quarantine != applied to repo
- verification code exists != safe to run
- verified != accepted
- accepted != committed
