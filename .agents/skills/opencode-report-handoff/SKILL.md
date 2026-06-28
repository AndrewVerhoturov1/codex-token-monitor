---
name: opencode-report-handoff
description: Conditional skill for long workspace-local OpenCode report handoff. Load only when a long report artifact is needed.
---

# OpenCode Report Handoff

## Purpose

Use only when OpenCode must produce a long user-facing report or large audit.

Do not load for normal short answers.

## Default report location

Use workspace-local:

```text
<workspace>\_opencode_reports\
```

Do not use by default:

- `external_directory`;
- `C:\Users\andre\.agents\reports\opencode\`;
- `C:\Users\andre\.codex\attachments\`.

## Workflow

1. OpenCode writes the report to `_opencode_reports`.
2. OpenCode returns:
   - report path;
   - marker;
   - 5-10 bullet summary;
   - evidence basis;
   - uncertainty;
   - safety status;
   - whether repo files changed;
   - whether Git/GitHub actions were performed.
3. Codex performs one MCP readback.
4. Codex verifies:
   - marker exists;
   - required sections exist;
   - safety status is clear;
   - no obvious contradiction.
5. Codex gives the user a short answer and the report path.

## Failure rule

If readback fails once:

- do not ask OpenCode to paste the full report into chat;
- do not use `opencode_conversation` to pull the whole report;
- return the available stub/path;
- mark verification unavailable;
- report `PARTIAL`/`BLOCKED` only if verified content was required.

## Revision

If the report is incomplete or unsafe, ask OpenCode for one bounded revision.

For revision, OpenCode must return:

- what changed;
- changed sections;
- updated path.

## Final answer

Codex final answer must be short:

- path;
- short summary;
- whether reviewed;
- caveats;
- next action.
