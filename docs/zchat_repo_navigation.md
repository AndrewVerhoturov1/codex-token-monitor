# Zchat Repo Navigation (v1.0.0)

## Purpose

This is a curated navigation map for the **external chat agent**. It is NOT a full repository index.
It establishes what the agent may rely on and what it must not assume.

## Canonical Public Docs

All canonical public documentation for Zchat is in `docs/` at the repository root:

| Document | Path | Raw URL |
|---|---|---|
| External Agent Static Manual | `docs/zchat_external_agent_static_manual.md` | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_external_agent_static_manual.md` |
| Repo Navigation (this file) | `docs/zchat_repo_navigation.md` | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_repo_navigation.md` |

## What the Agent MAY Rely On

- **Canonical public docs** in `docs/` — these are the single source of truth for contracts. The static manual (`docs/zchat_external_agent_static_manual.md`) is the **highest authority** above all other sources.
- **Task-provided source URLs** — explicitly listed in the prompt under Source URLs.
- **Public GitHub raw URLs** — files committed to the `main` branch of this repository, accessed via `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/<path>`.
- **Additional repo files** — may be read starting from canonical docs and this navigation, following the Source Priority defined in the static manual.

**Public GitHub/raw truth rule**: public GitHub raw URLs are the sole source of truth only for committed public docs and contracts. Local runtime state (git status, test results, build artifacts, non-committed files) is **never** a source of truth. The agent MUST NOT rely on any information that is not committed and publicly accessible on the `main` branch.

## What the Agent MUST NOT Assume

- Local runtime state (test results, git status, build artifacts).
- Non-committed or unpublished files.
- Repository internals not documented in canonical docs or provided in the prompt.
- Any authority to modify, commit, push, or create branches.

## Path Rule

- **Physical ZIP**: files stored as `payload/<repo-relative-path>`.
- **Logical manifest/checksum**: paths are `<repo-relative-path>` WITHOUT `payload/` prefix.
- Never include `payload/` in manifest `payload_files[].path`, `context_readback`, `verification_files`, `metadata.context_readback`, or `checksums.sha256`.

## Workflow Overview

```
[Codex prompt_pack] -> [External Chat receives prompt] -> [External Chat produces ZIP]
  -> [Codex receive_pack (quarantine)] -> [inspect_verification_pack] -> [verify_pack] -> [decision_pack]
```

The external chat agent:
1. Receives a prompt package from Codex.
2. Reads canonical docs and provided sources in the required order.
3. Produces a ZIP response (or blocks with appropriate status).
4. Returns the ZIP to the human for intake via Codex.

## Key Files for Agent Understanding

| File | Purpose |
|---|---|
| `docs/zchat_external_agent_static_manual.md` | Your core operating manual (read first) |
| `docs/zchat_repo_navigation.md` | This file — repo structure map (read second) |
| `.ai/zchat/rules/zchat_unified_contract.md` | Full v2 contract (read if provided) |
| `.ai/zchat/templates/prompt.md` | Prompt template structure (reference) |

## Request Naming

All Zchat requests use the format: `ZCHAT-YYYYMMDD-HHMMSS-<slug>`
- UTC timestamp with seconds
- Lowercase slug derived from task description
- Example: `ZCHAT-20260627-143052-add-login-feature`

## Notes

- Additional public repo reading may be done starting from canonical docs and this navigation.
- The agent should treat the static manual as the highest authority, above all other sources.
- If canonical docs declare a version, report it in context readback.
