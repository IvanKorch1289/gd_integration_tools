# ADR-0370 — Консолидация RPA-конфига, честная документация и тестовая гигиена

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (Wave 14, RPA-ревью, кластер C5)
* **Связан с**:
  - ADR-0358 (allowlist файловых путей и единый path-барьер DSL)
  - ADR-0361 (семантика `required_capability`)
  - ADR-0362 (config-audit: orphan vs missing)
  - ADR-0364 (удаление мёртвого кода — волна 13)
  - ADR-0366 (runtime-enforcement capability-гейта DSL)
  - ADR-0367 (файловый доступ и защита от инъекций в RPA-процессорах)
  - ADR-0368 (fail-closed whitelist shell-команд)
  - ADR-0369 (достижимость RPA-шагов из YAML и канон имён)
* **Затрагивает**:
  - `src/backend/core/config/services/rpa.py`
  - `src/backend/core/config/features/{sprints_18_21,sprint19_dx,experimental,infrastructure}.py` (только описания флагов)
  - `src/backend/core/security/capabilities/core_declarations.py`
  - `config_profiles/base.yml` (только секция `rpa:`)
  - `docs/rpa/RPA_GUIDE.md`, `docs/rpa/DSL_AUDIT.md`, `docs/reference/capabilities.md`
  - `tests/rpa/*`, `tests/unit/dsl/engine/processors/rpa/**`, `tests/unit/services/rpa/**`

## Контекст

Wave 14 (ревью RPA роем из 8 агентов; решения владельца —
`artifacts/current_audit/RPA_REVIEW_DECISIONS_2026-10-28.md`) зафиксировала
дефекты, которые не ломают код, но ломают доверие к конфигурации и к
документации RPA.

1. **Мёртвые поля `RPASettings` (решение D3).** 13 полей
   (`desktop_base_url`, `desktop_api_key`, `desktop_timeout`,
   `desktop_ttl_seconds`, `desktop_max_sessions`, `desktop_cb_*` (2),
   `desktop_retry_max_attempts`, `browser_kind`,
   `browser_viewport_width`, `browser_viewport_height`, `ocr_enabled`,
   `ocr_default_lang`) **не читаются нигде** в `src/` (проверено grep'ом:
   0 чтений). При этом модель объявлена с `extra="forbid"` и префиксом
   `RPA_` → унаследованная env-переменная `RPA_DESKTOP_API_KEY` (или
   `RPA_OCR_ENABLED`) роняет старт процесса с `ValidationError`, хотя
   параметр всё равно никто не использует. Плюс `ocr_enabled`/`ocr_default_lang`
   дублировали feature-флаг `rpa_ocr_enabled`, который читает
   `services/rpa/ocr_processor.py`.

2. **Документация врала.** Capability-таблица `docs/rpa/RPA_GUIDE.md`
   содержала 16 несуществующих имён из 33 (`rpa.file.archive`,
   `rpa.file.hash`, `rpa.doc.pdf.read`, `rpa.banking.citrix`, `rpa.file.*`
   для crypto/template/regex, `rpa.doc.excel.read` …) — реальные имена
   живут в vocabulary (`rpa_fs.py`) и выглядят иначе
   (`rpa.archive.execute`, `rpa.hash.compute`, `rpa.pdf.read`,
   `rpa.citrix.invoke`, `rpa.crypto.encrypt`, …). Кроме того: в таблице
   был несуществующий `ImageConvertProcessor`; пример YAML-маршрута ссылался
   на методы `RouteBuilder`, которых не существует; утверждение
   «Audit events → ClickHouse/Redis» не имело потребителя
   (`audit_event` объявлен на 308 процессорах и **ни разу** не читается);
   роль для HTTP-слоя бралась из заголовка `X-Roles`, тогда как
   middleware читает `scope["state"]["auth"].roles`
   (`rpa_policy.py:104-116`); в разделе настроек фигурировали
   несуществующие `rpa.shell_timeout_s`, `rpa.file_watch_timeout_s`,
   `rpa.max_archive_size_mb`, `rpa.process_pool_size`.
   `docs/rpa/DSL_AUDIT.md` содержал 4 из 5 «GAP»-процессоров, которые давно
   реализованы, и taxonomy из capability-имён, которых нет в vocabulary.

