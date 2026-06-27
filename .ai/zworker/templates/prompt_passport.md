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

## Temporary Context Branch

{temp_branch_info}

## Key Contract

- `strict_zip_contract = false`
- `zip_layout = root_repo_paths`
- `answer.md` required at ZIP root
- No manifest.json, no checksums.sha256, no payload/
- Repo files at repo-relative paths in ZIP root

## Human Next Step

- give prompt.md to external agent
