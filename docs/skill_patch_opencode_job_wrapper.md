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
