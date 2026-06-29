---
name: opencode-mcp-windows-control
description: Use before any repo or workspace task to route Codex through the correct OpenCode path, enforce no-local-work safety, and load conditional OpenCode skills only when the route or task type requires them.
---

# OpenCode Direct MCP Control

## Purpose

Codex MUST read this skill before any repo/workspace action.

This skill applies to any filesystem-backed engineering task, not only Git repositories.

This includes repositories, workspaces, project folders, scripts, config files,
documentation files, Codex/OpenCode skills, skill scripts, tests, reports, and
local tool files.

This skill is the mandatory dispatcher for:

- route selection;
- forbidden fallbacks;
- batch economy;
- OpenCode task shaping;
- conditional skill loading;
- stop rules.

Keep this skill short. Rare route details belong in conditional skills.

## Skill-first and no local filesystem work

If the task touches local files, project files, skill files, scripts, configs,
docs, reports, tests, or tool files, OpenCode is required by default.

Codex MUST NOT read, search, list, inspect, edit, delete, archive, or verify
local files by itself unless the user explicitly allows one specific local
Codex action in the current task.

Before and after reading this skill, Codex MUST NOT inspect the target repo or
workspace locally with filesystem listing, reading, or search tools, and MUST
NOT use local Git inspection such as `status`, `diff`, `log`, or `show` as a
fallback.

Forbidden by default:

- no local repo/workspace inspection by Codex;
- no filesystem listing/reading/search as fallback;
- no local Git inspection as fallback;
- no old Windows bridge;
- no silent fallback to local work.

Allowed exceptions:

- reading this skill file;
- editing this skill locally is allowed only when the user explicitly says in the
  current task that Codex may perform that exact local action without OpenCode;
- non-repo files outside this workflow when the task is not repo/workspace
  inspection or modification.

Boundary escalation rule:

- if Codex believes local Codex work is needed for the next step, Codex MUST
  stop before that local action and ask the user for permission for that one
  exact action;
- if Codex wants to use OpenCode outside the repo/workspace scope governed by
  this skill, or outside the routes, exceptions, or stop rules defined here,
  Codex MUST stop and ask the user for explicit permission before using
  OpenCode.

If OpenCode is required but unavailable or blocked, Codex MUST stop unless the
user explicitly changes the workflow.

## Batch economy rules

Codex MUST reduce unnecessary model launches.

Main rule:

```text
Same-type and independent actions MUST be batched.
Risky or decision-dependent actions MUST be separate steps.
```

Before reading, searching, checking, calling a tool, or delegating to
OpenCode, Codex MUST decide:

```text
1. Which sources or actions are needed.
2. Which of them are independent.
3. Which actions can be executed as one batch.
4. Where a decision boundary exists.
5. What is the smallest useful result needed.
```

Codex MUST:

- read related skills, notes, and docs as one source batch when they are
  already predictable;
- batch independent tool actions when the tool supports it;
- prefer one bounded OpenCode task over many small calls;
- use one preflight batch before normal repo work;
- use one result-check batch after edits or delegated work;
- summarize long logs instead of pulling full logs into context.

A second source batch is ALLOWED ONLY if a new reason appeared.

Default log rule:

```text
Inspect relevant tail only.
Search ERROR/WARN/FAIL.
Identify first real error.
Return compact summary.
```

Before acting, Codex MUST self-check:

```text
1. Can this be batched?
2. Is there a decision boundary?
3. Will long output enter context?
4. Can OpenCode do this cheaper as one bounded task?
5. If OpenCode is unavailable, will I stop instead of using a fallback?
```

## Roles

Codex:

- understands the task;
- chooses the route;
- shapes the OpenCode prompt;
- decides risky steps;
- reviews evidence;
- gives the final user answer.

OpenCode:

- searches, reads, and maps repo/workspace state;
- performs allowlisted edits inside scope;
- discovers commands;
- executes only commands selected by Codex;
- returns compact evidence.

## Default workflow

Prefer one bounded OpenCode task over many micro-calls.

Default flow:

1. Codex splits the user request into meaningful phases.
2. If route choice requires repo facts, the first repo-facing phase MUST be Route A
   reconnaissance. Codex must not gather those facts locally.
