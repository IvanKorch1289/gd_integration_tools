# ADR-0369 — RPA: достижимость шагов из YAML и канон именования

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (Wave 14, RPA-ревью, кластер C4)
* **Связан с**:
  - ADR-0058 (экспорт JSON-Schema процессоров)
  - ADR-003 / A2 (YAML whitelist: только публичные методы `RouteBuilder`)
  - ADR-0305 (deadline budget)
  - ADR-0354 (слои DSL ↔ services)
  - ADR-0364 (удаление мёртвого кода — волна 13)
* **Затрагивает**:
  - `src/backend/dsl/engine/processors/rpa/operations/{httprequestprocessor,imageocrprocessor,filtereddirectoryscanprocessor}.py`
  - `src/backend/dsl/builders/ai_rpa/rpa.py`
  - `src/backend/dsl/engine/processors/rpa_banking.py`
  - `src/backend/dsl/engine/processors/rpa/operations/__init__.py`
  - `src/backend/dsl/engine/processors/rpa/utils.py` (удалён)
  - `tools/dsl_export_schemas.py`
  - `tools/dsl_lsp/schema_completion.py`

## Контекст

Wave 14 (ревью RPA роем из 8 агентов, решения владельца —
`artifacts/current_audit/RPA_REVIEW_DECISIONS_2026-10-28.md`) зафиксировала
четыре класса дефектов RPA-подсистемы.

1. **Недостижимые из YAML шаги (решение D6).** Восемь процессоров
   (`csv_read`, `csv_write`, `file_delete`, `file_list`, `ftp_upload`,
   `http_request`, `email_read`, `terminal_exec`) существовали как классы, но
   не имели публичных методов `RouteBuilder`. YAML-загрузчик
   (`dsl/yaml_loader/build.py::_apply_processor`) принимает только публичные
   методы builder'а (A2 whitelist) → такой шаг падал с
   `ValueError: Unknown or forbidden processor 'csv_read'`.
   Дополнительно `browser_launch()` передавал `headless=`, а
   `wait_for_selector()` — `timeout_s=`, чего нет в сигнатурах
   `BrowserLaunchProcessor` / `WaitForProcessor` → **всегда** `TypeError`.

2. **Функциональные баги (C4).** `HttpRequestProcessor` при `to="body"`
   писал payload через `BaseProcessor.set_result`, который трактует
   `"body"` как имя property (`set_property("body", ...)`) → тело exchange
   оставалось пустым, ответ терялся для маршрута.
   `ImageOcrProcessor` не перехватывал `pytesseract.TesseractNotFoundError`
   (нет бинарника tesseract) → исключение роняло весь маршрут вместо
   `exchange.fail(...)`. `FilteredDirectoryScanProcessor` в deadline-ветке
   писал `set_property("body.files", {...})` вместо `body.files = []` —
   формат ответа зависел от ветки.

3. **Мёртвый код.** `rpa/utils.py::write_to_target` — 0 использований
   (решение D4 — удалить).

4. **Инструменты не отражали реальность.** `tools/dsl_export_schemas.py`
   экспортировал **0** схем: реестр `@processor` наполняется на этапе импорта
   модулей, а CLI ничего не импортировал. `tools/dsl_lsp/schema_completion.py`
   предлагал несуществующие шаги (`validate_request`, `try_catch`,
   `sink_publish`) и неверные параметры существующих (`transform.set`,
   `audit.event`, `publish_event.topic`, `choice.condition`/`steps`,
   `parallel.branches[].steps`, `saga.compensate`).

Дополнительно `rpa_banking.py` содержит 5 процессоров-заглушек без
бэкендов (citrix / 3270 / appium / IMAP-драйвер / pyautogui): `process()`
фиксирует намерение в `exchange.properties` и **не выполняет** внешнего
действия. Молчание об этом делало YAML-шаг похожим на рабочий.

## Решение

1. **Канон именования.** Имя YAML-шага = имя публичного метода
   `RouteBuilder`. Реестр `@processor` — метаданные (JSON-Schema, capability,
   теги), а не способ обращения к шагу. Каждая реализация RPA-шага в YAML
   обязана иметь публичный метод builder'а с тем же именем.

2. **Реализованы 8 builder-методов D6** в `dsl/builders/ai_rpa/rpa.py`
   (паттерн `_add_lazy`): `csv_read`, `csv_write`, `file_delete`,
   `file_list`, `ftp_upload`, `http_request`, `email_read`, `terminal_exec`.

3. **Парольные параметры — только dev.** `ftp_upload` / `email_read`
   принимают `password`, но в prod (`APP_ENV=prod|production`) plaintext-пароль
   отклоняется с `ValueError`; источник секрета в prod — Vault
   (`vault_read(...)`). Docstring каждого метода фиксирует «prod — Vault».

4. **Приведённые в соответствие kwargs.** `browser_launch(url=...)`,
   `wait_for_selector(selector=..., state=..., timeout=...)`,
   `print_pdf(format=..., path=..., landscape=...)` — сигнатуры совпадают с
   процессорами.

