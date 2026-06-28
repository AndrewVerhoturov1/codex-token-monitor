# Итог текущего чата: честный аудит AI-вызовов

В этом чате реализован call-level слой мониторинга AI-вызовов для live-сессий.  
Сервер теперь строит массив `ai_calls` из raw `last_token_usage` событий rollout JSONL,  
а UI показывает его как основную честную сводку над step-level блоками.

## Что сделано

- В сервере (`codex_token_monitor_server.py`) добавлен **call-level слой `ai_calls`**: функция `_build_session_ai_calls` собирает все `last_token_usage` чекпоинты в единый массив с явными полями `call_index`, `model`, `is_zero_usage`, `mapping_confidence`, `estimated_cost`.
- **Zero-usage события** учитываются отдельно: `is_zero_usage=True`, `ai_calls_zero_usage_count` в ответе API.
- Добавлены **additive-поля** в ответ сервера: `ai_calls`, `ai_calls_honest_audit_summary` (сводка: total, with_usage, zero, unmapped, cost, usage buckets).
- Добавлены **honesty warnings** в summary сервера: `call_vs_cumulative_cost_mismatch`, `positive_unmapped_or_internal_usage`, `reported_by_agent_items`.
- В UI (`app.js`) добавлен **блок AI Calls** как основная честная сводка — функция `renderAiCallsSectionIntoSteps` размещает блок над step-level содержимым.
- **Исправлена проблема дублирующих `renderHeader`/`renderSteps`**: код обёрнут через `const oldRenderHeader = renderHeader` / `const oldRenderSteps = renderSteps` с вызовом оригиналов, что устранило задвоение и AI Calls теперь отображается корректно.
- **Обновлён cache-buster** в `index.html`: styles.css `v=0063`, app.js `v=0078`.
- **Обновлён `start_codex_token_monitor.bat`**: добавлено убийство старого процесса на порту 8765 через `netstat` + `taskkill` перед запуском; понятный вывод статусов.
- **Расширены профильные тесты** в `tests/test_raw_export.py`: добавлены классы `CallLevelEventsTest`, `CallLevelAuditTests`, `HonestyWarningsTests`. Тесты локально проходили командой `python -m unittest tests.test_raw_export`.

## Что осталось

- **Довести экспорт Markdown/JSON**, чтобы primary truth везде был `ai_calls`, а не шаги.
- **Добавить отдельную compact fixture** в `tests/fixtures` для тестирования call-level слоя без развёртывания полного rollout.
- **Синхронизировать `scripts/codex_token_monitor_audit.py`** с новой truth model (сейчас аудит всё ещё смотрит в step-level, не в ai_calls).
- **Дожать UI-подписи и финальную подачу honest audit**: перевести подписи на русский, поправить форматирование, унифицировать стиль.
- **Усилить покрытие тестами** экспортного слоя (Markdown/JSON) и warning-сценариев (особенно fallback-путь через logs_2.sqlite).
