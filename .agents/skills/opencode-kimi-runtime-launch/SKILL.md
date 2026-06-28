---
name: opencode-kimi-runtime-launch
description: Use only when the user explicitly requests Kimi or `/kimifree` for a bounded medium-code task that must use temporary `OPENCODE_CONFIG_CONTENT` without changing `C:\Users\andre\.config\opencode\opencode.jsonc`.
---

# OpenCode Kimi Runtime Launch (Manual-Only)

## Purpose

Use this skill only when:

- the user explicitly requests Kimi, OR
- the user explicitly requests `/kimifree`.

This skill is conditional.

Kimi is not the default OpenCode route.
Kimi is not automatic fallback after DeepSeek failure.
Kimi is a manual-only bounded medium-code route.

Use temporary `OPENCODE_CONFIG_CONTENT`.
Do not change permanent [opencode.jsonc](</C:/Users/andre/.config/opencode/opencode.jsonc>).

## When the manual Kimi route is deliberately selected

This skill is used only when Codex deliberately enters the manual Kimi route
for a specific implementation phase after an explicit `/kimifree` or Kimi
request.

The manual Kimi route does not have to own the whole user task.

Normal route chain:

- Route A gathers context;
- the manual Kimi route implements the medium bounded code change;
- Route A verifies changed files, diff, and simple checks.

Kimi should receive only the bounded implementation context needed for its
phase, not a broad repo exploration task.

Use the bundled PowerShell script:

- [scripts/run-opencode-kimi-runtime.ps1](</C:/Users/andre/.agents/skills/opencode-kimi-runtime-launch/scripts/run-opencode-kimi-runtime.ps1>)

## Workflow

1. Confirm the task is a bounded Kimi task.
2. Default to `kimi-k2.5-thinking`.
3. Run the script with `-CheckOnly` first when a cheap preflight is needed.
4. Verify:
   - `http://127.0.0.1:9766/health` responds;
   - `http://127.0.0.1:9766/v1/models` responds;
   - the requested model ID is present.
5. Only if all checks pass, run OpenCode through one-shot
   `OPENCODE_CONFIG_CONTENT`.
6. Keep the task bounded to the requested folder or repository scope.
7. Report:
   - runtime config was used: yes/no;
   - permanent opencode.jsonc changed: no.
   - If bootstrap was attempted, additionally report:
     - bootstrap attempted: yes/no;
     - FreeGLMKimiAPI path: `C:\AI\FreeGLMKimiAPI`;
     - health after bootstrap: pass/fail;
     - models after bootstrap: pass/fail;
     - selected model present: yes/no.

## FreeGLMKimiAPI bootstrap

If the manual Kimi route is already deliberately selected and the health check
fails because local FreeGLMKimiAPI appears to be not running, Codex may
perform one bounded diagnostic bootstrap attempt.

This bootstrap is not a provider fallback and is not general repair work.
It only satisfies the selected Kimi route prerequisite.

Allowed bootstrap scope:

- local service: `C:\AI\FreeGLMKimiAPI`;
- local endpoint only: `http://127.0.0.1:9766`;
- one diagnostic start attempt;
- one `/health` check after start;
- one `/v1/models` check after start;
- continue only if the requested model ID is present.

Codex/OpenCode MUST NOT during bootstrap:

- change permanent `C:\Users\andre\.config\opencode\opencode.jsonc`;
- install dependencies;
- update packages;
- edit FreeGLMKimiAPI source files;
- edit `.env`;
- read or print secrets;
- switch to another provider or model;
- keep retrying start loops.

If bootstrap succeeds, continue the selected Kimi runtime task through
temporary `OPENCODE_CONFIG_CONTENT`.

If bootstrap fails, stop and ask the user what route to use next.

## Kimi task limits

Kimi MUST receive only bounded code implementation tasks.

Kimi tasks may be small or medium, but they MUST be one bounded implementation
slice, not broad exploration or multi-stage repo-wide work.

Allowed Kimi task shape:

- small or medium bounded implementation slice;
- enough context from Route A exploration, but no broad repo exploration;
- one goal;
- one feature slice or one understood bug;
- bounded allowed files/paths;
- exact goal;
- relevant files or target folder from Route A context;
- allowed edit scope;
- clear `MUST DO`;
- clear `MUST NOT`;
- clear `STOP BEFORE`;
- verification request;
- one selected validation command if needed;
- compact final report.

Kimi MUST NOT receive:

- broad repo exploration;
- vague tasks;
- "study and fix everything";
- multi-stage large implementation without splitting;
- whole-app rewrites;
- unbounded "create everything and polish everything" tasks;
- repo-wide refactors;
- dependency changes;
- install/network/server/watch commands;
- secrets or `.env`;
- Git/GitHub write actions;
- permanent OpenCode config edits;
- tasks that require multiple large stages in one run.

If the task is too large, Codex MUST split it before using Kimi.

## Stop rules

Stop immediately and report the blocker if:

