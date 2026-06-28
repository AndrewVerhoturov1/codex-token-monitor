# Kimi output formats

## TASK_STATUS

Must be the first line of the response:

```
TASK_STATUS: ok
TASK_STATUS: blocked
TASK_STATUS: done
TASK_STATUS: partial
```

Used for parseable status. One line only, no extra text on that line.

## FILE annotation

Inline file reference for traceability:
```
FILE: src/main.js:42
```

## Verification summary

After implementation, report:
- Files changed: list
- Verification command run: output
- Result: pass/fail

## Route report

```
runtime_config_only=true
permanent_opencode_config_touched=false
full_tool_catalog_sent=false
github_tools_sent=false
```