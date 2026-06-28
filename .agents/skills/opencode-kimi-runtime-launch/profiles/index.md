# Kimi execution profile

Single profile: **/kimifree (manual-only Kimi)**.

## /kimifree

| Tools | Description |
|-------|-------------|
| read, write, edit, glob, grep, bash, webfetch | File tools plus webfetch for the public external reference URL. Kimi must call webfetch to read the reference URL before implementation. GitHub tools are never sent. |

## Profile files

- [kimi-agent-core.md](kimi-agent-core.md) — agent rules, stop rules
- [kimi-agent-files.md](kimi-agent-files.md) — file tools (read/write/edit/glob/grep/bash)
- [kimi-agent-output.md](kimi-agent-output.md) — output formats (TASK_STATUS, FILE, verification summary, route report)
- [kimi-agent-external-reference.md](kimi-agent-external-reference.md) — external reference URL and webfetch rules
