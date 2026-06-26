# Prompt Passport

- **Zchat ID**: ZCHAT-20260626-HELLO-TEST
- **Goal**: Create a valid strict Zchat ZIP package containing exactly one file `docs/zchat_test/hello_from_zchat.md`
- **Prompt file**: `.ai/zchat/requests/zchat-hello-test-pack-20260626/prompt.md`

## Source Policy

`public_github_raw_first` — prefer public GitHub raw URLs for context files.

## Base Policy

No base branch operations required. This is an external chat test pack with no code changes.

## Resolved Sources

1. `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md`
2. `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/.ai/zchat/readme.md`

## Branch Decision

No branch needed. Source URLs are sufficient; no code changes or git operations are required.

## Expected Package Structure

```
manifest.json          - Metadata with payload_files list and sha256
checksums.sha256       - Per-file SHA256 verification digests
payload/               - All deliverable files relative to repo root
```

## Allowed Paths

- `docs/zchat_test/`

## Forbidden Paths

- `scripts/`
- `.ai/zchat/`
- `.env`
- `config/`

## Expected Outputs

- `docs/zchat_test/hello_from_zchat.md`

## Risks

- ZIP is untrusted: external chat may produce malicious paths or incorrect content.
- Checksums may be fabricated: verify every file before accepting.
- Manifest may be incomplete: extra payload files or missing manifest entries are structural violations.
- Allowed/forbidden path policies may be violated: strict prefix-based checks apply.

## Human Actions

1. Review `prompt.md`, `prompt_passport.md`, and `request_manifest.json`.
2. Deliver the prompt to the external chat (outside Codex/OpenCode).
3. Receive the ZIP package back from the external chat.
4. Run `zchat_import_pack` to validate and extract the ZIP.
5. Run `zchat_verify_pack` to produce a machine verdict.
6. Make the final decision via `zchat_decision_pack`.

## Codex Actions After ZIP

1. Import the ZIP via `zchat_import_pack` — structural, scope, and checksum validation.
2. Verify the extracted pack via `zchat_verify_pack` — produce accepted_for_review / rejected_structural / rejected_scope / needs_codex_decision.
3. Report the verdict and await human decision.

## What Was Not Checked

- Semantic correctness of delivered file content.
- External dependencies or network resources.
- Runtime behaviour of delivered files.
- Compatibility with other parts of the repository beyond structural scope.

## Artifacts

- `prompt.md`
- `prompt_passport.md`
- `request_manifest.json`