- `opencode.cmd` is not available;
- FreeGLMKimiAPI health check fails — first apply the bounded bootstrap rule
  in `## FreeGLMKimiAPI bootstrap` when the local service appears to be simply
  not running. Stop immediately if:
  - bootstrap is not allowed by scope;
  - bootstrap was already attempted and failed;
  - health still fails after bootstrap;
  - `/v1/models` still fails after bootstrap;
  - the requested model ID is absent;
  - the failure suggests broken config, missing dependencies, secrets, or
    source repair would be required.
- the user asked for any model other than `kimi-k2.5-thinking` and the local
  model list does not expose it exactly;
- the task would require secrets, permanent config edits, or broad repo writes
  beyond the stated scope.

Do not silently fall back to another provider or another model.

## Kimi failure behavior

A successful bounded FreeGLMKimiAPI bootstrap is not a failure and is not a
fallback. It remains part of the selected Kimi runtime route.

If Kimi preflight, health, model check, runtime launch, or result quality
fails, Codex MUST stop and ask the user what to do next.

Codex MUST NOT silently switch to:

- DeepSeek;
- job-wrapper fallback;
- local Codex repo work;
- another model;
- permanent OpenCode config edits.

After a failed bootstrap, Codex MUST stop and ask the user. Codex MUST NOT
silently switch to DeepSeek, job-wrapper fallback, local Codex work, another
model, or permanent config edits.

The user must choose the next route:

1. retry Kimi after fixing the blocker;
2. use normal DeepSeek OpenCode MCP;
3. allow Codex local work;
4. stop.

## Model rule

Default model: `kimi-k2.5-thinking`.

Use another model only when the user explicitly asks for it. Always verify the
exact model ID against `/v1/models` first. If the requested ID is absent, say
so plainly and stop.

## Command pattern

Preferred preflight:

```powershell
powershell -ExecutionPolicy Bypass -File `
  C:\Users\andre\.agents\skills\opencode-kimi-runtime-launch\scripts\run-opencode-kimi-runtime.ps1 `
  -RepoPath 'D:\path\to\repo' `
  -ModelId 'kimi-k2.5-thinking' `
  -TaskText 'TASK_STATUS must be near the top. ...' `
  -CheckOnly
```

Preferred real run:

```powershell
powershell -ExecutionPolicy Bypass -File `
  C:\Users\andre\.agents\skills\opencode-kimi-runtime-launch\scripts\run-opencode-kimi-runtime.ps1 `
  -RepoPath 'D:\path\to\repo' `
  -ModelId 'kimi-k2.5-thinking' `
  -Title 'kimi-runtime-task' `
  -TaskText 'TASK_STATUS must be near the top. ...'
```

## Task shaping

Keep prompts low-risk and bounded:

- tell OpenCode exactly where writes are allowed;
- forbid permanent config edits;
- forbid `npm install`, `git add`, `git commit`, `git push`, `git reset`,
  `git clean`;
- forbid reading secrets, `.env`, tokens, cookies;
- ask for short final output only.

For UI or repo smoke work, prefer:

- one target folder;
- one final artifact set;
- one verification command if needed;
- one compact final report.

## Kimi execution profile

Kimi uses a single manual-only execution profile: **/kimifree**.

| Profile | Tools | Description |
|---------|-------|-------------|
| /kimifree | read, write, edit, glob, grep, bash, webfetch | File tools plus webfetch for the public external reference URL. Kimi must call webfetch to read the reference URL before implementation. GitHub tools are never sent. |

### /kimifree rules

- Tools: read, write, edit, glob, grep, bash, webfetch.
- Kimi must call webfetch with the external reference URL before implementation.
- Full tool catalog: never sent.
- GitHub MCP tools: never sent.
- Runtime config only; permanent opencode.jsonc is never changed.

### Profile files

- [profiles/kimi-agent-core.md](profiles/kimi-agent-core.md) — agent rules, stop rules
- [profiles/kimi-agent-files.md](profiles/kimi-agent-files.md) — file tools (read/write/edit/glob/grep/bash)
- [profiles/kimi-agent-output.md](profiles/kimi-agent-output.md) — output formats (TASK_STATUS, FILE, verification summary, route report)
- [profiles/kimi-agent-external-reference.md](profiles/kimi-agent-external-reference.md) — external reference URL and webfetch rules

Kimi reminder:

```text
Kimi is deliberate, bounded, manual-only, and temporary-config only.
Kimi is not default.
Kimi is not silent fallback.
Kimi failure means stop and ask.
Kimi may be used for only the implementation phase inside a larger route chain.
Route A may gather context before Kimi.
Route A may verify after Kimi.
Kimi must not receive broad exploration tasks.
```

Kimi regression smoke:

- `/kimifree` or explicit Kimi request is required;
- small and medium bounded implementation slices are allowed for Kimi;
- "medium" does not block the manual Kimi route;
- Kimi is not part of ordinary Route C selection;
- Kimi rejects broad exploration and large multi-stage implementation, not medium bounded slices.
