# Zchat v1: что создано

## Назначение

Zchat v1 — четыре режима для структурированной упаковки задач (prompt pack),
импорта (import pack), верификации (verify pack) и принятия решения Codex
(decision pack) внутри репозитория codex-token-monitor.

## Режимы и точки входа

Все четыре режима реализованы в `scripts/codex_token_monitor_opencode_jobs.py` (функции
`zchat_prompt_pack`, `zchat_import_pack`, `zchat_verify_pack`, `zchat_decision_pack`).

| Режим | Функция | CLI-флаг | MCP-tool |
|---|---|---|---|
| prompt_pack | `zchat_prompt_pack()` | `--zchat-prompt-pack` | `opencode_zchat_prompt_pack` |
| import_pack | `zchat_import_pack()` | `--zchat-import-pack <zip>` | `opencode_zchat_import_pack` |
| verify_pack | `zchat_verify_pack()` | `--zchat-verify-pack <dir>` | `opencode_zchat_verify_pack` |
| decision_pack | `zchat_decision_pack()` | `--zchat-decision-pack --zchat-subject-id --zchat-decision-verdict` | `opencode_zchat_decision_pack` |

MCP-обёртка: `scripts/codex_token_monitor_opencode_jobs_mcp.py`, сервер `opencode_jobs`.

CLI-маршрут: `scripts/codex_token_monitor_opencode_jobs.py` (аргументы выше).

## Runtime-каталоги

Все runtime-артефакты пишутся в `.ai/zchat/runtime/`. Каждый артефакт получает
ZCHAT-slug ID (`ZCHAT-YYYYMMDD-HHMMSS-<hex8>`), сгенерированный
`scripts/git_utils.zchat_slug_id()`.

```
.ai/zchat/runtime/
  requests/<slug>/      — prompt.md, prompt_passport.md, request_manifest.json
  imports/<slug>/       — import_report_<uuid12>.md
  reviews/<slug>/       — verify_report_<uuid12>.md | codex_decision.md + decision_manifest.json (при needs_revision)
  accepted/<slug>/      — codex_decision.md + decision_manifest.json
  rejected/<slug>/      — codex_decision.md + decision_manifest.json
  branches/<slug>/      — branch metadata (зарезервировано)
```

## Контракты и артефакты

### Шаблоны (`.ai/zchat/templates/`)

- `prompt.md` — шаблон промпта с плейсхолдерами `{task}`, `{context}`, `{constraints}`
- `prompt_passport.md` — паспорт промпта: resolved_sources, branch_decision, artifacts
- `request_manifest.json` — каркас манифеста с policy-полями

### Схемы (`.ai/zchat/schemas/`)

- `import_manifest_schema.json` — JSON Schema draft-07 для валидации manifest.json при import_pack

### Skills (`.ai/zchat/skills/`)

- `intake_rules.md` — OpenCode skill: фиксированная последовательность VALIDATE → SECURITY_SCAN → EXTRACT_APPLY → VERIFY_INPUTS → REPORT

### Документация (`.ai/zchat/docs/`)

- `zchat_intake_contract.md` — полный контракт ZIP intake (5 шагов fail-fast preflight)
- `zchat_v1_created.md` — настоящий документ

### Вспомогательный код

- `scripts/git_utils.py` — `zchat_slug_id()`, `zchat_slug_id_is_valid()`, `resolve_branch_decision()`, `create_temp_branch()`, `push_temp_branch()`, `delete_temp_branch()`, `branch_metadata_to_passport()`

### Тесты (`tests/test_zchat.py`)

- `ZchatPromptPackTests` (5 тестов)
- `ZchatImportPackTests` (14 тестов)
- `ZchatVerifyPackTests` (6 тестов)
- `ZchatForbiddenPathTests` (5 тестов)
- `ZchatSlugIdTests` (4 теста)
- `ZchatDecisionPackTests` (7 тестов)
- `ZchatStructuredRuntimeTests` (4 теста)
- `ZchatBranchPolicyTests` (4 теста)

Всего ~49 тестов.

## Поток prompt → zip intake → verify → codex decision

```
Codex
  │
  ├─ 1. zchat_prompt_pack
  │     Создаёт prompt.md + prompt_passport.md + request_manifest.json
  │     в runtime/requests/<slug>/
  │     source_policy: public_github_raw_first
  │     branch_policy: temporary_branch_only_if_public_insufficient
  │
  ├─ 2. zchat_import_pack  (ZIP intake)
  │     Валидирует ZIP: manifest.json + checksums.sha256 + payload/
  │     Security scan: запрет traversal, .git/, .env*, .ai/zchat/, absolute paths
  │     Извлекает payload/ в рабочее дерево
  │     Пишет import_report.md в runtime/imports/<slug>/
  │     Вердикты: accepted_for_review | rejected_structural | rejected_scope | needs_codex_decision
  │
  ├─ 3. zchat_verify_pack
  │     Проверяет директорию pack: manifest + checksums + payload на консистентность
  │     Пишет verify_report.md в runtime/reviews/<slug>/
  │     Те же 4 вердикта
  │
  └─ 4. zchat_decision_pack
        Принимает финальное решение Codex
        Пишет codex_decision.md + decision_manifest.json
        accepted → runtime/accepted/<slug>/
        rejected → runtime/rejected/<slug>/
        needs_revision → runtime/reviews/<slug>/
```

Каждый шаг автономен: может вызываться отдельно через CLI или MCP.

## Политика временной ветки

Реализована в `scripts/git_utils.resolve_branch_decision()`:

- Если переданы `source_urls` (публичные GitHub raw URLs) → `no_branch_needed`, ветка НЕ создаётся.
- Если source_urls нет и публичный контекст недоступен → `branch_may_be_needed`, но create_branch всегда `False` в v1.

Вспомогательные функции `create_temp_branch()` / `push_temp_branch()` / `delete_temp_branch()`
существуют в `git_utils.py`, но автоматическое создание ветки в v1 **не активировано**:
паспорт промпта всегда пишет «temporary branch is NOT required».

## Что НЕ входит в v1

- Автоматическое создание временной ветки (create_branch всегда `False`)
- Интерактивный human review (verify_pack — машинный вердикт)
- Постоянное хранилище вне runtime (runtime-директории gitignored)
- Дедупликация по содержимому между сессиями
- Шифрование payload в ZIP
- Поддержка нескольких репозиториев
- Миграция данных между версиями runtime
