# RPA-ревью и решения гриллинга (Cycle 172, Wave 14)

**Дата**: 2026-10-28
**Вход**: ревью RPA роем из 8 агентов (DSL-поверхность, настройки, богатство
функционала, библиотеки, отказоустойчивость, тесты, безопасность, документация)
+ планирование роем из 5 агентов (кластеры C1–C5).

**Метод**: гриллинг (решения — владельца, факты — исполнителя) +
ub-mode (First Make it Work → Then Make it Right → Follow Practice:
падающий тест → минимальная правка → зелёный тест).

`AskUserQuestion` в auto-режиме недоступен → раунд оформлен этим документом;
рекомендации приняты по умолчанию, каждое помечено как пересматриваемое.

---

## Раунд 1 — решения по ревью RPA

### ❓ D1 — Capability-гейт: починить или отложить? (ADR-0361 / G12)

Факты: `BaseProcessor.auth_check` → sync `AuthorizationGateway.check` →
allow только из пустых in-memory policies; `CapabilityGate.check` в этом пути
не вызывается → **deny для любого** `required_capability` (72 RPA-процессора +
~40 прочих). Async-ветка `authorize()` capability-гейт использует — пути расходятся.
Ревью RPA подтвердило: RPA-подсистема **функционально мертва** в рантайме.

Варианты: (a) починить сейчас через namespace-резолвер + feature-флаги;
(b) починить, но включить только в dev; (c) отложить.

➡️ **Рекомендация: (a) с безопасным включением.** Namespace = `route_id` роута,
иначе `"core"`; `principal` **никогда** не используется как namespace (риск из
ADR-0361). Два флага: `dsl_capability_gate_enabled` (default OFF) и
`dsl_capability_core_baseline_enabled` (default OFF) → baseline открывается
явно. Rollout: dev → staging (после миграции `route.toml`) → prod.

**Решено по рекомендации.** Реализация: C1, ADR-0366.

### ❓ D2 — `ShellExecProcessor`: whitelist по умолчанию

Факты: `allowed_commands=None` → whitelist не проверяется, хотя docstring
обещает «только команды из whitelist». Прод-роутов с `.shell(...)` нет (grep).

➡️ **Рекомендация: fail-closed** — без whitelist команда не выполняется
(понятная ошибка), ADR-0368 фиксирует смену семантики DSL.

**Решено по рекомендации.** Реализация: C3.

### ❓ D3 — 13 мёртвых полей `RPASettings` при `extra="forbid"`

Факты: поля `desktop_*`, `browser_viewport_*`, `ocr_*` не читаются; удаление
при `extra="forbid"` → `ValidationError` на старте, если `RPA_*` остались в env.
В репозитории `RPA_*` встречаются только в `tools/config_audit_allowlist.txt`.

➡️ **Рекомендация: удалить поля** (конфиг не должен врать — тот же принцип,
что в ADR-0362) + проверить env через grep перед удалением + release-note.

**Решено по рекомендации.** Реализация: C5, ADR-0370.

### ❓ D4 — Мёртвый RPA-код

Факты: `rpa/utils.py::write_to_target` — 0 использований; `rpa/operations/
filewatchprocessor.py` — дубль ядерного `file_watch.py` без потребителей;
`services/rpa/ocr_processor.py` — 177 LOC, дублирует ImageOcr.

➡️ **Рекомендация:** удалить `rpa/utils.py`; `filewatchprocessor.py` **оставить**
и починить (он реализует живой watchdog-watch с ранним выходом, в отличие от
ядерного polling-варианта), но не дублировать его в YAML; `ocr_processor.py`
оставить с deprecation-нотой (его фиксит C3 — таймаут tesseract).

**Решено по рекомендации.** Реализация: C3 (filewatch/ocr), C4 (rpa/utils).

### ❓ D5 — Необъявленные зависимости RPA

Факты: `watchdog` (filewatchprocessor — RPA на macOS/Windows неработоспособна),
`pdfplumber` (молча отдаёт `tables=[]` — потеря данных), `jinja2` (шаблон
падает), `Pillow` (image/ocr), `pyautogui`, `apprise` — используются, но не
объявлены.

