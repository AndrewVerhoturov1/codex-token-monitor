# Zworker Prompt

**Request ID:** ZWORKER-20260628-030151-html-carcassonne

## Read first

- Zworker manual: https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md
- Repo navigation: https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md

## Task

Сделать HTML-версию игры Carcassonne для этого репозитория. Внешний агент сам ищет в интернете правила, механику и подходящие открытые референсы. Результат должен быть пригоден для локального запуска в текущем проекте без установки зависимостей.

## Context from Codex/OpenCode

Проект — статический vanilla HTML/CSS/JS фронтенд, который раздается Python-сервером на http://127.0.0.1:8765. В репозитории уже есть папка static/codex-token-monitor/carcassonne/ с существующим прототипом; ее нужно использовать как базовую целевую директорию и аккуратно заменить или улучшить текущую реализацию, а не создавать отдельный стек. Нужен самодостаточный браузерный прототип с игровым полем, колодой/мешком тайлов, размещением тайлов по правилам совместимости сторон, базовым начислением очков, управлением ходом и играбельным UI. Допустим упрощенный scope, если full rules слишком велики, но в таком случае нужно явно зафиксировать, что именно реализовано и что опущено.

## Files to read

- https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/README.md
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/scripts/codex_token_monitor_server.py
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/static/codex-token-monitor/index.html
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/static/codex-token-monitor/carcassonne/index.html
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/static/codex-token-monitor/carcassonne/app.js
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/static/codex-token-monitor/carcassonne/game.js
https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/static/codex-token-monitor/carcassonne/styles.css

## Result

Return a ZIP archive.
The ZIP must contain `answer.md` at the root.
Add any other files you think are useful for completing the task.
Write `answer.md` in clear Russian unless the task says otherwise.

## If something is missing

Ask for the exact file, command output, or clarification.
Do not invent local git/test/runtime state.
