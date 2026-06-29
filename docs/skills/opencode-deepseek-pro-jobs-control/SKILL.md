---
name: opencode-deepseek-pro-jobs-control
description: Use only when `opencode-mcp-windows-control` deliberately selects Route C for a bounded hard local verification, repair, or implementation phase that must run through OpenCode Jobs with `ollama_5_round_robin/minimax-m2.5`. (Skill name is legacy; actual runtime model is minimax-m2.5 via the round-robin profile.)
---

# OpenCode DeepSeek Pro Jobs Control (legacy name — actual runtime: minimax-m2.5 via ollama_5_round_robin)

## Purpose

Load this skill only when the main routing skill has already selected Route C.

Route C is:

```text
Codex -> mcp__opencode_jobs.opencode_job_run_and_wait -> job-wrapper -> OpenCode -> ollama_5_round_robin/minimax-m2.5
```

This skill is only for bounded hard local jobs.
It is not the default strongest thinking route, and it does not compete with
Route W for design, architecture, review, documentation, research, or initial
medium/complex code package generation when GitHub context is sufficient.
It is not for broad exploration, Route A reconnaissance, or silent recovery.

## Hard rules

- use only `mcp__opencode_jobs.opencode_job_run_and_wait`;
- use provider `ollama_5_round_robin`;
- use model `minimax-m2.5`;
- keep the task bounded to the approved implementation slice;
- gather repo context through Route A first when needed;
- do not change permanent [opencode.jsonc](</C:/Users/andre/.config/opencode/opencode.jsonc>);
- do not use the old Windows bridge;
- do not run install/network/server/watch commands;
- do not use Git/GitHub write actions;
- do not silently fall back to Kimi, Flash, local Codex work, or another route.

If the provider, model, jobs wrapper, or Route C result is unavailable, empty,
off-scope, or otherwise unusable, Codex MUST stop and explain the blocker to
the user.

## Task shaping

Every Route C jobs request should stay compact and use this structure:

```text
MODE: patch_pack
GOAL: one concrete implementation result
SCOPE: only the approved files, paths, or subsystem
MUST DO: only the minimum edits and one bounded verification pass
MUST NOT: no permanent config edits, no install/network/server/watch, no Git writes, no broad exploration
STOP BEFORE: any scope expansion, dependency drift, or unrelated refactor
OUTPUT: TASK_STATUS first, changed files, compact diff summary, checks, risks
BUDGET: one bounded jobs run
```

## Route C use cases

Use Route C for:

- complex local verification;
- hard failing tests;
- post-Web local repair;
- medium local fixes when Web cannot see required local context;
- long bounded local job work where Route A is too weak.

Prefer Route W for:

- initial design;
- architecture;
- review;
- documentation;
- research;
- medium/complex code package generation when GitHub context is sufficient.

## Route C reminder

```text
Route A gathers context when needed.
Route W is the preferred strongest-model phase when published GitHub context is sufficient.
Route C handles bounded hard local verification/repair through OpenCode Jobs.
Route A may verify the result afterward.
If minimax-m2.5 via ollama_5_round_robin or the jobs wrapper fails, stop and report.
```