➡️ **Рекомендация: объявить** `watchdog`, `pdfplumber`, `jinja2`, `Pillow`
в extra `rpa`; `pyautogui`/`apprise` — в соответствующие extras; lock обновить
(lock-чанж согласован владельцем в раунде 2 раунда Q2 — распространяется).

**Решено по рекомендации.** Реализация: трек зависимостей (вне кластеров).

### ❓ D6 — 8 RPA-шагов недостижимы из YAML

Факты: `csv_read`, `csv_write`, `file_delete`, `file_list`, `ftp_upload`,
`http_request`, `email_read`, `terminal_exec` существуют как процессоры, но
нет публичных методов `RouteBuilder` → YAML-шаг `Unknown or forbidden processor`.
`browser_launch()`/`wait_for_selector()` — всегда TypeError (kwargs ≠ сигнатуры).

➡️ **Рекомендация: добавить builder-методы и починить kwargs** (цель цикла —
богатство функционала RPA; удалять классы — против цели).

**Решено по рекомендации.** Реализация: C4, ADR-0369.

### ❓ D7 — Политика обновления библиотек

➡️ **Рекомендация:** patch/minor в текущих мажорных — автоматически; major —
только после проверки затронутого кода grep'ом и с обновлением `.pyi`/ADR.
Уязвимости с известным фиксом — обязательны к применению.

**Решено по рекомендации.** Реализация: трек зависимостей.

---

## Кластеры доработки (разделение файлов — конфликтов нет)

| Кластер | Владеет файлами | ADR |
|---|---|---|
| C1 — capability-гейт | `core/security/capabilities/runtime_resolver.py` (нов.), `gate/declaration_mixin.py`, `dsl/engine/processors/base.py`, `dsl/engine/processors/agent_dsl/_base.py`, `dsl/engine/exchange.py`, `core/config/features/dsl.py`, `config_profiles/dev.yml`, `config_profiles/dev_light.yml` | ADR-0366 |
| C2 — файлы и инъекции | `rpa/operations/{csvreadprocessor,csvwriteprocessor,filedeleteprocessor,archiveprocessor}.py`, `rpa/documents.py` | ADR-0367 |
| C3 — отказоустойчивость | `dsl/engine/execution_engine.py`, `services/rpa/{desktop_session_pool,rpa_policy,ocr_processor}.py`, `rpa/system.py`, `rpa/operations/filewatchprocessor.py` | ADR-0368 |
| C4 — функционал и достижимость | `rpa/operations/{httprequestprocessor,imageocrprocessor,filtereddirectoryscanprocessor}.py`, `builders/ai_rpa/rpa.py`, `rpa_banking.py`, `rpa/operations/__init__.py`, `rpa/utils.py` (удаление), `tools/dsl_export_schemas.py`, `tools/dsl_lsp/schema_completion.py` | ADR-0369 |
| C5 — документация, конфиг, тесты | `docs/rpa/*`, `docs/reference/capabilities.md`, `core/config/services/rpa.py`, `core/config/features/{sprints_18_21,sprint19_dx,experimental,infrastructure}.py` (только описания), `core/security/capabilities/core_declarations.py`, `config_profiles/base.yml`, `tests/rpa/*`, `tests/unit/dsl/engine/processors/rpa/**`, `tests/unit/services/rpa/**` | ADR-0370 |

`docs/adr/INDEX.md` перегенерируется оркестратором после всех кластеров.

---

## Находки, признанные follow-up (не чиним в этом цикле)

- Wiring `browser_pool`/`desktop_rpa_client` в `ExecutionContext` (RPA browser/desktop
  всегда RuntimeError) — G12.6.
- 5 banking-заглушек (`rpa_banking.py`) — нет бэкендов citrix/3270/appium.
- `FacadeCapabilityAdapter` глотает deny в `authorize()` — G12.3.
- 13 классов с `required_capability`, но без вызова `auth_check` — G12.2.
- Миграция `route.toml` под новый namespace — G12.4.
- Потолок `wait_for(to_thread(...))` — поток executor'а не прерывается.
- `services/rpa/ocr_processor.py` — deprecation вместо удаления.
