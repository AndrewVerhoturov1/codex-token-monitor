---
name: opencode-zworker-control
description: Conditional skill for the explicit `/zworker` external worker route. Load only when the user explicitly invokes `/zworker` or asks to use the external worker route.
---

# OpenCode Zworker Route Control

## Purpose

Load this skill only when the user explicitly invokes `/zworker` or asks to
use the external worker route.

If the user explicitly invokes `/zworker-auto`, do not use this skill as the
main workflow skill. Use the dedicated `zworker-auto` skill instead.

Do not load this skill for ordinary local repo work.
Do not load this skill for ordinary OpenCode delegation.
Do not load this skill for ordinary GitHub tasks.

Этот скилл условный. Codex читает его только при явном `/zworker`.

`/zworker` is not a request for Codex to solve the main task directly.
`/zworker` is a request to prepare and run the external worker route.

Codex remains the coordinator:

- decide whether repo context is needed;
- use OpenCode reconnaissance when needed;
- prepare the prompt-pack;
- review the returned ZIP safely;
- decide what to tell the user or what revision is needed next.

For repo reconnaissance and ZIP processing, Codex should use the OpenCode route
according to `opencode-mcp-windows-control`.

## Route

```text
User -> Codex
Codex -> OpenCode reconnaissance if needed
Codex -> zworker prompt-pack
User -> external chat
External chat -> ZIP with answer.md
User -> Codex
Codex/OpenCode -> safe unzip to temp folder
Codex -> read answer.md first
Codex -> decide next step
```

## Prompt-pack rules

The external-worker prompt must stay short.

It should contain only:

- Request ID;
- link to the zworker manual;
- link to the zworker repo navigation;
- the core task;
- brief context from Codex/OpenCode;
- exact externally-openable HTTPS links (preferably raw.githubusercontent.com)
  when the external worker must read files;
- the requirement to return a ZIP with `answer.md`;
- a plain instruction to ask for a file, command output, or clarification if
  information is missing.

The prompt must not contain:

- `PACKAGE_READY`;
- `BLOCKED_MISSING_CONTEXT`;
- `CONTRACT_CONFLICT`;
- `manifest`;
- `checksums`;
- `payload`;
- `receive_pack`;
- `verify_pack`;
- old zchat bureaucracy.

If the task requires repository understanding, Codex/OpenCode should provide
exact externally-openable HTTPS links for the external worker.

If the task is standalone, files may be omitted from the prompt-pack.

Codex must give the user clickable Markdown links to each produced file (at
minimum prompt.md, prompt_passport.md, request_manifest.json when they exist)
with a brief plain description of what each file is for. Use absolute local
file paths formatted as clickable Markdown links, not bare paths. Codex must
not execute the external chat itself.

### External prompt link rules

All source file links in the external-worker prompt MUST be absolute HTTPS URLs
that any external agent can open without authentication or local file system
access. The following are FORBIDDEN in any external prompt:

- **Relative paths**: `src/file.py`, `./docs/README.md`, `../utils/helpers.py`
- **Windows absolute paths**: `C:/Users/...`, `D:\Codex\...`, `\\server\share`
- **File:// URIs**: `file:///C:/Users/...`, `file:///home/user/...`
- **Unix absolute paths**: `/home/user/project/file.py`
- **SMB/UNC paths**: `\\server\share\file`

Permitted link formats:

- `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>` (preferred)
- Any absolute HTTPS URL that returns the raw file content

When Codex provides source files, it MUST resolve them to public raw
GitHub URLs (or other HTTPS raw URLs) before writing the prompt.

## Prompt self-check (before issuing prompt.md)

Before handing `prompt.md` to the user, Codex MUST run a self-check:

1. Verify every source link in the prompt starts with `https://`.
2. Verify the prompt contains zero relative paths (`./`, `../`, or bare
   filenames without `https://` prefix in the "Files to read" section).
3. Verify the prompt contains zero Windows paths (no `A:\` to `Z:\` patterns).
4. Verify the prompt contains zero `file://` URIs.
5. Verify the manual URL and repo navigation URL are reachable (the
   implementation may skip URL reachability in test environments).
6. If any check fails, fix the prompt before issuing it.

Run the self-check programmatically via `_zworker_prompt_self_check()`.

## Valid vs invalid prompt examples

**Valid source links in a prompt:**

```markdown
## Files to read
- https://raw.githubusercontent.com/owner/repo/main/src/auth.py
- https://raw.githubusercontent.com/owner/repo/main/docs/api.md
```

**Invalid source links (must be rejected):**

```markdown
## Files to read
- src/auth.py                           (relative path)
- C:/Users/andre/project/src/auth.py    (Windows absolute path)
- /home/user/project/src/auth.py        (Unix absolute path)
- file:///C:/Users/andre/auth.py        (file:// URI)
- ./docs/api.md                         (relative with ./)
- ../utils/helpers.py                   (path traversal)
```

## ZIP intake and first read

When the external worker returns a ZIP:

1. Do not apply the ZIP directly to the repository.
2. Use OpenCode to unpack it into a temporary inbox folder.
3. Reject dangerous unpacking patterns:
   - absolute paths;
   - `..`;
   - path escape outside the temp folder;
   - automatic execution of unpacked files.
4. Find `answer.md`.
5. Read `answer.md` first.
6. Prepare a short review for Codex:
   - what is inside the ZIP;
   - what `answer.md` says;
   - whether extra files exist;
   - whether repo-target files exist;
   - whether obvious problems exist.

## Result interpretation

If the task was informational, an answer-only ZIP with just `answer.md` is a
normal result.

Informational tasks include:

- explanation;
- overview;
- analysis;
- conclusions;
- review without file changes.

If the task expected files to be created or changed, an answer-only ZIP is
insufficient and should be treated as a revision request.

If follow-up is needed, Codex should prepare a simple `ver2` prompt.

## User-facing output

Do not answer the user with machine bureaucracy such as:

- `accepted_for_review`;
- `process_manifest_ms`;
- `receive verdict`;
- `request match`.

Write a simple human summary instead:

- ZIP unpacked or not;
- `answer.md` found and read or not;
- short substance of the external answer;
- whether extra files exist;
- whether they are ready to accept, need revision, or need clarification.
- clickable Markdown links to unpacked relevant files (answer.md and any
  other available artifacts) with a short description of each, using absolute
  local file paths formatted as clickable Markdown links;

## References

- Invocation overview: [zworker_invocation.md](https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_invocation.md)
- External worker manual: [raw manual](https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md)
- Repo navigation: [raw navigation](https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md)
