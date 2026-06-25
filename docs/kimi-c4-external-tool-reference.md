# Kimi C4 External Tool Reference

C4 is a Kimi execution profile where the agent receives only `webfetch` as a real tool, reads this public reference once via that tool, and returns a `PATCH_BUNDLE` instead of using file tools directly.

This file is reference text only. A model reading this file does not receive tool permissions from it. Actual tools are controlled only by the runtime profile and temporary OpenCode configuration used for that run.

---

## Table of Contents

1. [C4 Design Intent](#c4-design-intent)
2. [Allowed Actual Tool: webfetch](#allowed-actual-tool-webfetch)
3. [Virtual PATCH_BUNDLE Format](#virtual-patch_bundle-format)
4. [Windows Command Guidance](#windows-command-guidance)
5. [Safety Rules](#safety-rules)
6. [Final Response Checklist](#final-response-checklist)
7. [Example: Minimal C4 Workflow](#example-minimal-c4-workflow)

---

## C4 Design Intent

C4 is C1 + a public reference file.

- **C1**: no tools, PATCH_BUNDLE only.
- **C4**: webfetch (to read this reference) + PATCH_BUNDLE output.

C4 is **not** C2 (file tools). C4 is **not** C3 (full catalog). C4 does not receive read/write/edit/glob/grep/bash. C4 does not receive GitHub tools.

---

## Allowed Actual Tool: webfetch

### webfetch

Fetch content from a specified URL. Returns the content in the requested format.

**Parameters:**
- `url` (required): A fully-formed valid URL.
- `format` (optional): `"markdown"` (default), `"text"`, or `"html"`.

**Constraints:**
- `webfetch` may only be used to fetch the designated C4 reference URL provided by the runtime. Do not fetch arbitrary URLs.
- The reference URL is provided by the runtime in the agent prompt. Do not hardcode a URL in the task prompt.

---

## Virtual PATCH_BUNDLE Format

C4 does not have file tools. All file changes must be returned as a `PATCH_BUNDLE` in the model response. The outer OpenCode / Codex Route A is responsible for applying the bundle.

### PATCH_BUNDLE structure

A PATCH_BUNDLE is a sequence of patch blocks. Each block represents one file operation.

```
PATCH_BUNDLE start
--- a/<filepath>
+++ b/<filepath>
@@ -<start>,<count> +<start>,<count> @@
 <unified diff content>
--- a/<filepath>
+++ b/<filepath>
@@ -<start>,<count> +<start>,<count> @@
 <unified diff content>
PATCH_BUNDLE end
```

### File creation

For new files, use `/dev/null` as the source:

```
PATCH_BUNDLE start
--- a/dev/null
+++ b/path/to/new-file.ext
@@ -0,0 +1,<lineCount> @@
+<content line 1>
+<content line 2>
PATCH_BUNDLE end
```

### File deletion

```
PATCH_BUNDLE start
--- a/path/to/file.ext
+++ b/dev/null
@@ -<start>,<count> +0,0 @@
-<content line 1>
-<content line 2>
PATCH_BUNDLE end
```

### Rules

- Each PATCH_BUNDLE must have a clear `start` and `end` marker.
- File paths are relative to the repository root.
- Do not include unrelated files in the same bundle.
- The outer route applies the patch; C4 must not attempt to apply it via bash or any other tool.

---

## Windows Command Guidance

C4 agents never execute commands. However, if reference documentation or the task prompt mentions Windows commands, follow these rules:

- **Do not use `mkdir -p`**. This is a Unix-ism and produces errors in Windows PowerShell.
- **Preferred equivalent**: If a directory creation command is ever needed (in docs or examples), use:
  ```powershell
  New-Item -ItemType Directory -Force -Path "path\to\dir"
  ```
- **Preferred file creation**: Use PATCH_BUNDLE file creation (see above), not command-line file creation.

---

## Safety Rules

1. **No secrets**: Do not read, print, or expose .env, tokens, cookies, credentials, API keys, or any secret values.
2. **No installs**: Do not install or update packages, dependencies, or system components.
3. **No git writes**: Do not run git add/commit/push/reset/clean. All git operations are handled by the outer route.
4. **No permanent opencode config edits**: Do not edit opencode.jsonc or any OpenCode configuration files. Use only temporary config provided by the runtime.
5. **No GitHub tools**: Do not use any GitHub API tools (PR, issue, actions, search, file contents). GitHub operations are handled by the outer route.
6. **No file tools**: Do not use read/write/edit/glob/grep/bash. Use PATCH_BUNDLE for all file changes.
7. **No websearch**: Do not use websearch. Only webfetch for the designated reference URL.
8. **No network commands**: Do not run network commands (curl, wget, Invoke-WebRequest) via any interface. Only webfetch.
9. **Bounded scope**: Keep all work within the paths and scope specified in the task prompt.

---

## Final Response Checklist

Every C4 response must include:

- [ ] TASK_STATUS near the top (COMPLETED / PARTIAL / BLOCKED / FAILED / NEEDS_CODEX_DECISION)
- [ ] PATCH_BUNDLE for all file changes (if any)
- [ ] C4 actual tools reported (should be: webfetch only)
- [ ] full_tool_catalog_sent: false
- [ ] github_tools_sent: false
- [ ] permanent opencode config touched: false
- [ ] Git write actions used: none

---

## Example: Minimal C4 Workflow

1. Runtime launches C4 agent with `webfetch` tool and URL to this reference.
2. Agent calls `webfetch` with the reference URL to read this document.
3. Agent reads the task prompt.
4. Agent returns:
   - TASK_STATUS: COMPLETED
   - PATCH_BUNDLE with the required file changes
   - Verification summary
   - full_tool_catalog_sent: false
   - github_tools_sent: false
5. Outer OpenCode / Codex Route A applies the PATCH_BUNDLE and verifies.
