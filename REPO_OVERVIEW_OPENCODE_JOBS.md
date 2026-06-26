# Обзор репозитория: codex-token-monitor (OpenCode Jobs)

## Назначение проекта

Мониторинг и аудит использования токенов Codex-агента. Сервер отслеживает расход токенов в реальном времени (live-чаты), ведёт историю по архивным сессиям (из OTel-дампов) и рассчитывает стоимость на основе заданных тарифов. Дополнительно содержит инфраструктуру "OpenCode jobs" — file-based обёртку для запуска задач OpenCode вне основного цикла модели, с MCP-сервером.

## Основная архитектура

Проект — Python-монолит (HTTP-сервер на `http.server.ThreadingHTTPServer`). Состоит из:

- **HTTP-сервер/дашборд** (`scripts/codex_token_monitor_server.py`) — раздаёт статику (HTML/JS/CSS) + JSON API (`/api/sources`, `/api/sessions`, `/api/session`, `/api/audit`, `/api/raw-export` и др.)
- **Механизм сбора данных** — live (читает `state_5.sqlite`, `session_index.jsonl`, `rollout-*.jsonl` из `~/.codex`) и archive (читает `token_cost_dashboard_data.json` из `token-cost-normalized/` внутри дампов сессий)
- **OpenCode jobs** — file-based job-wrapper: `codex_token_monitor_opencode_jobs.py` + адаптер `codex_token_monitor_opencode_adapter.py` + MCP-сервер `codex_token_monitor_opencode_jobs_mcp.py` + стартер `start_opencode_jobs_mcp.py`
- **Аудит** (`scripts/codex_token_monitor_audit.py`) — проверяет корректность данных о сессиях
- **Конфигурация** в `config/`

## Главные папки и файлы

| Путь | Назначение |
|------|-----------|
| `scripts/codex_token_monitor_server.py` | Основной HTTP-сервер (4406 стр.) |
| `scripts/codex_token_monitor_opencode_jobs.py` | Job-wrapper: запуск, ожидание, очистка |
| `scripts/codex_token_monitor_opencode_adapter.py` | Адаптер между job-wrapper и OpenCode CLI |
| `scripts/codex_token_monitor_opencode_jobs_mcp.py` | MCP-сервер поверх job-wrapper |
| `scripts/codex_token_monitor_adapter.py` | (путь .py — отсутствует, есть .py в config) |
| `scripts/codex_token_monitor_audit.py` | Модуль аудита данных сессий |
| `scripts/install_opencode_jobs_mcp.py` | Установка MCP-блока в `~/.codex/config.toml` |
| `scripts/start_opencode_jobs_mcp.py` | Стартер MCP-сервера с очисткой старых процессов |
| `config/codex_token_monitor_projects.json` | Конфигурация источников (live/archive) |
| `config/token_pricing.json` | Цены на токены по моделям |
| `config/opencode_job_defaults.json` | Дефолты для job-wrapper |
| `static/codex-token-monitor/` | Веб-интерфейс: HTML, CSS, JS |
| `tests/` | Модульные тесты (unittest) |
| `_local/codex-token-monitor/opencode-jobs/` | Артефакты job-запусков (временные) |
| `docs/` | Документация по MCP и job-wrapper |

## Как работает мониторинг токенов

1. **Live-источник**: читает `state_5.sqlite` (таблица `threads`) для списка чатов, `session_index.jsonl` для названий, `rollout-*.jsonl` для per-step токенов и событий. Цены считаются через `config/token_pricing.json`. Если rollout нет — fallback через `logs_2.sqlite`.
2. **Archive-источник**: читает дампы из папок вида `<project>/_local/codex-token-debugger/<session_id>/token-cost-normalized/token_cost_dashboard_data.json`.
3. **Стоимость**: `estimated_total_cost_usd` = (non_cached_tokens * input_price + cached_tokens * cached_input_price + output_tokens * output_price) / 1_000_000.
4. **Raw-экспорт**: упаковывает исходные rollout JSONL в ZIP с манифестом.

## Как устроен веб-сервер/дашборд

- Класс `MonitorHandler(SimpleHTTPRequestHandler)` обслуживает все запросы.
- REST JSON API: `/api/sources`, `/api/sessions`, `/api/session`, `/api/status`, `/api/audit`, `/api/raw-export`, `/api/archive`, `/api/unarchive`, `/api/shutdown`.
- Статика: `static/codex-token-monitor/` (index.html, app.js ~3200 строк, styles.css).
- Фронтенд: одностраничное приложение на чистом JS со списком сессий, детальным просмотром шагов, фильтрацией, поиском, auto-refresh, аудитом.
- Порт по умолчанию: 8765. Запуск: `python scripts/codex_token_monitor_server.py --host 127.0.0.1 --port 8765 --open-browser`.

## Как устроен `opencode_jobs` route

Не HTTP-route, а **MCP-сервер** с одним tool `opencode_job_run_and_wait`.

**Цепочка вызова:**
1. Codex → `mcp__opencode_jobs.opencode_job_run_and_wait`
2. MCP-сервер (`codex_token_monitor_opencode_jobs_mcp.py`) → job-wrapper (`codex_token_monitor_opencode_jobs.py`)
3. Job-wrapper → адаптер (`codex_token_monitor_opencode_adapter.py`) → `opencode run ...`
4. После завершения: `result.md` + `done.json` → короткий summary

