# Kimi manual-only external reference profile

The `/kimifree` manual-only Kimi profile has file tools plus webfetch. No
GitHub tools. No full tool catalog.

## Available tools

`read`, `write`, `edit`, `glob`, `grep`, `bash`, `webfetch`.

See [kimi-agent-files.md](kimi-agent-files.md) for exact tool signatures.

## External reference URL

The `/kimifree` prompt includes a public reference URL that Kimi **must fetch
with `webfetch`** before implementation:

- URL: <https://github.com/AndrewVerhoturov1/codex-token-monitor/blob/main/docs/kimi-c4-external-tool-reference.md>
- Description: public compact reference for extended OpenCode/Kimi tool identity catalog, file/GitHub tool families, output formats, guard rules, and the manual-only Kimi contract.
- Action: call `webfetch` with this URL to read the reference content before starting any implementation task.

## Critical rules

- Call `webfetch` with the reference URL **before** starting implementation.
- Actual available tools are **only the tools listed by the runtime** in the prompt (`read`, `write`, `edit`, `glob`, `grep`, `bash`, `webfetch`).
- `webfetch` may only be used to fetch the designated reference URL, not arbitrary URLs.
- Do not claim a tool is available just because the reference names it.
- Do not call any tool not explicitly listed by the runtime.
- Never use GitHub tools (PR, issue, actions, search).
- Never use `websearch`.
- Never install dependencies or run network commands other than `webfetch` for the reference URL.
- Read a file before editing it.
