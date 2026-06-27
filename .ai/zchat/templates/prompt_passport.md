# Prompt Passport

- **Request Name**: {request_name}
- **Goal**: {task}
- **Prompt file**: `{prompt_path}`

## Canonical Docs

- **Static Manual**: {static_manual_url}
- **Repo Navigation**: {repo_navigation_url}

## Required Task Sources

{required_task_source_urls}

## Allowed Paths

{allowed_paths}

## Forbidden Paths

{forbidden_paths}

## Expected Outputs

{expected_outputs}

## Key Contract

- `zchat_result_type = package`
- `package_id = request name`
- `manifest/checksum paths are repo-relative without payload/`
- `physical ZIP entries use payload/{repo_relative_path}`

## Human Next Step

- give prompt.md to external chat
