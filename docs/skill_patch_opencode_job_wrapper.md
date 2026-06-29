## OpenCode job-wrapper route

For ordinary OpenCode repository/workspace tasks, Codex MUST prefer the dedicated job-wrapper MCP tool:

`mcp__opencode_jobs.opencode_job_run_and_wait`

This tool should be used instead of manual `check`/`wait`/`reply`/`conversation` loops.

Direct `mcp__opencode.*` remains allowed only for:

- repo-context diagnostics;
- permission/session/debug checks;
- fallback after job-wrapper failure;
- tasks explicitly requiring direct OpenCode control.

Codex MUST NOT use repeated `check`/`wait` loops as the normal waiting method.
The job-wrapper waits outside the model loop and returns one compact result.

---

## zworker-auto web path

**Attach-only via existing Chrome CDP.** Codex MUST use the already-running browser instance. Launch of a new browser profile in this scenario is forbidden.

**New chat validity.** A new ChatGPT session is considered valid only when the page URL matches the real ChatGPT pattern `/c/...` (e.g. `https://chatgpt.com/c/<uuid>`). Any other URL is not a valid chat start.

**Long web-run path.** For ChatGPT Web tasks that exceed normal timeout expectations, Codex MUST route through the long web-run path — same attach-only CDP flow, but with extended timeout handling via `mcp__opencode_jobs` or equivalent long-running wrapper.

**Semantic ZIP acceptance/remap.** When a completed task delivers a ZIP result, Codex MUST accept it by content semantics, not by exact filenames. If the mapping is unambiguous and safe, files inside the archive may be remapped (e.g. `output.txt` → `src/main.py`) without rejecting the entire result. Reject only if content semantics are unclear or multiple safe interpretations exist.
