# /zworker Invocation

`/zworker` is a conditional Codex route for sending a task to an external
worker. It is not direct task execution by Codex itself.

When the user explicitly invokes `/zworker`, Codex may use OpenCode to gather
the minimum repository context, then prepares a short `prompt.md` for the
external chat.

The external chat returns a ZIP with `answer.md` at the root. If the task also
needs files, they are returned in the same ZIP at repo-relative paths.

After that, Codex/OpenCode safely unpacks the ZIP into a temporary folder,
reads `answer.md` first, reviews any extra files, and decides whether the
result is ready to accept, needs revision, or needs clarification.
