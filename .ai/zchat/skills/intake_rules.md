# Zchat ZIP Intake Rules (OpenCode Skill)

## Purpose

This skill defines the mandatory intake contract for any OpenCode agent that receives a Zchat ZIP pack. The agent MUST follow this sequence exactly.

## Fixed Sequence (fail-fast preflight)

### 1. VALIDATE
Structural check of ZIP contents:
- ZIP MUST contain `manifest.json`, `checksums.sha256`, `payload/` directory.
- `manifest.json` MUST validate against `schemas/import_manifest_schema.json`.
- `checksums.sha256` MUST be present and non-empty.
- Stop condition: missing required files → `rejected_structural`.

### 2. SECURITY_SCAN
Path traversal and scope validation:
- Forbidden: absolute paths, `..` traversal, `.git/`, `.env*`, paths starting with `.ai/zchat/`, any path escaping repo root.
- Allowed: only relative paths within the repository scope.
- Stop condition: any violation → `rejected_scope`.

### 3. EXTRACT_APPLY
Apply payload to working tree:
- Extract `payload/` files to repository root.
- Each file path MUST be listed in `manifest.json.payload_files`.
- SHA256 of each extracted file MUST match manifest and checksums.
- Stop condition: checksum mismatch → `rejected_structural`.

### 4. VERIFY_INPUTS
Verify all inputs are consistent:
- `manifest.json` and `checksums.sha256` MUST be self-consistent.
- Every payload file listed in manifest MUST exist after extract.
- Stop condition: inconsistency → `rejected_structural`.

### 5. REPORT
Write `import_report.md`:
- Summary of actions taken.
- File listing with checksums.
- Final verdict.

## Verdicts

- `accepted_for_review`: All checks passed, ready for human review.
- `rejected_structural`: ZIP structure, manifest, or checksum failure.
- `rejected_scope`: Path traversal, forbidden paths, scope violation.
- `needs_codex_decision`: Ambiguous case requiring manual decision.

## Security Rules

- No `.git/` files.
- No `.env*` files.
- No absolute paths.
- No `..` in paths.
- No `.ai/zchat/` paths.
- All extracted files MUST be within repository root bounds.
