# Zchat Unified Contract (v2)

## Purpose

This document defines the unified ZIP-first contract for the Zchat system v2. It supersedes scattered legacy rules and provides a single source of truth for intake, inspection, and decision guardrails.

## Manifest Versions

### v1.0 (Legacy, still supported)
```json
{
  "manifest_version": "1.0",
  "package_id": "<string>",
  "created_at": "<ISO8601>",
  "mode": "zchat_import_pack",
  "payload_files": [{"path": "...", "sha256": "<64-hex>"}],
  "allowed_paths": ["..."],
  "forbidden_paths": ["..."],
  "metadata": {}
}
```

### v2.0 (Current unified)
```json
{
  "manifest_version": "2.0",
  "package_id": "<string>",
  "created_at": "<ISO8601>",
  "mode": "zchat_import_pack",
  "zchat_result_type": "advice|review|package",
  "run_policy": "never_auto_run",
  "context_readback": "payload/context_readback.md",
  "payload_files": [{"path": "...", "sha256": "<64-hex>"}],
  "verification_files": ["<relative path>"],
  "allowed_paths": ["..."],
  "forbidden_paths": ["..."],
  "metadata": {
    "context_readback": "payload/context_readback.md"
  }
}
```

## v2 Required Fields

| Field | Type | Values | Description |
|---|---|---|---|
| `zchat_result_type` | string | `advice`, `review`, `package` | Type of external chat deliverable |
| `run_policy` | string | `never_auto_run` | Must never auto-run verification or apply |
| `context_readback` | string | path or empty | Path to context readback file; if empty, must be in `metadata.context_readback` |

## v2 Optional Fields

| Field | Type | Description |
|---|---|---|
| `verification_files` | list[str] | Files inside payload/ to inspect before application |

## Context Readback Contract

Every v2 ZIP MUST include a context readback (either `payload/context_readback.md` or as pointed by metadata). The context readback MUST contain at minimum these sections:

### Confirmed
Facts verified from provided sources. Cite specific source URL and line/region.

### Inferred
Reasonable deductions from confirmed facts. State the inference chain explicitly.

### Not verified
Claims believed true but unconfirmable from provided sources. Flag these clearly.

### Needs local verification
Statements requiring repo-local access (running tests, checking git state, reading non-provided files). NEVER fabricate these results.

## Trust Chain

This trust chain is NON-NEGOTIABLE for all v2 operations:

| Step | Principle |
|---|---|
| External answer | != accepted |
| ZIP created | != received (must pass structural validation) |
| Received to quarantine | != applied to repo (quarantine is sandbox) |
| Verification code exists | != safe to run (must pass inspection) |
| Verified | != accepted (machine verdict is checkpoint) |
| Accepted | != committed (human decision + git commit separate) |

## Pipeline

```
[Human] -> prompt_pack -> [External Chat] -> receive_pack (quarantine)
  -> inspect_verification_pack -> verify_pack -> decision_pack
  -> [apply_pack - planned, not implemented]
```

### receive_pack
- Accepts ZIP, validates structure/checksums/path-policy.
- Extracts ONLY to `runtime/quarantine/<slug>/payload/`.
- NEVER writes to repo.
- Writes `receive_report.md`.

### inspect_verification_pack
- Reads `verification_files` as text from quarantine.
- Does NOT execute them.
- Scans for dangerous patterns (20+ patterns covering deletion, network, shell, secrets, git, paths).
- Returns `safe_to_run` / `unsafe` / `needs_human_decision` / `not_present`.

### apply_pack (PLANNED, NOT IMPLEMENTED)
- After full pipeline (receive + inspect + verify + decision = accepted).
- Copy files from quarantine to repo.
- Current workaround: use `zchat_import_pack` for legacy direct-apply.

## Allowed / Forbidden Paths

### Global Forbidden (always enforced)
- `.git/` — protect git history
- `.env*` — protect secrets and environment configs
- `.ai/zchat/` — protect zchat runtime internals
- Absolute paths — `C:\...` or `/...`
- `..` traversal — prevent path escape
- Paths escaping repository root

### Manifest-level (optional)
- `allowed_paths`: if set and non-empty, each payload file must match at least one prefix.
- `forbidden_paths`: if set, no payload file may match any prefix.
- Global forbidden always overrides manifest allowed.

## Verification Inspection Patterns

The following categories are scanned during `zchat_inspect_verification_pack`:

| Category | Examples |
|---|---|
| `file_deletion` | rm -rf, os.remove, shutil.rmtree, Path.unlink |
| `writes_outside_scope` | Writing outside allowed scope |
| `env_secrets_access` | .env read/access, os.environ, dotenv |
| `git_commit` | git commit |
| `git_push` | git push |
| `git_mutation` | git add/checkout/branch/reset/clean/rebase |
| `network_install` | pip install, npm install, apt-get, choco |
| `network_download` | curl, wget, requests.get, urllib |
| `shell_subprocess` | subprocess.run/Popen/call, os.system |
| `code_execution` | eval, exec, compile |
| `git_access` | .git read/write/modify |
| `absolute_path` | /etc, /var, C:\Windows |
| `path_traversal` | open/read/write with ../ |

## Verdict Flow

```
receive_pack:
  structural check fails -> rejected_structural
  scope/policy violation -> rejected_scope
  checksum mismatch -> rejected_structural
  all pass -> accepted_for_review (files in quarantine)

inspect_verification_pack:
  critical patterns -> unsafe
  warning patterns -> needs_human_decision
  no patterns -> safe_to_run
  no files -> not_present

verify_pack:
  structural issues -> rejected_structural
  scope issues -> rejected_scope
  warnings -> needs_codex_decision
  all pass -> accepted_for_review

decision_pack:
  accepted/rejected/needs_revision
```

## Legacy Compatibility

- v1.0 manifests with `manifest_version: "1.0"` continue to work with `zchat_import_pack` (direct-apply).
- `zchat_import_pack` is the legacy direct-apply mode; bypasses quarantine.
- v2.0 manifests work with both `zchat_receive_pack` (quarantine) and `zchat_import_pack` (direct-apply, if pass context_readback check).
- All new guardrails (trust chain, verification inspection) apply to v2 manifests.
