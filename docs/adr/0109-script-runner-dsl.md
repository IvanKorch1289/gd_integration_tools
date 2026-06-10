# ADR-0109: Script Runner DSL для inline Python/Node/Ruby/Shell

## Статус

Accepted

## Контекст

Анализ Jupyter DSL + RPA фич (2026-06-08) выделил **Script Runner DSL** как gap:
платформа имела `ShellExecProcessor` для внешних команд, но не предоставляла
удобного DSL для выполнения inline-скриптов на Python, Node.js и Ruby внутри
маршрута. Это ограничивало RPA-сценарии, где логика обработки проще выразить
коротким скриптом, чем цепочкой процессоров.

## Решение

Добавлен `ScriptRunnerProcessor` и четыре chainable метода RouteBuilder:

- `.script_python(code, *, timeout_seconds, env, allowed_languages)`
- `.script_node(code, *, timeout_seconds, env, allowed_languages)`
- `.script_ruby(code, *, timeout_seconds, env, allowed_languages)`
- `.script_shell(code, *, timeout_seconds, env, allowed_languages)`

Процессор:

1. Пишет `code` во временный файл с правильным расширением (`.py`, `.js`, `.rb`, `.sh`).
2. Запускает через `asyncio.create_subprocess_exec` соответствующий интерпретатор.
3. Capture stdout/stderr/exit_code с `timeout_seconds` (default 30s).
4. Результат пишет в exchange body как `{"stdout", "stderr", "exit_code", "language"}`.
5. `side_effect=SIDE_EFFECTING`, `compensatable=False` — irreversible execution.

Безопасность:

- Без `shell=True`.
- Optional `allowed_languages` whitelist.
- Timeout с `proc.kill()`.
- Интерпретаторы запускаются с правами процесса; production рекомендуется
  запускать в sandbox/контейнере (TD-xxx — future hardening).

## Альтернативы

| Альтернатива | Почему отклонена |
|--------------|------------------|
| Docker-контейнеры для каждого языка | Тяжёлая инфраструктура; требует runtime Docker. Оставлена для future hardening. |
| E2B Sandbox для всех языков | E2B покрывает только Python; платная внешняя зависимость. |
| Расширение `ShellExecProcessor` | ShellExec ориентирован на вызов существующих команд; inline-код требует tempfiles и языковой маршрутизации. |

## Последствия

- Новый процессор: `src/backend/dsl/engine/processors/script_runner.py`.
- Builder методы в `src/backend/dsl/builders/ai_rpa.py`.
- Unit-tests: `tests/unit/dsl/engine/processors/test_script_runner.py`.
- Обновлён `.pyi` stub через `make dsl-stubs`.
- Зависимостей не добавлено: используется `asyncio` + `tempfile` из stdlib.

## Релевантные файлы

- `src/backend/dsl/engine/processors/script_runner.py`
- `src/backend/dsl/builders/ai_rpa.py`
- `tests/unit/dsl/engine/processors/test_script_runner.py`
- `src/backend/dsl/builders/base.pyi`
