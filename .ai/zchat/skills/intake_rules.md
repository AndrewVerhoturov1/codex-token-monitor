# Zchat ZIP Intake Rules (OpenCode Skill)

## Purpose

This skill defines the mandatory intake contract for any OpenCode agent that receives a Zchat ZIP pack. The agent MUST follow this sequence exactly.

## Fixed Sequence (fail-fast preflight)

### 1. VALIDATE
Structural check of ZIP contents:
- ZIP MUST contain `manifest.json`, `checksums.sha256`, `payload/` directory.
- `manifest.json` MUST pass schema-like manifest validation (manifest_version==1.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, non-empty payload_files list, each entry with path and 64-hex sha256).
- `checksums.sha256` MUST be present and non-empty.
- Stop condition: missing required files or manifest schema violation → `rejected_structural`.

### 2. SECURITY_SCAN
Path traversal, scope, and policy validation:
- Global forbidden: absolute paths, `..` traversal, `.git/`, `.env*`, `.ai/zchat/`, paths escaping repo root.
- **allowed_paths**: if set and non-empty in manifest, every payload file MUST match at least one allowed prefix.
- **forbidden_paths**: if set in manifest, no payload file MAY match any forbidden prefix.
- Global forbidden always stronger than manifest policy.
- Stop condition: any violation → `rejected_scope`.

### 3. EXTRA_FILES_CHECK
- Any file in `payload/` not listed in `manifest.payload_files` → `rejected_structural`.
- No silent ignoring of extra payload files.

### 4. CHECKSUMS
- Every file listed in manifest MUST exist in ZIP `payload/`.
- SHA256 in manifest and checksums.sha256 MUST match actual file data.
- Stop condition: checksum mismatch → `rejected_structural`.

### 5. ATOMIC_COMMIT
- All validation happens in memory first.
- Files are written to target root ONLY after all checks pass.
- If any check fails before the commit step, no file is written.

### 6. REPORT
Write `import_report.md`:
- Summary of actions taken.
- File listing with checksums.
- Final verdict.

## Verdicts

- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest schema, checksum failure, or extra payload files.
- `rejected_scope`: Path traversal, forbidden paths, scope/policy violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

## Security Rules

- No `.git/` files.
- No `.env*` files.
- No absolute paths.
- No `..` in paths.
- No `.ai/zchat/` paths.
- All extracted files MUST be within repository root bounds.
- Global forbidden paths always override manifest-level allowed_paths.
- `imported != accepted`: ZIP is untrusted; files are staged for review only.
- Extra payload files NOT in manifest are always rejected (no silent acceptance).