**Протокол:** адаптер дописывает в task.md инструкцию записать `result.md` и `done.json` атомарно. Job-wrapper ждёт эти файлы с таймаутом.

**Параметры tool:** `task_text`, `directory`, `timeout_seconds`, `provider_id`, `model_id`, `debug_visible_terminal`, `debug_open_session_tui`, `opencode_attach_url`, `export_session`, `config_path`.

**Жизненный цикл job:**
- UUID job_id → создаётся директория `<jobs_dir>/<uuid>/`
- `task.md` → `opencode_input.md` (с протоколом) → адаптер запускает OpenCode
- Ожидание `result.md` + `done.json` (polling, до `timeout_seconds`)
- Очистка старых job по retention (success: 7 дней, failure: 30 дней, keep recent: 20)

## Какие есть конфиги

| Файл | Формат | Назначение |
|------|--------|-----------|
| `config/codex_token_monitor_projects.json` | JSON v2 | Источники данных (live/archive) |
| `config/token_pricing.json` | JSON | Цены на токены ($/1M токенов) |
| `config/opencode_job_defaults.json` | JSON | Настройки job-wrapper (таймауты, шаблоны команд, retention) |
| `config.json` | JSON | Провайдеры и модели Codex (Ollama) |
| `opencode.json` | JSON | Провайдер Codex (локальный Ollama) |

## Какие есть тесты

Все тесты — `unittest.TestCase` в `tests/`:
- `test_opencode_jobs.py` (928 стр.) — job-wrapper: запуск, таймауты, очистка, протокол
- `test_opencode_adapter.py` (324 стр.) — адаптер: экспорт, поиск сессий, команды
- `test_opencode_jobs_mcp.py` (362 стр.) — MCP-сервер: вызов tool, конфигурация
- `test_raw_export.py` (340 стр.) — raw-экспорт: итератор, манифест, ZIP
- `test_install_opencode_jobs_mcp.py` (103 стр.) — установка MCP-блока в config.toml
- `test_start_opencode_jobs_mcp.py` (312 стр.) — стартер: поиск процессов, очистка

Запуск: `python -m pytest tests/` или `python -m unittest discover tests/`.

## Какие есть вспомогательные скрипты

- `scripts/install_opencode_jobs_mcp.py` — добавляет блок `[mcp_servers.opencode_jobs]` в `~/.codex/config.toml`
- `scripts/start_opencode_jobs_mcp.py` — стартер: убивает старые MCP-процессы, запускает новый, пишет PID
- `start_codex_token_monitor.bat` — убивает старые процессы на порту 8765, запускает сервер
- `win-opencode-launch.ps1` — PowerShell-лаунчер для OpenCode на Windows
- `win opencode.bat` — bat-лаунчер

## Где лежат временные/job-артефакты

`_local/codex-token-monitor/opencode-jobs/<uuid>/`:
- `task.md` — исходная задача
- `opencode_input.md` — задача + протокол (что подаётся OpenCode)
- `opencode_manual_command.txt` — PowerShell-команда для ручного запуска
- `opencode_launch.json` — метаданные запуска (PID, команда, статус сессии)
- `result.md` — результат выполнения
- `done.json` — статус завершения
- `stdout.log` / `stderr.log` — логи
- `adapter_bootstrap_stdout.log` / `adapter_bootstrap_stderr.log` — логи начальной фазы адаптера
- `opencode_session_export.json` / `opencode_session_transcript.md` — экспорт сессии (если запрошен)

Дополнительно: `_local/codex-token-monitor/opencode-jobs-mcp.pid.json` — PID текущего MCP-сервера.

## Что важно не сломать

1. **Протокол атомарной записи**: `result.md.tmp` → `result.md`, затем `done.json.tmp` → `done.json`. Порядок критичен.
2. **Адаптер ждёт, пока OpenCode не запишет done.json**. После этого экспортирует сессию.
3. **Стартер MCP убивает старые legacy MCP-процессы** перед запуском нового.
4. **Очистка job** удаляет только те, чей возраст превышает retention + keep_recent.
5. **Проверка путей**: rollout-файлы проверяются на валидность (`is_relative_to`).
6. **Live vs Archive**: разная логика источников — live читает SQLite/JSONL, archive — нормализованные JSON.
7. **Цены**: отсутствие модели в `token_pricing.json` → стоимость не считается (None).

## Как быстро войти в проект новому агенту

1. Прочитать `README.md` и данный обзор.
2. Изучить `scripts/codex_token_monitor_server.py` — основная точка входа, понять REST API.
3. Изучить `scripts/codex_token_monitor_opencode_jobs.py` — job-wrapper: `run_opencode_job()`.
4. Изучить `scripts/codex_token_monitor_opencode_adapter.py` — как адаптер готовит задачу и запускает OpenCode.
5. Посмотреть `tests/test_opencode_jobs.py` — тесты раскрывают жизненный цикл job-запуска.
6. Конфиги: `config/opencode_job_defaults.json` (дефолты), `config/codex_token_monitor_projects.json` (источники).
7. MCP-уровень: `scripts/codex_token_monitor_opencode_jobs_mcp.py` — тонкая обёртка над job-wrapper.
8. Для отладки job: `opencode_launch.json` в job-директории содержит полную диагностику.
