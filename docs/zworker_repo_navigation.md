# Zworker Repo Navigation (v2.0.0)

## Purpose

A brief navigation map for the zworker external agent. Not a full repository index.

## Canonical Zworker Docs

| Document | Raw URL |
|---|---|
| External Agent Manual | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md` |
| Repo Navigation (this file) | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md` |
| Codex Invocation Overview | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_invocation.md` |

## Where Zworker Files Live

- `.ai/zworker/` — zworker system config: templates, readme
- `.ai/zworker/templates/` — prompt, passport, manifest templates
- `.ai/zworker/runtime/` — runtime artifacts (requests, inbox, revisions)

## Zchat Legacy

- `.ai/zchat/` — the older zchat system (separate, not used by zworker)
- `docs/zchat_*` — zchat documentation (legacy reference)

## How to Read Public Raw URLs

Files committed to the default branch can be read via:
`https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/<path>`

If a temporary context branch is listed in the prompt, files are readable via:
`https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/<branch_name>/<path>`

## Temporary Context Branch

When public source URLs are insufficient, the prompt may include a temporary context branch section. The branch is read-only for the agent. If no branch is mentioned in the prompt, there is no temporary context to use.

## Request Naming

All Zworker requests use the format: `ZWORKER-YYYYMMDD-HHMMSS-{slug}`
- UTC timestamp with seconds
- Lowercase slug derived from task description
- Example: `ZWORKER-20260627-143052-add-login-feature`

Revisions append `-ver2`, `-ver3`, etc.: `ZWORKER-20260627-143052-add-login-feature-ver2`

## Notes

- The external agent manual is the core reference for how to work.
- The Codex-side `/zworker` invocation flow is documented in `docs/zworker_invocation.md`.
- If something in the task description is unclear, ask for clarification.
