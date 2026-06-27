# Zworker Repo Navigation (v1.1.0 — Stage 2)

## Purpose

This is a curated navigation map for the **zworker external agent**. It is NOT a full repository index.
It establishes what the agent may rely on and what it must not assume.

## Canonical Public Docs

All canonical public documentation for Zworker is in `docs/` at the repository root:

| Document | Path | Raw URL |
|---|---|---|
| External Agent Static Manual | `docs/zworker_external_agent_manual.md` | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md` |
| Repo Navigation (this file) | `docs/zworker_repo_navigation.md` | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md` |

## What the Agent MAY Rely On

- **Canonical public docs** in `docs/` — these are the single source of truth for contracts. The static manual (`docs/zworker_external_agent_manual.md`) is the **highest authority** above all other sources.
- **Task-provided source URLs** — explicitly listed in the prompt under Source URLs.
- **Public GitHub raw URLs** — files committed to the default branch of this repository, accessed via `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/<path>`.
- **Additional repo files** — may be read starting from canonical docs and this navigation, following the Source Priority defined in the static manual.

## What the Agent MUST NOT Assume

- Local runtime state (test results, git status, build artifacts).
- Non-committed or unpublished files (unless a temporary context branch is listed — see below).
- Repository internals not documented in canonical docs or provided in the prompt.
- Any authority to modify, commit, push, or create branches.

## Temporary Context Branch (Read-Only)

When public source URLs are insufficient for requested files, the prompt may include a temporary context branch under the "Temporary Context Branch" section. This branch, if created by external orchestration, hosts unpublished files for the agent to read.

- The branch is **read-only** for the agent.
- Files are accessible via `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/<branch_name>/<path>`.
- The branch name follows the pattern `zworker/context/ZWORKER-YYYYMMDD-HHMMSS-slug`.
- Mark temp branch sources in the Sources Read Report under "External search used" with note "Temporary context branch".

## ZIP Contract (Lightweight)

zworker uses a lightweight ZIP contract: no manifest, no checksums, no payload/ directory.

```
answer.md               - REQUIRED at root
<repo_relative_path>    - Files at root using repo-relative paths
```

Unlike zchat, zworker does NOT require `manifest.json`, `checksums.sha256`, or `payload/` directory. Files go directly at ZIP root.

## Workflow Overview (Stage 2)

```
[Codex prompt_pack] -> [External Agent receives prompt] -> [External Agent produces ZIP with answer.md]
  -> [zworker_result_unpack] -> [zworker_process_result] -> [auto-apply or revision]
```

The external agent:
1. Receives a prompt package from Codex.
2. Reads canonical docs and provided sources in the required order.
3. Produces a ZIP response (or blocks with appropriate status).
4. Returns the ZIP to the human.

The local zworker pipeline (Stage 2):
1. **Unpack**: Safely extracts ZIP into `.ai/zworker/runtime/inbox/<request-id>/` only — never writes to repo.
2. **Process**: Reads `answer.md` first, validates Sources Read Report structure, checks scope against manifest.
3. **Auto-apply**: If clear and safe, applies repo-candidate files directly to working tree.
4. **Revision**: If answer.md is missing or report is incomplete, generates a revision prompt with `-ver2`/`-ver3` naming.

## Key Files for Agent Understanding

| File | Purpose |
|---|---|
| `docs/zworker_external_agent_manual.md` | Your core operating manual (read first) |
| `docs/zworker_repo_navigation.md` | This file — repo structure map (read second) |

## Request Naming

All Zworker requests use the format: `ZWORKER-YYYYMMDD-HHMMSS-{slug}`
- UTC timestamp with seconds
- Lowercase slug derived from task description
- Example: `ZWORKER-20260627-143052-add-login-feature`

Revisions append `-ver2`, `-ver3`, etc.: `ZWORKER-20260627-143052-add-login-feature-ver2`

## Notes

- Additional public repo reading may be done starting from canonical docs and this navigation.
- The agent should treat the static manual as the highest authority, above all other sources.
- If canonical docs declare a version, report it in the Sources Read Report.
