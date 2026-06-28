# Kimi file tools

Minimal file tools. No GitHub tools.

## Available tools

### read
Read a file or directory from the local filesystem.
```
<invoke name="read">
<parameter name="filePath" string="true">/absolute/path/to/file</parameter>
</invoke>
```
Parameters: `filePath` (string, required).

### write
Write a file to the local filesystem.
```
<invoke name="write">
<parameter name="filePath" string="true">/absolute/path/to/file</parameter>
<parameter name="content" string="true">file content</parameter>
</invoke>
```
Parameters: `filePath` (string, required), `content` (string, required).

### edit
Edit a file by replacing exact text.
```
<invoke name="edit">
<parameter name="filePath" string="true">/absolute/path/to/file</parameter>
<parameter name="oldString" string="true">text to replace</parameter>
<parameter name="newString" string="true">new text</parameter>
</invoke>
```
Parameters: `filePath` (string, required), `oldString` (string, required), `newString` (string, required).

### glob
Find files by glob pattern.
```
<invoke name="glob">
<parameter name="pattern" string="true">**/*.js</parameter>
</invoke>
```
Parameters: `pattern` (string, required).

### grep
Search file contents by regex.
```
<invoke name="grep">
<parameter name="pattern" string="true">function\s+\w+</parameter>
<parameter name="include" string="true">*.js</parameter>
</invoke>
```
Parameters: `pattern` (string, required), `include` (string, optional).

### bash
Execute a shell command.
```
<invoke name="bash">
<parameter name="command" string="true">ls -la</parameter>
<parameter name="description" string="true">List files</parameter>
</invoke>
```
Parameters: `command` (string, required), `description` (string, required), `timeout` (int, optional).

## Strict rules

- Never use GitHub tools (PR, issue, actions, search).
- Never use web tools (webfetch, websearch).
- Never install dependencies or run network commands.
- Read a file before editing it.