3. Codex chooses the best route for the first phase.
4. Codex loads conditional skills only when a phase requires them.
5. Codex executes the phase through the selected route.
6. At the next phase boundary, Codex re-evaluates the route.
7. Codex stops or continues with the next route in the route chain.

Use separate decision loops only for writes, tests/builds, cleanup, Git/GitHub
actions, or other risk-increasing steps.

## Per-phase route planning

Before every meaningful action boundary, Codex MUST decide which route is best
for the next phase.

Meaningful phases include:

- skill loading;
- repo/workspace exploration;
- file reading;
- context gathering;
- planning;
- code implementation;
- code modification;
- verification;
- test/lint/build execution;
- report handoff;
- cleanup;
- GitHub work;
- recovery after route failure.

Codex MUST NOT assume that the route used for exploration should also be used
for implementation.

Exploration and implementation may use different routes in the same user task.

Verification may use a different route than implementation.

Route changes are allowed only at phase boundaries and must have a reason.

The first phase may be route planning from the user request only.

Codex may draft a provisional route chain from the prompt, but MUST NOT inspect
the repository locally to confirm it.

When repo evidence is needed, Codex MUST insert a Route A reconnaissance phase
before deciding the implementation route.

Before each phase, Codex MUST internally answer:

```text
PHASE:
ACTION TYPE:
BEST ROUTE:
WHY THIS ROUTE:
CONDITIONAL SKILL NEEDED:
STOP BOUNDARY:
BUDGET:
```

This route decision may be kept compact, but it must guide the next action.

If the route decision changes from the previous phase, Codex must know why.

## Pre-route repository reconnaissance

Codex MUST NOT inspect the repository or workspace locally in order to choose a
route.

Route selection starts from:

- the user request;
- this routing skill;
- already loaded explicit task context;
- previously returned OpenCode evidence from the current task.

If Codex needs repository facts before choosing the implementation route, that
fact-gathering is itself a meaningful phase and MUST use Route A.

Default pre-route repo reconnaissance:

- route: Route A / standard OpenCode MCP;
- mode: `context_pack`;
- purpose: gather only the minimum facts needed to choose the next route;
- no edits;
- no Git writes;
- compact output.

Codex MUST NOT use local filesystem listing, reading, search, or local Git
inspection as a route-selection shortcut.

Forbidden route-selection shortcuts:

- `ls`;
- `dir`;
- `Get-ChildItem`;
- `find`;
- `rg`;
- `grep`;
- `cat`;
- `Get-Content`;
- local `git status`;
- local `git diff`;
- local `git log`;
- reading repo files directly through Codex tools.

If route choice depends on repo structure, file locations, existing commands,
or current changed files, Codex MUST ask OpenCode for a bounded Route A
`context_pack` or `verify_pack` first.

## Route selection policy

Codex MUST choose the best execution route for each meaningful phase of the
user task, not one route for the whole user task.

A single user request may require a route chain.

Examples:

- repo exploration -> Route A;
- file reading / context_pack -> Route A;
- medium code implementation -> Route C / DeepSeek 4 Pro via OpenCode Jobs;
- diff / changed-file verification -> Route A;
- GitHub work -> GitHub skill through OpenCode;
- cleanup -> cleanup skill;
- long report -> report handoff skill;
- direct-route failure recovery -> Route B.

### Route A: standard OpenCode MCP / DeepSeek

Default route for ordinary small and low-risk repo/workspace work:

```text
Codex -> mcp__opencode.* -> OpenCode -> deepseek/deepseek-v4-flash
```

Route A is the default for investigation, reading, mapping, verification, and
small low-risk edits.

Route A is also the required route for repository reconnaissance needed to
choose later routes.

Confirmed terminal failure, quota exhaustion, explicit model error, or
confirmed empty/no-content result on Route A allows exactly one model fallback:

```text
Codex -> mcp__opencode.* -> OpenCode -> opencode/deepseek-v4-flash-free
```

If the fallback model also fails, returns no usable content, or is unavailable,
Codex MUST stop and explain the blocker to the user.

Route A SHOULD be used for:

