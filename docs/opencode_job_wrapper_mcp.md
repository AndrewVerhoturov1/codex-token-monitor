# OpenCode Job-Wrapper MCP

## Что это

Это отдельный маленький MCP-сервер поверх уже существующего file-based job-wrapper:

- [scripts/codex_token_monitor_opencode_jobs.py](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/scripts/codex_token_monitor_opencode_jobs.py>)
- [scripts/codex_token_monitor_opencode_adapter.py](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/scripts/codex_token_monitor_opencode_adapter.py>)
- [scripts/codex_token_monitor_opencode_jobs_mcp.py](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/scripts/codex_token_monitor_opencode_jobs_mcp.py>)

Он не заменяет существующий `mcp__opencode.*`. Он добавляет отдельный сервер `opencode_jobs` с одним tool:

- `opencode_job_run_and_wait`

## Зачем он нужен

Новый MCP нужен для обычного пути ожидания OpenCode-задачи одним вызовом:

```text
Codex
  -> mcp__opencode_jobs.opencode_job_run_and_wait
  -> file-based job-wrapper
  -> adapter/OpenCode
  -> result.md + done.json
  -> короткий summary и пути обратно
```

Это убирает дорогой цикл:

```text
opencode_run -> check -> wait -> conversation -> readback
```

## Что он возвращает

Tool возвращает компактный JSON:

- `job_id`
- `status`
- `reason`
- `summary`
- `duration_ms`
- `timed_out`
- `result_path`
- `done_path`
- `stdout_path`
- `stderr_path`
- `launch_path`
- `debug_visible_terminal_requested`
- `debug_visible_terminal_status`
- `debug_visible_terminal_reason`
- `debug_visible_terminal_pid`
- `debug_open_session_tui_requested`
- `debug_open_session_tui_status`
- `debug_open_session_tui_reason`
- `debug_session_id`
- `debug_tui_command`
- `debug_attach_url`

Полный `result.md` в ответ не тащится. Возвращается только короткий `summary` и пути к файлам.

## Как подключить в Codex

`opencode_jobs` подключается как отдельный MCP-сервер. Он не заменяет
существующий `mcp__opencode.*`, а добавляется рядом с ним.

Для постоянной доступности во всех сессиях Codex этот сервер лучше держать в
глобальном пользовательском конфиге:

- [config.toml](C:\Users\andre\.codex\config.toml)
- [scripts/install_opencode_jobs_mcp.py](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/scripts/install_opencode_jobs_mcp.py>)

Ниже пример для user-level MCP-конфига Codex на Windows.
Точный верхнеуровневый формат пользовательского файла конфигурации может
отличаться, но для нового сервера должны сохраниться эти поля:

- `server name`: `opencode_jobs`
- `command`: `python`
- `args`: `["scripts/start_opencode_jobs_mcp.py"]`
- `cwd`: `D:\Codex+opencode_new\Proect_C_O\codex-token-monitor`
- `startup_timeout_sec`: `30`
- `tool_timeout_sec`: `900`

Пример фрагмента:

```json
{
  "mcpServers": {
    "opencode_jobs": {
      "command": "python",
      "args": [
        "scripts/start_opencode_jobs_mcp.py"
      ],
      "cwd": "D:\\Codex+opencode_new\\Proect_C_O\\codex-token-monitor",
      "startup_timeout_sec": 30,
      "tool_timeout_sec": 900
    }
  }
}
```

Если реальный пользовательский MCP-конфиг Codex использует другую внешнюю
обёртку или другой корневой объект, вставлять нужно именно блок сервера
`opencode_jobs` с этими значениями `command` / `args` / `cwd`.

Если `python` не доступен в `PATH`, используйте свой стандартный Python
launcher для Windows, но не добавляйте в конфиг секреты, токены или
автозапуск OpenCode-задач.

Самый безопасный путь подключения теперь такой:

```powershell
python scripts/install_opencode_jobs_mcp.py
```

Что делает installer:

- добавляет или обновляет блок `[mcp_servers.opencode_jobs]` в пользовательском `config.toml`;
- переводит старый `python -m scripts.codex_token_monitor_opencode_jobs_mcp` на `python scripts/start_opencode_jobs_mcp.py`;
- делает backup существующего `config.toml` перед перезаписью блока;
- печатает, нужен ли перезапуск Codex.

