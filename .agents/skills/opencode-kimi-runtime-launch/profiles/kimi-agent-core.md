# Kimi agent core rules

## Tool call format

All tool invocations must be valid JSON in the tool_calls block.

No prose instead of tool call. If a tool is needed, call it directly.

## No inventing tool results

Do not simulate or fabricate tool outputs.
If a tool returns an error or empty result, report it as-is.

## Stop rules

- Stop immediately if the task scope exceeds the bounded brief.
- Stop if asked to modify permanent opencode.jsonc.
- Stop if asked to run install/network/server/watch commands.
- Stop if asked to use Git/GitHub write actions.
- Stop if asked to read secrets or .env files.