- repo search;
- multi-file reading;
- `context_pack`;
- project mapping;
- config/log/error analysis;
- safe command discovery;
- diff summary;
- changed-file verification;
- `verify_pack`;
- tiny obvious edits with no new logic;
- where a feature should live;
- which files are relevant;
- whether the task is UI-only or backend-related;
- whether the edit is tiny or medium;
- which commands are safe;
- what changed after another route acted.

For ordinary small tasks, this route is mandatory.

Route A SHOULD NOT be used for medium or larger code implementation merely
because it was used for the earlier exploration phase.

### Route B: job-wrapper fallback bell route

Use `mcp__opencode_jobs.opencode_job_run_and_wait` only as bounded recovery
when the standard route has already shown a real problem in the current task:

- timeout;
- empty or no text answer;
- busy or stuck session;
- missing final answer;
- check/wait spiral would otherwise be needed.

Fallback bell route MUST NOT become the new default route.
After a fallback attempt, the next new OpenCode task MUST start again with the standard `mcp__opencode.*` route.
Codex MUST NOT begin future tasks with the fallback route merely because it was used before.

### Route C: DeepSeek 4 Pro via OpenCode Jobs

Use DeepSeek 4 Pro through `mcp__opencode_jobs.opencode_job_run_and_wait`
when Route C is selected by per-phase route planning for a bounded code
implementation phase.

Route C is the preferred implementation route for medium bounded code work.

Before using Route C, Codex MUST read `opencode-deepseek-pro-jobs-control`.

Codex SHOULD select Route C for the implementation phase when the phase
requires creating or changing non-trivial code logic.

Codex MUST prefer Route C when the implementation phase has two or more of
these signals:

- new standalone app/game/tool;
- multiple new files;
- multiple interacting code subsystems;
- UI plus state plus behavior;
- game loop or realtime behavior;
- parser/export/import logic;
- non-trivial state management;
- medium feature slice;
- bug fix requiring logic changes across several files;
- tests plus implementation for one defined behavior.

Using Route A for exploration does not authorize using Route A for the later
implementation phase.

Route C should not perform initial broad repository exploration.

If Route C implementation needs repo context, Codex MUST first gather the minimum
needed context through Route A, then pass only the bounded implementation
context to the Route C jobs run.

Route C is for:

- medium `patch_pack` tasks;
- one approved feature slice;
- one understood bug;
- tests for one defined behavior;
- bounded medium/complex code changes where ordinary Route A is too weak but
  Codex should not work locally.

Route C MUST use only this transport and model:

```text
Codex -> mcp__opencode_jobs.opencode_job_run_and_wait -> job-wrapper -> OpenCode -> deepseek/deepseek-v4-pro
```

Route C MUST NOT silently fall back to:

- Kimi;
- `opencode/deepseek-v4-flash-free`;
- `deepseek/deepseek-v4-flash`;
- local Codex repo work;
- the old Windows bridge.

Route C MUST NOT be used for:

- initial broad repo exploration;
- vague tasks;
- repo-wide refactors;
- dependency changes;
- install/network/server/watch commands;
- secrets or `.env`;
- permanent OpenCode config edits;
- Git/GitHub write actions;
- tasks too large for one bounded run.

If the task is too large, Codex MUST split it before using Route C.

If DeepSeek 4 Pro, the jobs wrapper, or the Route C result is unavailable,
empty, off-scope, or otherwise unusable, Codex MUST stop and explain the
blocker to the user. Codex MUST NOT silently switch to Kimi, Flash, or local
Codex work.

Route A may still be used for tiny code edits when all are true:

- one small file or one obvious local change;
- no new subsystem;
- no non-trivial logic;
- no cross-file reasoning;
- no new test behavior;
- low risk and clearly bounded.

Examples:

- text label change;
- README/Markdown edit;
- simple CSS tweak;
- obvious one-line HTML tweak.

If unsure between Route A and Route C:

- choose Route A for investigation, reading, mapping, and verification;
- choose Route C for implementation, new code, non-trivial logic, or medium
  `patch_pack` work.

### Route D: Codex local work

Codex local filesystem work is forbidden by default.

This applies to repositories, workspaces, project files, scripts, config files,
documentation files, Codex/OpenCode skills, skill scripts, tests, reports, and
local tool files.

Codex may read, search, list, inspect, edit, delete, archive, or verify local
files only when the user explicitly says in the current task that Codex may
perform that one exact local action without OpenCode.