5. **Функциональные баги исправлены**:
   - `HttpRequestProcessor`: `target == "body"` → payload пишется в
     `exchange.in_message.body`; остальные target'ы — через `set_result`.
   - `ImageOcrProcessor`: `pytesseract.TesseractNotFoundError` →
     `exchange.fail(...)` (fail-closed, маршрут не падает); docstring
     приведён к реальным ключам результата (`text`, `lang`).
   - `FilteredDirectoryScanProcessor`: deadline-ветка →
     `set_result(exchange, self.target, [])` + отдельный property
     `directory_scan.deadline_exhausted`; bare-строка-докстринг внутри
     `process()` удалён.

6. **Мёртвый код удалён**: `rpa/utils.py` (0 использований). `rpa/operations/__init__.py`
   его не реэкспортировал — правок не потребовал.

7. **Заглушки не удалены, а названы заглушками**: docstring каждого из 5
   классов `rpa_banking.py` и module docstring явно фиксируют, что
   бэкенда нет и `process()` — no-op (пишет properties).

8. **Инструменты приведены в соответствие**:
   - `tools/dsl_export_schemas.py`: helper `_ensure_processors_imported()`
     импортирует `src.backend.dsl.engine.processors` перед экспортом →
     реестр наполняется, CLI экспортирует схемы. `ImportError` (optional-зависимость)
     → понятное сообщение и код возврата 1, без traceback.
   - `tools/dsl_lsp/schema_completion.py`: фиктивные шаги удалены, параметры
     приведены к реальным kwarg'ам `RouteBuilder`, добавлены RPA-шаги
     (в т.ч. 8 шагов D6 и browser-триада).

## Альтернативы (отклонённые)

- **Регистрация RPA-шагов в реестре `@processor` как способ обращения из
  YAML** — отклонено: реестр — метаданные; введение второго пути именования
  («имя в реестре» ≠ «имя метода») вернёт расхождение между DSL и
  автодополнением. A2 whitelist уже требует «имя = публичный метод».
- **Манифест `yaml_steps.json` (отдельный список допустимых YAML-шагов)** —
  отклонено: третий источник правды рядом с `RouteBuilder` и реестром;
  рассинхронизация гарантирована (ровно тот дефект, который чинится).
- **Удалить 8 «недостижимых» процессоров** — отклонено решением владельца
  (D6): цель цикла — богатство функционала RPA, а не её усечение.
- **Удалить 5 banking-заглушек** — отклонено решением владельца: заглушки
  держат контракт capability + audit-event для будущей интеграции; удаление
  ломает публичные шаги без выигрыша.
- **Вернуть `headless` / `timeout_s` через `**kwargs`-маппинг в builder** —
  отклонено: процессоры не имеют таких параметров; маппинг скрывал бы
  расхождение, а не устранял его.
- **Хранить plaintext-пароли в YAML и в prod** — отклонено: секреты в
  конфигурации маршрута — прямая утечка; prod — Vault.
- **Ловить `TesseractNotFoundError` на уровне engine (error-handler)** —
  отклонено: процессор знает о своей optional-зависимости; локальный
  `exchange.fail` даёт точное сообщение и не роняет маршрут.

## Последствия

- **Позитивные:** 8 RPA-шагов + browser-триада стали достижимы из YAML;
  LSP перестал предлагать несуществующие шаги; экспорт схем работает
  (`make schemas` больше не выгружает 0 файлов); дефекты `body`/OCR/deadline
  закрыты; 1 мёртвый модуль удалён.
- **Поведенческие:** `HttpRequestProcessor` при `to="body"` теперь пишет в
  тело exchange (а не в property) — маршруты, полагавшиеся на property
  `"body"`, должны читать `in_message.body`; это и есть заявленный контракт.
- **Ограничения:** 5 banking-заглушек остаются no-op до подключения
  бэкендов (citrix / 3270 / appium / IMAP / pyautogui) через DI-провайдер —
  это follow-up, а не решение этого цикла.
- **Wiring `browser_pool` / `desktop_rpa_client` в `ExecutionContext`** —
  вне зоны: RPA browser/desktop по-прежнему дают `RuntimeError` (G12.6).

## Проверка

- `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_c4_rpa_functional_fixes.py tests/unit/dsl/builders/test_rpa_step_reachability.py tests/unit/tools/test_lsp_schema_completion.py tests/unit/tools/test_dsl_export_schemas.py -q -p no:randomly` — green.
- `.venv/bin/python -m ruff check <файлы кластера>` — green.
- `.venv/bin/python tools/check_layers.py --strict` — 41 (baseline, новых нет).
- `.venv/bin/python tools/check_docstrings.py src --max-allowed 0` — 0 missing.
- `.venv/bin/python tools/config_audit.py --scope orphans` — 0.
- Регенерация stub'ов: `python tools/gen_dsl_stubs.py` → `dsl/builders/base.pyi`.

## Связи с другими ADR

- ADR-003 / A2 — YAML whitelist: только публичные методы `RouteBuilder`.
- ADR-0058 — экспорт JSON-Schema процессоров (CLI, требующий наполнения реестра).
- ADR-0305 — deadline budget (ветка «бюджет исчерпан» в directory scan).
- ADR-0354 — границы слоёв DSL ↔ services (банковские заглушки vs DI-провайдер).
- ADR-0364 — волна удаления мёртвого кода (предшественник `rpa/utils.py`).
- ADR-0366 / ADR-0368 — соседние решения cycle 172 (capability-гейт, fail-closed shell).
