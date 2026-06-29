# TASK_STATUS

COMPLETED

## Вывод коротко

- Подключить несколько Ollama-аккаунтов в OpenCode как разные `provider_id`: да.
- Вручную выбирать каждый профиль: да.
- Штатный автоматический fallback при квоте/429 между `ollama_acc_1` и `ollama_acc_2`: не найден.

## Что проверено

- Версия OpenCode: `1.17.10`.
- Постоянный глобальный конфиг OpenCode: `C:\Users\andre\.config\opencode\opencode.jsonc`.
- Хранилище credentials/auth: `C:\Users\andre\.local\share\opencode\auth.json`.
- Проектный конфиг репозитория: `D:\Codex+opencode_new\Proect_C_O\codex-token-monitor\opencode.json`.
- Временный тест выполнен без изменения постоянного `opencode.jsonc`.
- Для теста использовался временный конфиг через `OPENCODE_CONFIG` с двумя custom provider:
  - `ollama_acc_1`
  - `ollama_acc_2`
- После завершения теста:
  - временные credentials `ollama_acc_1` и `ollama_acc_2` удалены через `opencode providers logout`;
  - временный конфиг и тестовая папка удалены.

## Результаты тестов

| provider_id | model_id | endpoint | ключ | результат | ошибка |
| --- | --- | --- | --- | --- | --- |
| `ollama_acc_1` | `minimax-m2.5:cloud` | `https://ollama.com/v1` | `****594P` | `OK_ACC_1` | нет |
| `ollama_acc_2` | `minimax-m2.5:cloud` | `https://ollama.com/v1` | `****zU-4` | `OK_ACC_2` | нет |

Дополнительно подтверждено:

- `opencode models ollama_acc_1` показал отдельные модели:
  - `ollama_acc_1/devstral-2:123b-cloud`
  - `ollama_acc_1/gemma4:31b-cloud`
  - `ollama_acc_1/glm-4.7:cloud`
  - `ollama_acc_1/minimax-m2.5:cloud`
- `opencode models ollama_acc_2` показал отдельные модели:
  - `ollama_acc_2/devstral-2:123b-cloud`
  - `ollama_acc_2/gemma4:31b-cloud`
  - `ollama_acc_2/glm-4.7:cloud`
  - `ollama_acc_2/minimax-m2.5:cloud`

Это доказывает, что OpenCode видит их как разные provider/model-пути и позволяет вручную выбирать нужный профиль.

## Совместимость

- Через `@ai-sdk/openai-compatible`: работает.
  - Подтверждено реальным запуском через `https://ollama.com/v1` и двумя разными `provider_id`.
- Через локальный Ollama `http://localhost:11434/v1`: поддерживается OpenCode официально, но в этом прогоне не перепроверялось, так как основной сценарий уже успешно доказан.
- Через прямой native Ollama Cloud API `https://ollama.com/api/chat`: у Ollama такой API есть, но для OpenCode в этой задаче он не потребовался, потому что OpenAI-compatible путь уже отработал успешно.
- Прокси-адаптер: не нужен для сценария ручного выбора двух профилей, если использовать custom providers OpenCode и endpoint `https://ollama.com/v1`.

## Ограничения

- В установленной версии OpenCode не обнаружена подтвержденная поддержка `OPENCODE_CONFIG_CONTENT`.
  - В этой проверке использовался `OPENCODE_CONFIG`, он сработал.
- Штатный автоматический fallback между двумя разными provider/model-профилями в текущей версии не подтвержден.
- Прямой тест выполнялся на одной модели `minimax-m2.5:cloud`.
  - Для доказательства схемы этого достаточно, потому что разделение по `provider_id` и разным ключам уже подтверждено реальным запуском.
- Внутри TUI-команда `/models` не кликалась вручную, но эквивалентная ручная селекция подтверждена через:
  - `opencode models <provider_id>`;
  - `opencode run --model provider/model`.

## Рекомендация

- Хранить 2+ Ollama-профиля как отдельные custom provider в OpenCode, например:
  - `ollama_acc_1`
  - `ollama_acc_2`
- Для ручного переключения использовать:
  - `/models` в TUI, где модели будут видны как `ollama_acc_1/...` и `ollama_acc_2/...`;
  - или CLI с явным `--model`, например `ollama_acc_1/minimax-m2.5:cloud`.
- Для временных безопасных проверок использовать `OPENCODE_CONFIG`, а не менять постоянный `opencode.jsonc`.
- Если нужен автоматический fallback по квоте/429, лучше рассчитывать на внешний роутер/прокси или отдельную доработку, а не на штатный механизм OpenCode.

## Источники

- [OpenCode Providers](https://opencode.ai/docs/providers/)
- [OpenCode Config](https://opencode.ai/docs/config/)
- [OpenCode CLI](https://opencode.ai/docs/cli/)
- [Ollama Cloud](https://docs.ollama.com/cloud)
- [Ollama Authentication](https://docs.ollama.com/api/authentication)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [OpenCode issue #7602: Native Model Fallback / Failover Support](https://github.com/anomalyco/opencode/issues/7602)
- [OpenCode issue #8673: fallback models for (sub) agents](https://github.com/anomalyco/opencode/issues/8673)
- [OpenCode issue #8687: Fallback models in configuration](https://github.com/anomalyco/opencode/issues/8687)