This permission is single-action only.
It does not authorize local Codex work for the rest of the session.

If Codex concludes that a local action is needed, Codex MUST stop before doing
it and ask the user for permission for that exact local action.

A request to edit a skill, config, script, doc, report, test, or repo file is
not by itself permission for local Codex work.

If OpenCode is unavailable or blocked, Codex MUST stop and report
`TASK_STATUS: BLOCKED` or `TASK_STATUS: PARTIAL` unless the user explicitly
changes the workflow and allows local Codex work.

Codex remains responsible for:

- understanding the task;
- choosing the route;
- shaping prompts;
- deciding risky steps;
- reviewing evidence;
- final user explanation.

## General plugin skill priority

This OpenCode routing skill has priority for route selection and execution
path.

General creative, brainstorming, or TDD skills MUST NOT create extra approval
gates for isolated bounded prototype tasks unless the user explicitly requested
that workflow.

For standalone throwaway prototypes, Codex may proceed with a compact design
assumption and bounded implementation unless the user explicitly asked for a
separate design approval step.

Do not load general plugin skills merely because the task is creative if doing
so would block the OpenCode route plan or add unnecessary model calls.

Conditional route skills listed in this skill have priority over general plugin
skills.

## Conditional skills

Codex MUST NOT load conditional skills by default.

Codex MUST load a conditional skill only after the route or task type requires
it.

Conditional skills:

- `opencode-zworker-control`
  Load only for `/zworker` or an explicit external worker route request. Do not load it by default.

- `zworker-auto`
  Load only for `/zworker-auto` or an explicit request to run the fully automated ChatGPT Web zworker route. Do not load it by default.

- `opencode-deepseek-pro-jobs-control`
  Load only when Route C / DeepSeek 4 Pro via OpenCode Jobs is deliberately selected.

- `opencode-kimi-runtime-launch`
  Load only for `/kimifree` or an explicit Kimi request.

- `opencode-github-mcp-control`
  Load only for explicit GitHub tasks.

- `opencode-report-handoff`
  Load only for long workspace report workflows.

- `opencode-cleanup-control`
  Load only for cleanup planning or cleanup execution.

Codex MUST read all needed conditional skills as one source batch.

Codex MUST NOT read conditional skills merely because they exist.

## OpenCode task modes

`context_pack`

- read, search, map, summarize;
- no edits;
- compact output only.

`patch_pack`

- make a small allowlisted edit;
- return changed files, diff summary, checks, and risks.

`verify_pack`

- verify current state, diff, or checks;
- no edits unless explicitly allowed.

## OpenCode task formulation

Every delegated OpenCode work request MUST be formulated as one bounded batch
task using this structure.
This does not apply to narrow status, check, recovery, readback, or discovery
calls explicitly allowed by this skill.

```text
MODE:
GOAL:
SCOPE:
MUST DO:
MUST NOT:
STOP BEFORE:
OUTPUT:
BUDGET:
```

Requirements:

- `MODE` MUST be one of `context_pack`, `patch_pack`, or `verify_pack`;
- `GOAL` MUST state the concrete result;
- `SCOPE` MUST bound files, paths, or decision area;
- `MUST DO` MUST list the minimal required actions;
- `MUST NOT` MUST ban unsafe extras and drift;
- `STOP BEFORE` MUST define the decision boundary;
- `OUTPUT` MUST require compact evidence;
- `BUDGET` MUST bound calls, checks, or artifacts.

Forbidden vague tasks:

```text
study the repo
fix everything
continue until done
do whatever is needed
run all checks
clean up as needed
```

## OpenCode-only categories

The following categories are OpenCode-only by default even when the target is
not a Git repository.

The following repo/workspace tasks are OpenCode-only:

- skill file reading/editing;
- skill script reading/editing;
- local config/script/doc/test/report file work;
- local tool file work;
- repo search and multi-file reading;
- project mapping and entry point discovery;
- `TODO`/`FIXME` audit;
- folder structure, relation/import, config, log, and error analysis;
- safe test/lint/build discovery;
- selected safe test/lint/build execution after Codex decision;
- draft Markdown docs and context packs;
- simple allowlisted edits, diff summary, and changed-file verification;
- workspace-local report handoff;
- cleanup planning and cleanup execution after Codex decision;
- `.gitignore` candidate analysis;
- read-only Git verification.