3. **Capability-каталог отставал.** `docs/reference/capabilities.md` —
   генерируемый артефакт (`make capability-catalog`), но содержал 51 строку
   из 108 capability. Свежесть проверял только pre-commit hook, которого нет
   в CI.

4. **`CORE_CAPABILITIES` неполон.** В baseline-декларацию ядра не входили
   4 capability, которые реально используются процессорами и есть
   в vocabulary: `web_search.perplexity.invoke`, `web_search.tavily.invoke`,
   `workflow.claim_check.store`, `workflow.continue_as_new.request`.
   Capability-гейт fail-closed → эти процессоры получали blanket-deny.

5. **Описания флагов противоречили значениям.** 5 RPA-флагов имели
   `default=True` при описании «default-OFF до …»
   (`rpa_resilience_wrapper_enabled`, `desktop_rpa_session_pool_enabled`,
   `browser_cookies_redis_persist`, `rpa_session_persistence`,
   `rpa_ocr_enabled`).

6. **Тестовая гигиена.** Осиротевшие дубли `tests/rpa/` ломали CI:
   `test_browser_cookies.py` требовал Fernet-ключ (нет в окружении),
   `test_desktop_pool.py` ждал `httpx.AsyncClient` вместо
   `OutboundHttpClient`. `test_more_rpa_tools.py` **присваивал**
   `ftplib.FTP`/`ftplib.FTP_TLS` на глобальном модуле — мутация переживала
   тест и ломала соседние FTP-тесты при `pytest -n auto`.
   `test_new_rpa_tools.py` писал в общий `/tmp/dsl` вместо `tmp_path`.
   `test_operation_processors.py` проверял моки без значений
   (`assert_called()`) — тест проходил бы и при неверных аргументах.
   `ImageOcrProcessor.process` и 5 процессоров `rpa_banking.py` не имели
   покрытия вообще.

## Решение

### 1. Мёртвые поля `RPASettings` удалены (решение D3)

Перед удалением — grep-проверка: `RPA_*` в репозитории встречается только
в `tools/config_audit_allowlist.txt` (allowlist config-audit'а, а не
env-деплой), в `.env.example` и профилях — **нет**. Старт приложения
не падает.

В модели остались 4 живых поля (их читает `services/rpa/browser_pool.py`):
`browser_pool_size`, `browser_headless`, `browser_launch_max_retries`,
`browser_launch_retry_base_seconds`. Параметры desktop-RPA pool'а
(`base_url`, `api_key`, `timeout`, `ttl_seconds`, `max_sessions`) —
ctor-аргументы `DesktopRPASessionPool`, а не настройки приложения.

Секция `rpa:` в `config_profiles/base.yml` содержит ровно эти 4 поля →
`tools/config_audit.py --scope orphans` = 0.

**Release-note обязателен:** удаление полей — breaking change для
окружений, где выставлены `RPA_DESKTOP_*` / `RPA_OCR_*` /
`RPA_BROWSER_VIEWPORT_*` / `RPA_BROWSER_KIND` (при `extra="forbid"` старт
упадёт с `ValidationError` — это осознанный fail-fast, а не тихая потеря
настройки).

### 2. Описания 5 RPA-флагов приведены в соответствие

Использован паттерн `tenant_cache_prefix_enabled`: описание явно фиксирует
фактическое значение по умолчанию (`True`) и явно называет прежнюю
формулировку цитатой (цитата — отсылка к истории, а не утверждение).
Гейт `tests/unit/services/rpa/test_rpa_feature_flags.py` не допускает
возврата противоречия.

