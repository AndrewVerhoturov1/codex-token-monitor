---
name: opencode-deepseek-pro-jobs-control
description: Use only when `opencode-mcp-windows-control` deliberately selects Route C for a bounded medium/complex implementation phase that must run through OpenCode Jobs with `deepseek/deepseek-v4-pro`.
---

# OpenCode DeepSeek Pro Jobs Control

## Purpose

Load this skill only when the main routing skill has already selected Route C.

Route C is:

```text
Codex -> mcp__opencode_jobs.opencode_job_run_and_wait -> job-wrapper -> OpenCode -> deepseek/deepseek-v4-pro
```

This skill is only for bounded medium/complex code implementation phases.
It is not for broad exploration, Route A reconnaissance, or silent recovery.

## Hard rules

- use only `mcp__opencode_jobs.opencode_job_run_and_wait`;
- use provider `deepseek`;
- use model `deepseek-v4-pro`;
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

## Route C reminder

```text
Route A gathers context when needed.
Route C implements the bounded medium/complex code change through OpenCode Jobs.
Route A may verify the result afterward.
If DeepSeek Pro or the jobs wrapper fails, stop and report.
```