## OpenCode route policy

Allowed delegation paths:

```text
Primary route:
Codex -> mcp__opencode.* -> OpenCode

Fallback bell route:
Codex -> mcp__opencode_jobs.opencode_job_run_and_wait -> job-wrapper -> OpenCode
```

Do not use for repo tasks:

- `opencode-new-request-windows.ps1`;
- `opencode-runner-windows.ps1`;
- the old request-runner bridge;
- manual shell invocation of `opencode`.

For ordinary OpenCode repo/workspace tasks, Codex MUST use standard
`mcp__opencode.*` first.

If the standard route succeeds and returns useful content, Codex MUST NOT call
the job-wrapper route.

When fallback bell route is used:

- make one bounded fallback attempt;
- do not open a manual `check`/`wait` spiral around it;
- treat it as recovery for the current failed direct-route attempt only.

The fallback bell route is recovery for the current failed direct-route attempt only. It does not change the default route for later tasks. Every new ordinary OpenCode task starts with standard `mcp__opencode.*`.

Fresh-session discovery rule:

- if the fallback tool is not already callable when it is actually needed,
  Codex MUST do exactly one targeted `tool_search` for `opencode_job_run_and_wait`
  or `opencode_jobs`;
- if discovery succeeds, use the discovered fallback route;
- only if that single discovery step fails may Codex report the route unavailable.

Codex MUST NOT use repeated `check`/`wait` loops as the normal waiting method.

## Call budget and hard cap

For ordinary tasks:

- OpenCode/MCP calls target: `2-4`;
- hard cap: `6`.

The hard cap is a stop rule, not advice.

If the hard cap is reached before the task succeeds, stop and report
`TASK_STATUS: PARTIAL` or `TASK_STATUS: BLOCKED`.

Timeout recovery limit:

1. one check or status call;
2. one short wait;
3. one result or readback attempt.

If still unresolved, stop.

Do not call by default:

- `opencode_setup`;
- `opencode_provider_models`;
- extra `tool_search`.

For ordinary Route A tasks, `opencode_provider_models` is not part of the normal
path.

For conditional GitHub tasks, `opencode_setup` and GitHub MCP status/preflight
may be allowed by `opencode-github-mcp-control`, but `opencode_provider_models`
still remains forbidden unless the model discovery rule below allows it.

## Status protocol

OpenCode should return exactly one valid `TASK_STATUS` near the start of the
meaningful answer:

```text
TASK_STATUS: COMPLETED
TASK_STATUS: FAILED
TASK_STATUS: PARTIAL
TASK_STATUS: BLOCKED
TASK_STATUS: BLOCKED_PERMISSION
TASK_STATUS: NEEDS_CODEX_DECISION
```

Protocol goal:

- one valid status;
- near the start;
- no contradictory second status;
- short summary and evidence after status.

Functional result has priority over protocol perfection.

If the task is completed, the repo/workspace is safe, and the result is useful,
that is a functional pass.

Bad, late, or missing `TASK_STATUS`, extra chatter, minor formatting issues, or
pre-existing untracked files are protocol/process warnings, not automatic
failure.

Fail only when the task is not completed, the result is unclear, the
repo/workspace was damaged, a forbidden action was performed, the old bridge
was used, or a required blocker prevented completion.

## Default DeepSeek model

Default model:

- providerID: `deepseek`
- modelID: `deepseek-v4-flash`
- reasoning effort: `max`

## Model discovery rule

For Route A / standard OpenCode MCP, Codex MUST use the skill-default model:

- providerID: `deepseek`
- modelID: `deepseek-v4-flash`
- reasoning effort: `max`

Codex MUST NOT call `opencode_provider_models` merely to confirm or rediscover
this default model.

`opencode_provider_models` is ALLOWED ONLY when:

- `opencode_setup` or a required status/preflight indicates the default provider
  is missing or unavailable;
- the selected route explicitly requires a non-default provider/model;
- the user explicitly asks to inspect or change models;
- there is a confirmed model/provider error and Codex is diagnosing that exact
  blocker.

General MCP tool recommendations to discover providers/models do not override
this skill-default model rule.