### 3. `CORE_CAPABILITIES` дополнен 4 capability

`web_search.perplexity.invoke`, `web_search.tavily.invoke`,
`workflow.claim_check.store`, `workflow.continue_as_new.request` добавлены
в baseline-декларацию ядра; гейт
`tests/unit/services/rpa/test_core_capabilities.py` проверяет, что
`CORE_CAPABILITIES ⊆ vocabulary` и что все 4 присутствуют.

### 4. Capability-каталог перегенерирован, гейт перенесён в CI

`docs/reference/capabilities.md` перегенерирован
(`tools/export_v11_artefacts.py capability-catalog`) → 108 строк.
Свежесть теперь проверяется pytest'ом (`tests/rpa/test_capability_catalog_freshness.py`),
а значит — в CI (`pytest tests`).

### 5. Документация приведена в соответствие с кодом

* `RPA_GUIDE.md`: capability-таблица перегенерирована (41 capability,
  46 процессоров), пример YAML использует **реальные** методы
  `RouteBuilder` (`file_list` / `terminal_exec` / `file_delete` /
  `csv_read` / `csv_write` / `email_read` — появились в ADR-0369), добавлен
  раздел про path-allowlist (`settings.dsl.allowed_paths`, env
  `DSL_ALLOWED_PATHS`, ADR-0358), исправлен источник роли
  (`scope["state"]["auth"].roles`), audit-события помечены как
  **нереализованные**, удалён `ImageConvertProcessor`, исправлены
  счётчики (посчитаны через AST) и несуществующие поля настроек.
* `DSL_AUDIT.md`: GAPS-таблица и taxonomy приведены к коду (закрытые
  пункты вынесены отдельно, taxonomy ссылается только на существующие
  capability).

Гейт актуальности — `tests/rpa/test_rpa_docs.py`: capability-таблица
должна совпадать с vocabulary, а упомянутые процессоры — существовать
в `src/backend`.

### 6. Тестовая гигиена

* Непокрытые кейсы из `tests/rpa/` перенесены в
  `tests/unit/services/rpa/` (multi-tenant изоляция, TTL=86400,
  worker-restart, session-affinity, TTL-expiry, force-reconnect,
  разные app_name → разные клиенты), после чего **осиротевшие файлы
  `tests/rpa/test_browser_cookies.py` и `tests/rpa/test_desktop_pool.py`
  удалены**.
* Глобальная мутация `ftplib` заменена на `monkeypatch.setattr`.
* Запись в общий `/tmp/dsl` заменена на `tmp_path` + `DSL_ALLOWED_PATHS`.
* Моки в `test_operation_processors.py` проверяют значения
  (`assert_called_once_with` по ключу, данным и результату).
* Добавлены тесты на `ImageOcrProcessor.process` и на 5 процессоров
  `rpa_banking.py` (happy path, deny-путь, валидация ctor).
* Гейт `tests/unit/dsl/engine/processors/rpa/operations/test_rpa_test_hygiene.py`
  (AST-скан) не допускает возврата мутации глобальных модулей, записи
  в общий `/tmp` и value-less mock-assertions.

## Альтернативы (отклонённые)

1. **Оставить мёртвые поля, пометив deprecated.** Отклонено: конфиг
   продолжает врать (тот же принцип, что в ADR-0362), а `extra="forbid"`
   сохраняет риск падения старта. Владелец в раунде 1 (решение D3)
   выбрал удаление.
2. **Удалить поля, но ослабить `extra="forbid"` до `extra="ignore"`.**
   Отклонено: теряется защита от опечаток в env-имёнх (ADR-0362),
   конфликтует с принципом «fail-fast на неизвестной конфигурации».
3. **Не трогать документацию, исправить только код.** Отклонено: именно
   документация была источником 16 выдуманных capability; без
   автоматического гейта расхождение вернётся при следующем
   переименовании в vocabulary.
