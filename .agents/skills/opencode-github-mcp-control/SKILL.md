---
name: opencode-github-mcp-control
description: Conditional skill for explicit GitHub tasks through OpenCode/GitHub MCP. Load only when GitHub work is explicitly requested.
---

# OpenCode GitHub MCP Control

## Purpose

Use only for explicit GitHub tasks.

This skill is conditional. Codex MUST NOT read it for ordinary local repo work.

This skill does not authorize Codex to use GitHub directly.

It authorizes only this route:

Codex -> mcp__opencode.* -> OpenCode -> GitHub MCP

Direct Codex-side GitHub MCP/tools/connectors are forbidden.

## Preconditions

Codex MUST already have read `opencode-mcp-windows-control`.

GitHub is explicit-only.

Do not use GitHub MCP, `gh`, PRs, issues, pushes, merges, or remote writes
unless the user explicitly requested a GitHub task.

## Route

Use:

```text
Codex -> mcp__opencode.* -> OpenCode -> GitHub MCP
```

Do not use local `gh` by default.

## Direct GitHub tool ban

Codex MUST NOT call GitHub tools directly.

Forbidden examples:

- `mcp__codex_apps__github.*`;
- direct GitHub connector tools;
- local `gh`;
- direct GitHub API calls;
- any non-OpenCode GitHub read/write path.

This applies to:

- authenticated user checks;
- repository root listing;
- file reads;
- README reads;
- issue reads;
- pull request reads;
- branch reads;
- all GitHub write actions.

All GitHub operations must be requested from OpenCode through one bounded
`opencode_ask` or `opencode_run` task, unless the GitHub skill explicitly
defines a narrow OpenCode-mediated preflight/status check.

If Codex has already used direct GitHub tools in the current task, it MUST mark
the result as a route violation and repeat the GitHub step through OpenCode if
the user wants a valid skill test.

## Mandatory preflight

For explicit GitHub tasks, preflight should be minimal and bounded.

Preflight must not become a mixed route.

If Codex checks OpenCode/GitHub MCP status through OpenCode, the later GitHub
read/write work must still be done through OpenCode.

Codex MUST NOT do:

OpenCode preflight -> direct Codex GitHub reads

That is a route violation.

Allowed preflight:

1. `opencode_setup` when needed to confirm the OpenCode route is ready.
2. `opencode_mcp_status` or equivalent status check to confirm `github:
   connected`.
3. One tiny real read-only GitHub probe.
4. OpenCode server version check when version/stale-route risk is relevant.

Model discovery is NOT required for GitHub read-only tasks when the main skill
default model is used.

Codex MUST NOT call `opencode_provider_models` for GitHub tasks merely because
the OpenCode tool description recommends provider discovery.

Call `opencode_provider_models` only if:

- the default provider/model is missing or rejected;
- the user explicitly asks for a different provider/model;
- the task is specifically about provider/model diagnosis.

## GitHub safety

- protect `main`;
- no push unless explicitly allowed;
- no PR unless explicitly allowed;
- no merge unless explicitly allowed;
- no issue/PR writes unless explicitly allowed;
- no secrets in files, issues, comments, logs, or reports;
- no tokens printed;
- no broad repo writes.

## Read-only tasks

Read-only GitHub tasks may include:

- authenticated user check;
- repository root listing;
- file read;
- issues list;
- pull requests list;
- workflows list;
- PR file/diff read.

## Write tasks

Write tasks require explicit user permission and bounded scope.

Allowed only when explicitly requested:

- create issue;
- comment issue;
- close issue;
- create branch;
- create file in branch;
- create PR;
- comment PR;
- close PR without merge.

No merge by default.

## Budget notes

For a simple GitHub read-only task, target preflight is:

- setup/status if needed;
- GitHub connected check;
- one read-only GitHub probe;
- one bounded OpenCode GitHub task.

Avoid extra discovery calls. `opencode_provider_models` is a budget warning
unless specifically justified by a model/provider blocker.

## Output

Return compact evidence:

```text
TASK_STATUS: COMPLETED / PARTIAL / BLOCKED / FAILED / NEEDS_CODEX_DECISION
```

Route:
- ...

GitHub route used:
- OpenCode-mediated yes/no

direct Codex-side GitHub tools used:
- yes/no

local `gh` used:
- yes/no

GitHub writes performed:
- yes/no

route violation:
- yes/no

Preflight:
- ...

Actions:
- ...

GitHub objects:
- ...

Safety:
- ...

For GitHub tasks, OpenCode/Codex final report MUST include:

- GitHub route used: OpenCode-mediated yes/no;
- direct Codex-side GitHub tools used: yes/no;
- local `gh` used: yes/no;
- GitHub writes performed: yes/no;
- route violation: yes/no.

## Regression smoke

- GitHub read-only must use OpenCode-mediated route;
- direct Codex-side GitHub tools are forbidden even for read-only;
- OpenCode preflight followed by direct Codex GitHub reads is a route violation;
- valid GitHub route proof must say: direct Codex-side GitHub tools used: no.