После любого изменения `config.toml` нужно один раз полностью перезапустить Codex, потому что текущая сессия не подхватывает новый MCP-маршрут на лету.

Важно для новых чатов Codex: `opencode_jobs` может быть deferred tool.
Это означает, что в начале новой сессии `mcp__opencode_jobs.opencode_job_run_and_wait`
иногда ещё не виден как callable tool, хотя сервер уже корректно подключён.

Практическое правило для smoke и обычной работы:

1. если tool уже callable, используйте его сразу;
2. если tool не виден, сделайте ровно один `tool_search` по `opencode_job_run_and_wait` или `opencode_jobs`;
3. если `tool_search` вернул tool, используйте его и не считайте это ошибкой маршрута;
4. только если после этого tool всё равно не найден, считайте маршрут недоступным в текущей сессии.

Стартовать нужно именно через [scripts/start_opencode_jobs_mcp.py](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/scripts/start_opencode_jobs_mcp.py>),
а не напрямую через `python -m scripts.codex_token_monitor_opencode_jobs_mcp`.
Этот стартёр перед запуском свежего MCP:

- находит старые процессы `opencode_jobs` по точным маркерам командной строки;
- не трогает `mcp__opencode.*`, `opencode serve` и чужие Python-процессы;
- останавливает только старые процессы самого `opencode_jobs` MCP;
- пишет PID/state в `_local/codex-token-monitor/opencode-jobs-mcp.pid.json`;
- пишет startup audit в `_local/codex-token-monitor/opencode-jobs-mcp-startup.log`.

Это нужно, чтобы старые процессы `opencode_jobs` с устаревшим кодом не
оставались висеть и не обслуживали новые сессии Codex вместо свежего старта.

Дополнительная защита от старого конфига теперь есть и в самом legacy entrypoint:
если кто-то всё же запускает `python -m scripts.codex_token_monitor_opencode_jobs_mcp`,
он автоматически перепрыгивает в `scripts/start_opencode_jobs_mcp.py`, а не обходит стартёр.

`tool_timeout_sec` здесь увеличен специально: сам tool ждёт завершения
job-wrapper вне модельного цикла, поэтому стандартного короткого MCP timeout
для обычных OpenCode-задач недостаточно.

Хотя сервер настроен глобально и будет виден Codex во всех сессиях, его
внутренний `cwd` всё равно указывает на проект
[codex-token-monitor](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor>),
потому что именно там находится локальная реализация
`scripts.codex_token_monitor_opencode_jobs_mcp`.

После подключения у Codex должен появиться tool:

- `mcp__opencode_jobs.opencode_job_run_and_wait`

## Параметры tool

Обязательный параметр:

- `task_text`

Опциональные параметры:

- `directory`
- `timeout_seconds`
- `provider_id`
- `model_id`
- `debug_visible_terminal`
- `debug_open_session_tui`
- `opencode_attach_url`
- `config_path`

Если параметры не переданы, используются значения из [config/opencode_job_defaults.json](</D:/Codex+opencode_new/Proect_C_O/codex-token-monitor/config/opencode_job_defaults.json>).

`directory` прокидывается в существующий wrapper и дальше в OpenCode CLI как рабочая директория задачи.

Текущий project default для wrapper timeout:

```json
"timeout_seconds": 720
```

## Debug visible terminal mode

Для ручной диагностики можно включить отдельный видимый Windows terminal launch, не меняя обычный silent flow по умолчанию.

По умолчанию:

```json
"debug_visible_terminal": true
```

```json
"debug_open_session_tui": false,
"opencode_attach_url": ""
```

Текущие project defaults для wrapper:

```json
"provider_id": "opencode",
"model_id": "deepseek-v4-flash-free"
```

Для Windows можно явно задать shim OpenCode:

```json
"opencode_command": "C:\\Users\\andre\\AppData\\Roaming\\npm\\opencode.cmd"
```

Для MCP-маршрута `opencode_jobs` visible debug mode теперь включён по умолчанию.
Явное управление по-прежнему возможно двумя путями:

- через `config_path`, где задано `"debug_visible_terminal": true`;
- через MCP-вызов `opencode_job_run_and_wait(..., debug_visible_terminal=true)`.

Что происходит в этом режиме:

