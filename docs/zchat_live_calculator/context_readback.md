# Context Readback

## Sources Read Report

| Field | Value |
|---|---|
| STATIC_MANUAL_READ | Read |
| Static manual URL/version/sections read | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_external_agent_static_manual.md`, v1.0.0, full visible source. |
| REPO_NAVIGATION_READ | Read |
| Repo navigation URL/version/sections read | `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_repo_navigation.md`, v1.0.0, full visible source. |
| TASK_PROMPT_READ | Read |
| Task prompt name/sections read | `ZCHAT-20260627-002044-stylish-calculator`, full uploaded task prompt. |
| SOURCE_URLS_READ | Read (2/2 fully, 0 partially, 0 not read): `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md`; `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/.ai/zchat/readme.md`. |
| SIDE_FILES_READ | Uploaded task prompt file `Вставленный текст(111).txt`; canonical public docs via raw GitHub URLs. |
| UNREAD_OR_UNAVAILABLE_SOURCES | None. |

## Confirmed

- The static manual identifies the role as an external chat agent with no repository authority, and says not to claim git, tests, runtime state, or unpublished repository knowledge. Source: `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_external_agent_static_manual.md`, lines 0-5.
- The static manual requires ZIP assembly with `manifest.json`, `checksums.sha256`, `payload/`, and a required context readback file. Source: `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_external_agent_static_manual.md`, lines 6-13.
- The static manual and repo navigation require physical ZIP paths to use `payload/{repo_relative_path}` while manifest and checksum paths are repo-relative without the `payload/` prefix. Sources: `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_external_agent_static_manual.md`, lines 8-13; `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zchat_repo_navigation.md`, line 4.
- The task prompt requires `zchat_result_type` to be `package`, `package_id` to equal `ZCHAT-20260627-002044-stylish-calculator`, and all deliverables to be under `docs/zchat_live_calculator/`. Source: uploaded task prompt, sections `Task`, `Constraints`, and `Expected Outputs`.
- The task prompt requires an offline, self-contained static calculator with modern UI, CSS animations, gradient backgrounds, smooth hover effects, responsive layout, basic arithmetic, keyboard support, vanilla JavaScript only, and no external dependencies. Source: uploaded task prompt, sections `Task` and `Constraints`.
- The repository README describes the project as `codex-token-monitor` and links Zchat to `.ai/zchat/readme.md`. Source: `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md`, lines 0-1.
- The Zchat README says ZIPs are untrusted, receive extracts to quarantine, v2 manifest requires `zchat_result_type`, `run_policy`, and `context_readback`, and extra payload files are rejected. Source: `https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/.ai/zchat/readme.md`, lines 0-12.

## Inferred

- Because the task prompt lists exactly seven expected deliverables and all are under `docs/zchat_live_calculator/`, the manifest payload list should contain exactly those seven repo-relative paths. This follows from the task sections `Expected Outputs`, `Allowed Paths`, and the static manual path rule.
- Because `verification/check_result.py` is listed as an expected output and the task requires `verification_files[]`, the same repo-relative path is included in `manifest.verification_files`. This follows from the task's `Expected Outputs` and `Verification Files Policy`.
- Because the task requires offline/self-contained operation and forbids remote assets and network requests, the website uses local `styles.css` and `app.js` only and does not include remote fonts, frameworks, libraries, or assets.

## Not verified

- Browser-specific rendering details are not verified from provided sources.
- Exact visual appearance on every screen size is not verified from provided sources.
- Acceptance by Zchat receive, inspect, verify, or decision stages is not verified from provided sources.

## Needs local verification

- Running repository-local Zchat receive, inspect, verify, decision, or apply stages requires local repository access and was not claimed.
- Running the optional `docs/zchat_live_calculator/verification/check_result.py` helper requires local review/execution after the package is received or applied.
- Git status, test results, commits, pushes, and repository cleanliness require local repository access and were not claimed.
