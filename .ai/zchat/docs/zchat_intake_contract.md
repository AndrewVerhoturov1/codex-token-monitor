# Zchat ZIP Intake Contract

## Fixed Sequence (fail-fast preflight)

1. **VALIDATE**: Structural check of ZIP contents.
   - ZIP must contain `manifest.json`, `checksums.sha256`, `payload/` directory.
   - `manifest.json` must pass schema-like manifest validation (manifest_version==1.0, non-empty package_id, non-empty created_at, mode==zchat_import_pack, non-empty payload_files list, each with path and 64-hex sha256).
   - `checksums.sha256` must be present and non-empty.
   - Stop condition: missing required files or manifest schema violation → `rejected_structural`.

2. **SECURITY_SCAN**: Path traversal, scope, and policy validation.
   - **Global forbidden** (always enforced): absolute paths, `..` traversal, `.git/`, `.env*`, `.ai/zchat/`, paths escaping repo root.
   - **allowed_paths** (manifest-level): if set and non-empty, every payload file MUST match at least one allowed prefix.
   - **forbidden_paths** (manifest-level): if set, no payload file MAY match any forbidden prefix.
   - Stop condition: any violation → `rejected_scope`.

3. **EXTRA_FILES_CHECK**: Extra payload detection.
   - Any file in `payload/` not listed in `manifest.payload_files` → `rejected_structural`.
   - No silent ignoring of extra payload files.

4. **CHECKSUMS**: Validate all checksums.
   - Every file listed in manifest must exist in ZIP `payload/`.
   - SHA256 in manifest and checksums.sha256 must match actual file data.
   - Stop condition: checksum mismatch → `rejected_structural`.

5. **ATOMIC_COMMIT**: Write files only after all validation passes.
   - All validation happens in memory first.
   - If any check fails before the commit step, no file is written.
   - Only after all checks pass are files written to the target root.

6. **REPORT**: Write `import_report.md`.
   - Summary of actions taken.
   - File listing with checksums.
   - Final verdict.

## Verdicts

- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest schema, checksum failure, or extra payload files.
- `rejected_scope`: Path traversal, forbidden paths, scope/policy violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

## Security Rules

- No `.git/` files (protect git history).
- No `.env*` files (protect secrets).
- No absolute paths (protect filesystem).
- No `..` in paths (protect against traversal).
- No `.ai/zchat/` paths (protect zchat runtime).
- All extracted files must be within repository root bounds.
- Global forbidden paths always override manifest-level allowed_paths.
- `imported != accepted`: ZIP is untrusted; files are staged for human review only.
- Extra payload files not in manifest are always rejected (no silent acceptance).