Fallback model for Route A after confirmed terminal failure, quota exhaustion, explicit
model error, or confirmed empty/no-content result:

- providerID: `opencode`
- modelID: `deepseek-v4-flash-free`
- reasoning effort: `max`

If this Route A fallback model also fails or returns no usable content, Codex
MUST stop and explain the blocker to the user.

OpenCode must not ask the human user for permission:

- if a scope or risk decision is needed -> `TASK_STATUS: NEEDS_CODEX_DECISION`;
- if blocked by permission policy -> `TASK_STATUS: BLOCKED_PERMISSION`.

## Long report trigger only

For long outputs, OpenCode should write a workspace-local report artifact
instead of pasting a huge report into chat.

Before detailed long-report handoff, Codex MUST read
`opencode-report-handoff`.

Default report directory remains:

```text
<workspace>\_opencode_reports\
```

Do not use `external_directory` or Codex attachment paths by default.

## GitHub trigger only

GitHub is explicit-only.

Before any GitHub task, Codex MUST read `opencode-github-mcp-control`.

GitHub route is OpenCode-mediated only.

For any GitHub task, "GitHub MCP" means:

Codex -> mcp__opencode.* -> OpenCode -> GitHub MCP

Codex MUST NOT use direct Codex-side GitHub tools or connectors, including but
not limited to tools named like:

- `mcp__codex_apps__github.*`;
- `github.*`;
- direct GitHub connector actions;
- local `gh`;
- direct GitHub API calls.

This ban applies even for read-only GitHub tasks.

A successful OpenCode preflight is not enough. The actual GitHub read/write
operation MUST also be performed through OpenCode.

Using direct Codex-side GitHub tools is a route violation, even if the action is
read-only and the result is correct.

No GitHub MCP, `gh`, PR, issue write, push, merge, or remote write action is
allowed unless the user explicitly requested a GitHub task and the GitHub
skill allows it.

Exception: the skill-edit commit/push obligation (see Git write restrictions
section) creates a narrow exception for skill-file edits within the completion
phase of a task that modified skills.

## Cleanup trigger only

Cleanup requires a decision loop.

Before cleanup planning or cleanup execution, Codex MUST read
`opencode-cleanup-control`.

Default rule:

```text
OpenCode proposes cleanup plan -> Codex selects approved paths -> OpenCode deletes/archives only selected paths.
```

Codex MUST NOT delete/archive repo paths locally.
OpenCode MUST NOT decide on its own what to delete/archive.

## Test/lint/build loop

Test/lint/build loop:

1. OpenCode discovers possible commands and rates safety.
2. Codex selects one safe command or refuses execution.
3. OpenCode executes only the selected command.

Without a separate Codex decision, do not run:

- install commands;
- network commands;
- server or watch commands;
- commands requiring secrets;
- commands that write external directories;
- Git write commands.

## Git write restrictions

Local Git writes are forbidden by default:

- `git add`;
- `git commit`;
- `git push`;
- `git merge`;
- `git rebase`;
- `git reset`;
- `git clean`;
- pull requests;
- remote/GitHub write actions.

### Skill-edit commit/push obligation

When the current task edits any skill file (*SKILL.md*, skill scripts, or
skill-pack files governed by this routing framework), those changes are not
considered complete until the commit and push to GitHub have been prepared or
executed.

Codex MUST include commit/push of skill changes in the mandatory completion
phase, unless:

- the user explicitly forbids remote write in the current task;
- the GitHub/remote route is blocked or unavailable;
- the user has explicitly changed the workflow to allow local-only skill edits
  without GitHub sync.

This is a narrow exception to the general Git write restriction: it applies
only to skill-file edits and only within the completion phase of a task that
modified skills.

This obligation does not authorize general repo Git writes, unrelated commits,
or PRs outside the skill scope.

## User-facing compact output

Codex must keep user-facing output compact.

OpenCode output should also stay compact:

- no progress messages;
- no long logs;
- no huge report restatements in chat when a file artifact exists.

## Quiet commentary mode

By default, Codex MUST NOT print intermediate commentary, progress messages,
thinking updates, or verbose play-by-play explanations.

Codex MAY show short working updates only when the current user message contains
at least one show-mode control trigger.