- wrapper всё так же ждёт файловый протокол `result.md -> done.json`;
- adapter запускается в отдельном видимом окне Windows console;
- вывод OpenCode стримится в окно и одновременно пишется в `stdout.log` / `stderr.log`;
- adapter передаёт сам task в OpenCode как attachment через `--file`, а рабочую папку задаёт через `--dir`;
- в job directory создаются:
  - `opencode_input.md`
  - `opencode_manual_command.txt`
  - `opencode_launch.json`
  - bootstrap `stdout.log` / `stderr.log` даже если adapter не дошёл до нормального старта

Это даёт пользователю точную команду и входной payload для ручного воспроизведения, даже если job завершился timeout.
Также в `opencode_launch.json` теперь пишутся `opencode_resolved_command`, `opencode_found_by`, `PATH`, `cwd`, `working_directory`, `provider_id` и `model_id`.
Если adapter завис до bootstrap, wrapper теперь завершает такой job раньше с диагностикой `adapter_bootstrap_timeout` или `adapter_exited_without_bootstrap`, не оставляя пустой silent-timeout без артефактов.

## Debug open session TUI mode

Для отдельной диагностики live-session теперь есть второй независимый debug-режим:

```json
"debug_open_session_tui": true
```

Он не заменяет `debug_visible_terminal`, а дополняет его:

- `debug_visible_terminal` показывает живой stdout/stderr потока `opencode run`;
- `debug_open_session_tui` пытается открыть отдельное окно OpenCode TUI/attach именно для session этого job-а.

Что делает adapter в этом режиме:

- добавляет `--title codex-job-<job_id>` в `opencode run`;
- после старта коротко опрашивает `opencode session list --format json`;
- ищет session по `title` и `directory`;
- если session найдена, пытается открыть отдельное окно через `wt.exe` или fallback на `powershell.exe -NoExit`;
- для открытия TUI используется штатное открытие найденной session без дополнительных replay-флагов, потому что текущий CLI не поддерживает эти флаги на маршруте `opencode attach` / `opencode <project> --session ...`;
- если session не найдена или окно не открылось, основной job не считается failed только из-за этого.

Если нужно использовать общий OpenCode server/attach backend, можно отдельно задать:

```json
"opencode_attach_url": "http://localhost:4096"
```

Тогда:

- `opencode run` получает `--attach http://localhost:4096`;
- команда открытия TUI строится через `opencode attach ... --session <session_id> --dir <repo>`.

В `opencode_launch.json` дополнительно пишутся:

- `opencode_run_title`
- `session_lookup_attempted`
- `session_lookup_status`
- `session_lookup_error`
- `session_id_found`
- `session_id`
- `tui_open_attempted`
- `tui_open_status`
- `tui_open_command`
- `tui_open_error`
- `attach_url`

Новый MCP-ответ теперь явно отделяет успешность самого job от успешности debug-ветки видимости:

- `debug_visible_terminal_status=adapter_started_not_confirmed` означает, что wrapper запустил adapter в visible режиме, но сам факт видимости окна не подтверждается машинно;
- `debug_open_session_tui_status=launched_not_confirmed` означает, что wrapper нашёл session и выполнил запуск TUI/attach окна, но не может доказать, что пользователь его увидел;
- `session_not_found`, `lookup_failed` и `launch_failed` больше не теряются молча и возвращаются прямо в MCP-ответе.

## Когда использовать этот MCP

Используйте `opencode_jobs` для обычных OpenCode repository/workspace задач, где нужен один запуск и одно ожидание результата.

Оставляйте прямой `mcp__opencode.*` для:

- диагностики repo-контекста;
- проверки session/permission/debug состояния;
- fallback-пути после сбоя job-wrapper;
- задач, где реально нужен прямой контроль OpenCode-сессии.

Не меняйте существующий `mcp__opencode.*`. Новый сервер должен жить отдельно
под именем `opencode_jobs`.

## Smoke-test

Минимальная проверка:

1. Подключить MCP-сервер `opencode_jobs`.
2. Вызвать `opencode_job_run_and_wait` с коротким `task_text`.
3. Убедиться, что MCP-ответ короткий и содержит `summary` плюс пути.
4. Убедиться, что на диске появились `result.md` и `done.json`.
5. Проверить, что `result.md` записан раньше `done.json`.

Для локального fake-worker smoke можно передать свой `config_path` с тестовым `command_template`, не меняя основной конфиг проекта.
