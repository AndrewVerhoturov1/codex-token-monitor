# Шаблон запроса внешнему Zworker

Замените значения в угловых скобках. Не оставляйте неоднозначные placeholders в финальном prompt.

```markdown
# Zworker Prompt

**Request ID:** <ZWORKER-YYYYMMDD-HHMMSS-slug>

## Read first

- Zworker manual: https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md
- Repo navigation: https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md

## Task

<Одна конкретная задача. Укажите, что именно должно быть создано, изменено или проанализировано.>

## Context from Codex/OpenCode

<Только проверенные факты и необходимые интеграционные ограничения.>
<Не утверждайте локальный git/test/runtime state без фактической проверки.>

## Files to read

- <Публичный raw URL или точное содержимое файла>
- <Добавьте только реально необходимые файлы>

## Result

Return a ZIP archive.
The ZIP must contain `answer.md` at the root.
<Перечислите точные требуемые repo-relative paths.>
Write `answer.md` in clear Russian unless the task says otherwise.

## Acceptance criteria

- <Проверяемый критерий 1>
- <Проверяемый критерий 2>
- <Запрет на известную неудачную форму результата, если это revision>

## If something is missing

Ask for the exact file, command output, or clarification.
Do not invent local git/test/runtime state.

---

# AUTOMATION ZIP MARKING CONTRACT

You must create and attach a real downloadable ZIP file.

ZIP filename must be exactly:
<REQUEST_ID>-zworker-result.zip

ZIP requirements:
- answer.md must be at the ZIP root.
- Any created or modified repo files must be inside the ZIP using repo-relative paths.
- Do not use payload/.
- Do not include manifest.json unless the task explicitly asks.
- Do not include absolute paths.
- Do not include paths with .. traversal.
- Do not include files outside allowed_paths.
- Do not include files inside forbidden_paths.
- If images, HTML, scripts, docs, or code are part of the result, include them in the ZIP.

When the ZIP is attached, write this exact block in the same final assistant message:

ZWORKER_ZIP_MANIFEST_BEGIN
request_id: <REQUEST_ID>
zip_filename: <REQUEST_ID>-zworker-result.zip
zip_kind: zworker_result
required_root_file: answer.md
ZWORKER_ZIP_MANIFEST_END

Then write exactly one final line:
ZWORKER_ZIP_READY

Do not write anything after ZWORKER_ZIP_READY.

If you cannot attach the ZIP, write:
ZWORKER_ZIP_FAILED: <short reason>
```

## Правила заполнения

- Для нового запроса используйте новый UTC timestamp и lowercase slug.
- Для ревизии сохраняйте исходное имя и добавляйте `-ver2`, `-ver3` и далее.
- Указывайте `allowed_paths` и `forbidden_paths`, когда scope ограничен.
- Для изменения существующих файлов давайте их опубликованные raw URL.
- Не просите «интегрировать по аналогии» без исходного кода.
- Не включайте локальные секреты, токены и приватные данные.