Show-mode triggers:
- `+мысли`
- `+комментарии`
- `+прогресс`
- `+объясняй`
- `+подробно`

Quiet-mode triggers (return to silent):
- `-мысли`
- `+молча`
- `+тихо`
- `+без_комментариев`

Control trigger rules:
- The last control trigger in the user message wins.
- Control triggers are case-sensitive and must appear as whole tokens.
- Control triggers MUST NOT be repeated to the user.
- Control triggers MUST NOT be forwarded to external prompts unless they are
  part of the useful payload.

This is NOT a chain-of-thought request. When show-mode is active, only short
working updates are permitted. Internal hidden reasoning chains are never
allowed as visible output.

The following are ALWAYS shown, regardless of quiet mode:
- final answer;
- blockers and task status;
- errors and error explanations;
- safety warnings;
- direct questions to the user.

## Route reminder

```text
Small work -> standard OpenCode MCP / DeepSeek.
Route A default model -> deepseek/deepseek-v4-flash.
Route A model fallback after confirmed failure -> opencode/deepseek-v4-flash-free once.
Route A fallback failed -> stop and explain the blocker.
Direct MCP failed in current task -> one job-wrapper fallback attempt.
Next new task -> standard OpenCode MCP again.
Medium bounded code implementation -> Route C / DeepSeek 4 Pro via OpenCode Jobs by default.
Route C DeepSeek Pro failed -> stop and explain the blocker.
Kimi -> manual-only via /kimifree or explicit user request.
Codex local repo work -> only with explicit workflow change.

Route chain reminder:

- investigation -> Route A;
- reading/context -> Route A;
- medium code implementation -> Route C;
- verification/diff -> Route A;
- GitHub -> GitHub skill through OpenCode;
- cleanup -> cleanup skill;
- long report -> report handoff skill;
- fallback -> Route B only after direct-route failure.
```

When reporting the route chain to the user, include the concrete provider/model
used for each phase that actually ran, when known (for example
"Route A via deepseek/deepseek-v4-flash" rather than just "Route A").

## Regression smoke

After editing this skill, run a minimal smoke:

- skill read first;
- filesystem-backed skill/config/script/doc tasks require OpenCode by default;
- a request to edit a skill is not by itself permission for local Codex work;
- Codex local file work happens only after explicit permission for one exact
  local action;
- if Codex wants local work, Codex stops first and asks for that exact action;
- no local repo inspection;
- Codex does not inspect repo locally to choose a route;
- repo reconnaissance for route selection uses Route A;
- Route C implementation receives bounded context gathered by Route A;
- route choice based on repo structure never uses local `ls/rg/Get-Content/git`;
- conditional skills are not loaded by default;
- Codex chooses routes per phase, not one route for the whole task;
- Route A exploration does not force Route A implementation;
- Route A primary model is `deepseek/deepseek-v4-flash`;
- Route A fallback model is `opencode/deepseek-v4-flash-free`;
- Route A stops and reports if the fallback model also fails;
- medium code implementation selects Route C by default;
- standalone app/game/tool implementation selects Route C when bounded;
- Route C uses DeepSeek 4 Pro via `mcp__opencode_jobs.opencode_job_run_and_wait`;
- Route C does not silently fall back to Kimi, Flash, local Codex work, or the old bridge;
- Kimi is manual-only through `/kimifree` or explicit Kimi request;
- verification after Route C may return to Route A;
- general brainstorming/TDD plugin skills do not add approval gates unless user
  explicitly requested that workflow;
- final report includes the route chain used;
- one bounded OpenCode task by default;
- explicit `MODE/GOAL/SCOPE/MUST DO/MUST NOT/STOP BEFORE/OUTPUT/BUDGET`;
- target `2-4` calls, hard cap `6`;
- test/lint/build loop stays in main skill;
- job-wrapper fallback stays in main skill;
- no old bridge;
- no `external_directory`;
- GitHub read-only must use OpenCode-mediated route;
- direct Codex-side GitHub tools are forbidden even for read-only;
- OpenCode preflight followed by direct Codex GitHub reads is a route violation;
- valid GitHub route proof must say: direct Codex-side GitHub tools used: no;
- skill edits include mandatory commit/push obligation in completion phase
  (see Git write restrictions section);
- compact final answer.
