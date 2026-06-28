# Prompt Passport

- **Zchat ID**: ZCHAT-20260626-V2-E2E-QUARANTINE
- **Goal**: Create a valid Zchat manifest v2 ZIP intake package for quarantine-first E2E test
- **Prompt file**: `.ai/zchat/requests/zchat-v2-e2e-quarantine-20260626/prompt.md`

## Source Policy

`public_github_raw_first` — prefer public GitHub raw URLs for context files.

## Base Policy

No base branch operations required. This is an external chat E2E test pack with quarantine-first delivery; no direct repo writes.

## Resolved Sources

1. `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md`

## Branch Decision

No branch needed. Source URLs are sufficient; this is a quarantine-first ZIP intake test with no code changes or git operations.

## Expected Package Structure

```
manifest.json          - Metadata v2 (manifest_version "2.0", zchat_result_type "package")
checksums.sha256       - Per-file SHA256 verification digests
payload/               - All deliverable files relative to repo root
  docs/
    zchat_v2_e2e/
      result.md
      context_readback.md
      change_summary.md
      verification/
        check_result.py
```

## Allowed Paths

- `docs/zchat_v2_e2e/`

## Forbidden Paths

- `scripts/`
- `.ai/zchat/`
- `.env`
- `config/`

## Expected Outputs

- `manifest.json` — v2 manifest with `manifest_version: "2.0"`, `zchat_result_type: "package"`, `run_policy: "never_auto_run"`, `verification_files` list
- `checksums.sha256` — one SHA256 line per payload file
- `payload/docs/zchat_v2_e2e/result.md` — E2E test result with status PASS/FAIL
- `payload/docs/zchat_v2_e2e/context_readback.md` — Confirmed/Inferred/Not verified/Needs local verification
- `payload/docs/zchat_v2_e2e/change_summary.md` — list of files, purposes, risks
- `payload/docs/zchat_v2_e2e/verification/check_result.py` — Python script that validates manifest v2 structure

## Risks

- ZIP is untrusted: external chat may produce malicious paths or incorrect content.
- Checksums may be fabricated: verify every file before accepting.
- Manifest may be incomplete: extra payload files or missing manifest entries are structural violations.
- Allowed/forbidden path policies may be violated: strict prefix-based checks apply.
- Verification script may contain dangerous operations: must be inspected before any execution.

## Human Actions

1. Review `prompt.md`, `prompt_passport.md`, and `request_manifest.json`.
2. Deliver the prompt to the external chat (outside Codex/OpenCode).
3. Receive the ZIP package back from the external chat.
4. Run `zchat_receive_pack` to receive the ZIP to quarantine (v2 quarantine-first).
5. Run `zchat_inspect_verification_pack` to scan verification files.
6. Run `zchat_verify_pack` to produce a machine verdict.
7. Make the final decision via `zchat_decision_pack`.

## Codex Actions After ZIP

1. Receive the ZIP via `zchat_receive_pack` — quarantine-first, never writes directly to repo.
2. Inspect verification files via `zchat_inspect_verification_pack` — scan for dangerous patterns.
3. Verify the extracted pack via `zchat_verify_pack` — produce accepted_for_review / rejected_structural / rejected_scope / needs_codex_decision.
4. Report the verdict and await human decision.

## What Was Not Checked

- Semantic correctness of delivered file content.
- External dependencies or network resources.
- Runtime behaviour of delivered files.
- Compatibility with other parts of the repository beyond structural scope.
- Whether the verification script is safe to execute.

## Artifacts

- `prompt.md`
- `prompt_passport.md`
- `request_manifest.json`
