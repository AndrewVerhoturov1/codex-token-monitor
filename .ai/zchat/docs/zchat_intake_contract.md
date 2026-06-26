# Zchat ZIP Intake Contract

## Fixed Sequence (fail-fast preflight)

1. **VALIDATE**: Structural check of ZIP contents.
   - ZIP must contain `manifest.json`, `checksums.sha256`, `payload/` directory.
   - `manifest.json` must match `schemas/import_manifest_schema.json`.
   - `checksums.sha256` must be present and non-empty.
   - Stop conditions: missing required files → `rejected_structural`.

2. **SECURITY_SCAN**: Path traversal and scope validation.
    - Forbidden: absolute paths, `..` traversal, `.git/`, `.env*`, runtime zchat paths (`.ai/zchat/`), any path escaping repo root.
   - Allowed: only relative paths within the repository scope.
   - Stop conditions: any violation → `rejected_scope`.

3. **EXTRACT_APPLY**: Apply payload to working tree.
   - Extract `payload/` files to repository root.
   - Each file path must be in `manifest.json.payload_files`.
   - SHA256 of each extracted file must match manifest.
   - Stop conditions: checksum mismatch → `rejected_structural`.

4. **VERIFY_INPUTS**: Verify all inputs are consistent.
   - `manifest.json` and `checksums.sha256` must be self-consistent.
   - Every payload file listed in manifest must exist after extract.
   - Stop conditions: inconsistency → `rejected_structural`.

5. **REPORT**: Write `import_report.md`.
   - Summary of actions taken.
   - File listing with checksums.
   - Final verdict.

## Verdicts

- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest, or checksum failure.
- `rejected_scope`: Path traversal, forbidden paths, scope violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

## Security Rules

- No `.git/` files (protect git history).
- No `.env*` files (protect secrets).
- No absolute paths (protect filesystem).
- No `..` in paths (protect against traversal).
- No `.ai/zchat/` paths (protect zchat runtime).
- All extracted files must be within repository root bounds.