4. **Перенести `tests/rpa/*` в `tests/unit/` целиком (без удаления
   дублей).** Отклонено: файлы дублировали уже существующие тесты и
   падали из-за устаревшего API (Fernet-ключ, тип клиента) — перенос
   сохранил бы мусор в CI.
5. **Удалить `audit_event` у 308 процессоров** («нет потребителя —
   значит, поле лишнее»). Отклонено: поле — часть публичного контракта
   процессоров; правильная фикса — подключить audit-sink (owner-задача),
   а не снести пол-контракта в одном цикле. Документация честно
   помечает поведение как нереализованное.
6. **Перенести гейт свежести каталога в `tests/tools/`.** Отклонено:
   `tests/tools/` вне зоны кластера C5; гейт положен в `tests/rpa/`,
   где он всё равно исполняется тем же CI-прогоном.

## Последствия

* **Позитивные:** конфигурация RPA описывает только то, что реально
  работает; capability-каталог и документация не расходятся с кодом
  (и защищены гейтами); CI больше не падает на осиротевших дублях и
  глобальной поллюции; 4 capability, которым раньше грозило blanket-deny,
  объявлены в baseline ядра.
* **Негативные (breaking):** окружения с выставленными `RPA_DESKTOP_*`,
  `RPA_OCR_*`, `RPA_BROWSER_VIEWPORT_*`, `RPA_BROWSER_KIND` упадут на
  старте с `ValidationError` → **release-note обязателен**; удалённые
  поля не восстанавливаются автоматически.
* **Долги, зафиксированные за владельцем:** (а) потребитель
  `audit_event` (audit-sink для DSL-процессоров); (б) capability-гейт
  для legacy proxy/antivirus-процессоров; (в) `FileSearchProcessor`
  (единственный открытый gap из `DSL_AUDIT.md`); (г) deprecation-нота
  для `services/rpa/ocr_processor.py` (дублирует `ImageOcrProcessor`;
  удаление отложено, C3 чинит таймаут tesseract).
* **Вне зоны кластера C5:** реализация `audit_event`-потребителя,
  capability-гейт legacy-процессоров, `FileSearchProcessor`,
  `services/rpa/ocr_processor.py`.

## Проверка

```bash
.venv/bin/python -m pytest tests/rpa tests/unit/services/rpa \
    tests/unit/dsl/engine/processors/rpa -q -p no:randomly
.venv/bin/python -m ruff check \
    src/backend/core/config/services/rpa.py \
    src/backend/core/config/features/sprints_18_21.py \
    src/backend/core/config/features/sprint19_dx.py \
    src/backend/core/config/features/experimental.py \
    src/backend/core/config/features/infrastructure.py \
    src/backend/core/security/capabilities/core_declarations.py \
    tests/rpa tests/unit/services/rpa tests/unit/dsl/engine/processors/rpa
.venv/bin/python tools/check_layers.py --strict          # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/config_audit.py --scope orphans    # 0
.venv/bin/python tools/check_v11_artefacts.py             # capabilities.md свеж
```

## Связи с другими ADR

* **ADR-0358** — источник истины для path-allowlist (`settings.dsl.allowed_paths`),
  на который ссылается обновлённый `RPA_GUIDE.md`.
* **ADR-0361** — семантика `required_capability`; baseline-декларация ядра
  расширена в этом ADR.
* **ADR-0362** — `orphan` vs `missing` в config-audit: секция `rpa:` в
  `base.yml` обязана состоять только из живых полей модели.
* **ADR-0364** — общий принцип удаления мёртвого кода (применён к полям
  конфигурации).
* **ADR-0366** — runtime-enforcement capability-гейта: объявленные здесь
  4 capability иначе получали blanket-deny.
* **ADR-0367 / ADR-0368 / ADR-0369** — соседние кластеры cycle 172;
  `RPA_GUIDE.md` ссылается на них.
