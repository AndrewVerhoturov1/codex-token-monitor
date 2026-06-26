# Zchat ZIP Intake Rules (OpenCode Skill) — v2

## Purpose

This skill defines the mandatory intake contract for any OpenCode agent that receives a Zchat ZIP pack. The agent MUST follow this sequence exactly. v2 adds quarantine, context readback, and verification inspection guardrails.

## Fixed Sequence (fail-fast preflight)

### 1. VALIDATE
Structural check of ZIP contents:
- ZIP MUST contain `manifest.json`, `checksums.sha256`, `payload/` directory.
- `manifest.json` MUST pass schema-like manifest validation.
  - v1.0: manifest_version==1.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, non-empty payload_files list, each with path and 64-hex sha256.
  - v2.0: manifest_version==2.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, zchat_result_type in {advice, review, package}, run_policy==never_auto_run, context_readback set.
- `checksums.sha256` MUST be present and non-empty.
- v2: `payload/context_readback.md` MUST be present or pointed to by metadata.context_readback.
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

### 5. QUARANTINE (v2 receive) / ATOMIC_COMMIT (legacy import)
v2 receive_pack: Files extracted ONLY to quarantine (`runtime/quarantine/<slug>/payload/`). NEVER write to repo.
Legacy import_pack: Files written to target root ONLY after all checks pass. Atomic rollback on failure.

### 6. CONTEXT_READBACK_CHECK (v2)
- v2 manifests require context_readback (as field or metadata pointer).
- Verify `payload/context_readback.md` contains Confirmed / Inferred / Not verified / Needs local verification breakdown.
- Missing or empty context_readback -> `rejected_structural`.

### 7. INSPECT_VERIFICATION (v2)
- If `verification_files` set in v2 manifest, run `zchat_inspect_verification_pack`.
- Reads files as text; does NOT execute them.
- Scans for dangerous patterns: file deletion, writes outside scope, .env/secrets, git commit/push, network/install/download, shell/subprocess/os.system, config mutation, .git access, absolute paths, path traversal.
- Returns verdict: `safe_to_run` / `unsafe` / `needs_human_decision` / `not_present`.

### 8. REPORT
Write `import_report.md` (legacy) or `receive_report.md` (v2):
- Summary of actions taken.
- File listing with checksums.
- Final verdict.
- v2: explicit quarantine location and next steps.

## Verdicts

- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest schema, checksum failure, extra payload, missing context_readback.
- `rejected_scope`: Path traversal, forbidden paths, scope/policy violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

## v2 Inspection Verdicts

- `safe_to_run`: No dangerous patterns detected.
- `unsafe`: Critical dangerous patterns found.
- `needs_human_decision`: Warning patterns found.
- `not_present`: No verification files specified or directory not found.

## Trust Chain (v2)

- **external answer != accepted**
- **created ZIP != received**
- **received to quarantine != applied to repo**
- **verification code exists != safe to run**
- **verified != accepted**
- **accepted != committed**

## Security Rules

- No `.git/` files.
- No `.env*` files.
- No absolute paths.
- No `..` in paths.
- No `.ai/zchat/` paths.
- All extracted files MUST be within repository root bounds.
- Global forbidden paths always override manifest-level allowed_paths.
- `imported != accepted`: ZIP is untrusted; files are staged for review only.
- `received != applied`: v2 receive extracts to quarantine only.
- Extra payload files NOT in manifest are always rejected (no silent acceptance).
- Context readback is MANDATORY for v2 manifests.

## Planned State (not implemented)

- `zchat_apply_pack`: After receive -> inspect -> verify -> decision pipeline passes, apply payload from quarantine to repo. Currently only documented as planned; use `zchat_import_pack` for legacy direct-apply.
