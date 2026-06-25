# Kimi C4 External Capability Catalog

This file is the **virtual capability catalog** for C4 execution. A model reading this file does not receive tool permissions from it. Actual tools are controlled only by the runtime profile and temporary OpenCode configuration used for that run.

**These are virtual protocols, not real OpenCode tool grants.**

---

## Table of Contents

1. [C4 Contract](#c4-contract)
2. [Catalog-Read Proof](#catalog-read-proof)
3. [Virtual Capabilities](#virtual-capabilities)
4. [Windows Guidance](#windows-guidance)
5. [Safety Prohibitions](#safety-prohibitions)
6. [Final Report Checklist](#final-report-checklist)

---

## C4 Contract

C4 is like C1 (PATCH_BUNDLE output), but with one real tool: `webfetch`. The agent reads this catalog via `webfetch` at task start, then uses virtual capabilities described here to produce PATCH_BUNDLE output.

**Hard rules:**
- The FIRST assistant message MUST contain a `webfetch` call to the reference URL.
- If `webfetch` is unavailable or fails, return `TASK_STATUS: BLOCKED` and do NOT produce PATCH_BUNDLE.
- All file changes MUST be returned as PATCH_BUNDLE. No real file tools are available.

---

## Catalog-Read Proof

To prove the catalog was read, include these fields in your response:

```
CATALOG_READ: true
CATALOG_VERSION: "2026-06-25"
CATALOG_SECTIONS_USED: ["virtual-capabilities", "windows-guidance", "safety-prohibitions"]
```

---

## Virtual Capabilities

These are virtual protocols for producing PATCH_BUNDLE output. They are NOT real tool calls.

### PATCH_BUNDLE.create_file

Create a new file in the repository.

**Virtual call:**
```
PATCH_BUNDLE.create_file(
  path: "relative/path/to/file.ext",
  content: "file content here"
)
```

**Produces PATCH_BUNDLE block:**
```
--- a/dev/null
+++ b/relative/path/to/file.ext
@@ -0,0 +1,<lineCount> @@
+<content line 1>
+<content line 2>
```

### PATCH_BUNDLE.update_file

Update an existing file. You must read the file content first (via webfetch if needed, or from task context).

**Virtual call:**
```
PATCH_BUNDLE.update_file(
  path: "relative/path/to/file.ext",
  old_content: "original content",
  new_content: "updated content"
)
```

**Produces PATCH_BUNDLE block:**
```
--- a/relative/path/to/file.ext
+++ b/relative/path/to/file.ext
@@ -<start>,<count> +<start>,<count> @@
-old line
+new line
```

### PATCH_BUNDLE.multi_file_artifact

Bundle multiple file operations into one PATCH_BUNDLE.

**Virtual call:**
```
PATCH_BUNDLE.multi_file_artifact(
  operations: [
    { type: "create", path: "file1.ext", content: "..." },
    { type: "update", path: "file2.ext", old_content: "...", new_content: "..." }
  ]
)
```

**Produces:** A single PATCH_BUNDLE with multiple file blocks.

### PATCH_BUNDLE.no_mkdir_required

Directory creation is handled implicitly by file paths. Never include explicit directory creation commands in PATCH_BUNDLE.

**Virtual call:**
```
PATCH_BUNDLE.no_mkdir_required()
```

**Effect:** Acknowledges that directories will be created as needed by the outer route when applying file patches.

---

## Windows Guidance

C4 agents never execute commands. If reference documentation or the task prompt mentions Windows commands, follow these rules:

- **Never use `mkdir -p`**. This is a Unix-ism and produces errors in Windows PowerShell.
- **Preferred approach:** Create directories implicitly through patch paths (file creation implies directory creation).
- **If an external executor explicitly asks for a command:** Use only `New-Item -ItemType Directory -Force -Path "path\to\dir"`. Do not use `mkdir`.

---

## Safety Prohibitions

1. **No secrets:** Do not read, print, or expose .env, tokens, cookies, credentials, API keys, or any secret values.
2. **No installs:** Do not install or update packages, dependencies, or system components.
3. **No git writes:** Do not run git add/commit/push/reset/clean.
4. **No permanent config edits:** Do not edit opencode.jsonc or any OpenCode configuration files.
5. **No GitHub tools:** Do not use any GitHub API tools (PR, issue, actions, search, file contents).
6. **No file tools:** Do not use read/write/edit/glob/grep/bash. Use PATCH_BUNDLE for all file changes.
7. **No websearch:** Do not use websearch. Only webfetch for the designated reference URL.
8. **No network commands:** Do not run network commands (curl, wget, Invoke-WebRequest).
9. **Bounded scope:** Keep all work within the paths and scope specified in the task prompt.

---

## Final Report Checklist

Every C4 response must include:

- [ ] `TASK_STATUS` near the top (COMPLETED / PARTIAL / BLOCKED / FAILED / NEEDS_CODEX_DECISION)
- [ ] `webfetch` call made as first action (no webfetch = rule violation)
- [ ] `CATALOG_READ: true` proof included
- [ ] PATCH_BUNDLE for all file changes (if any; must NOT exist if webfetch failed)
- [ ] C4 actual tools reported (should be: webfetch only)
- [ ] `full_tool_catalog_sent: false`
- [ ] `github_tools_sent: false`
- [ ] `permanent_opencode_config_touched: false`
- [ ] Git write actions used: none
