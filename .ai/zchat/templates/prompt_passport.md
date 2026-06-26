# Prompt Passport

- **Request Name**: {request_name}
- **Zchat ID**: {request_id}
- **Goal**: {task}
- **Prompt file**: `{prompt_path}`

## Canonical Public Docs

- **Static Manual**: {static_manual_url}
- **Repo Navigation**: {repo_navigation_url}

## Required Reading

{required_reading}

## Required Task Source URLs

{required_task_source_urls}

## Optional Task Source URLs

{optional_task_source_urls}

## Side Files / Provided Excerpts

{side_files}

## Authority Order

{authority_order}

## Missing Information Policy

{missing_information_policy}

## Source Policy

{source_policy}

## Base Policy

{base_policy}

## Resolved Sources

{resolved_sources}

## Branch Decision

{branch_decision}

## Expected Package Structure

```
manifest.json          - Metadata with payload_files list and sha256
checksums.sha256       - Per-file SHA256 verification digests
payload/               - All deliverable files relative to repo root
```

## Preflight Checklist

- [ ] `manifest.json` contains all required v2 fields with correct values.
- [ ] `checksums.sha256` covers every payload file with accurate SHA-256 digests.
- [ ] `payload/` directory contains exactly the files listed in `manifest.payload_files` — no extra, no missing.
- [ ] Logical paths (manifest, checksums) are repo-relative WITHOUT `payload/` prefix. Physical ZIP entries use `payload/{repo_relative_path}`.
- [ ] No file path violates `allowed_paths` (if set and non-empty) or matches `forbidden_paths`.
- [ ] No path uses absolute paths, `..` traversal, or escapes the repository root.
- [ ] Every SHA-256 in `manifest.payload_files` matches the actual file content.
- [ ] `Sources Read Report` is included in `context_readback.md` covering every provided source.
- [ ] `Context Readback` (Confirmed/Inferred/Not verified/Needs local verification) is in `context_readback.md`.

## Allowed Paths

{allowed_paths}

## Forbidden Paths

{forbidden_paths}

## Expected Outputs

{expected_outputs}

## Risks

- ZIP is untrusted: external chat may produce malicious paths or incorrect content.
- Checksums may be fabricated: verify every file before accepting.
- Manifest may be incomplete: extra payload files or missing manifest entries are structural violations.
- Allowed/forbidden path policies may be violated: strict prefix-based checks apply.
- A bad ZIP is worse than no ZIP.

## Human Actions

1. Review prompt.md, prompt_passport.md, and request_manifest.json.
2. Deliver the prompt to the external chat (outside Codex/OpenCode).
3. Receive the ZIP package back from the external chat as an attached/downloadable file.
4. Run `zchat_import_pack` to validate and extract the ZIP.
5. Run `zchat_verify_pack` to produce a machine verdict.
6. Make the final decision via `zchat_decision_pack`.

## Codex Actions After ZIP

1. Import the ZIP via `zchat_import_pack` — structural, scope, and checksum validation.
2. Verify the extracted pack via `zchat_verify_pack` — produce accepted_for_review / rejected_structural / rejected_scope / needs_codex_decision.
3. Report the verdict and await human decision.

## What Was Not Checked

- Semantic correctness of code (syntax, logic, tests).
- External dependencies or network resources.
- Runtime behaviour of delivered files.
- Compatibility with other parts of the repository beyond structural scope.

## Artifacts

{artifacts}
