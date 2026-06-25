# Kimi C4 External Tool Reference

This public reference is a compact, stable description of the extended OpenCode/Kimi tool environment.

C4 prompts may link here instead of embedding long repeated tool and profile documentation. This file is reference text only. A model reading this file does not receive tool permissions from it. Actual tools are controlled only by the runtime profile and temporary OpenCode configuration used for that run.

## C4 intent

C4 is for tasks where Kimi should receive a short prompt plus a public reference link for the extended tool catalog and shared operating rules.

C4 must not be treated as C3 automatically.

- C1: no tools, PATCH_BUNDLE only.
- C2: file tools only: read, write, edit, glob, grep, bash.
- C3: full tool catalog, only with an explicit reason.
- C4: compact prompt with a public reference link. Runtime tools are still selected by the runner and must be reported explicitly.

## Tool identity catalog

Common OpenCode tool IDs referenced by the full profile:

- bash
- read
- glob
- grep
- edit
- write
- task
- webfetch
- todowrite
- websearch
- skill
- apply_patch

This list is descriptive. It is not a permission grant.

## File tool signatures

These are the file tools used by file-capable profiles such as C2.

```text
read(filePath) -> content or error
write(filePath, content) -> ok or error
edit(filePath, oldString, newString) -> ok or error
glob(pattern) -> matching paths
grep(pattern, include?) -> matching lines
bash(command, description?, timeout?) -> stdout/stderr/exit code
```

File tools are for bounded local workspace tasks. They must not be used to read secrets, print tokens, install dependencies, start watch/server loops, or perform Git writes unless the active task explicitly allows that.

## GitHub tool families

The full profile may expose GitHub tool families for repository and project operations:

- file contents read
- create or update file
- push multiple files
- code search
- pull request create/read/list
- issue read/write/comment
- commit read/list
- branch list/create
- actions list/get/trigger

GitHub tools are not for ordinary local filesystem work. They require an explicit GitHub task and a bounded scope. This reference does not authorize GitHub writes.

## Output formats

Prefer compact, machine-checkable reports.

```text
TASK_STATUS: COMPLETED / PARTIAL / BLOCKED / FAILED / NEEDS_CODEX_DECISION
```

For patch-only work, use a PATCH_BUNDLE with clear file boundaries. For normal file work, report changed files and verification.

Recommended final report fields:

- task status
- files changed
- verification performed
- tools actually available
- full tool catalog sent: yes/no
- GitHub tools sent: yes/no
- permanent config changed: yes/no
- Git write actions used: yes/no

## Core operating rules

- Do not invent tool outputs.
- Do not claim a file, command, GitHub object, or test result exists unless a tool actually confirmed it.
- If a needed tool is unavailable, report the missing tool and stop or request a route change.
- Keep task scope bounded to the paths and actions in the prompt.
- Do not read or print `.env`, tokens, cookies, credentials, or secrets.
- Do not change permanent OpenCode config unless the task explicitly requests it.
- Do not run installs, updates, servers, watchers, or network-heavy commands unless explicitly allowed.
- Do not perform Git writes unless explicitly allowed.
- Do not use GitHub writes unless the task is explicitly a GitHub task.

## Guard rules by domain

File tasks:

- use file tools only within the allowed scope;
- keep edits minimal;
- verify with no-install checks when possible;
- stop before dependency installs or persistent servers.

GitHub tasks:

- use GitHub tools only when explicitly requested;
- prefer read-only probes before writes;
- protect default branches unless the user explicitly requested a direct publish/update;
- report whether GitHub writes were performed.

No-tools tasks:

- return PATCH_BUNDLE only;
- do not simulate reads or command outputs;
- keep patches self-contained and reviewable.

## Profile comparison

| Profile | Prompt style | Runtime tools | Full catalog | GitHub tools |
|---|---|---|---|---|
| C1 | compact patch bundle | none | no | no |
| C2 | file-agent prompt | read/write/edit/glob/grep/bash | no | no |
| C3 | full agent prompt | full OpenCode catalog | yes | yes, if configured |
| C4 | compact prompt + this reference link | selected by runner | must be reported | must be reported |

## C4 prompt contract

A C4 prompt should include:

- this reference URL;
- a one-sentence description of what this reference contains;
- the actual runtime tools available in the current run;
- explicit statement whether full tool catalog was sent;
- explicit statement whether GitHub tools were sent;
- the concrete task brief and bounded scope.

The task prompt remains authoritative over this reference. If this reference conflicts with the task prompt, follow the narrower and safer instruction.
