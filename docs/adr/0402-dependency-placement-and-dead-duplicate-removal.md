# ADR-0402 — Размещение зависимостей по extras и удаление мёртвого дубля OCR (волна 21, кластер A1)

* Статус: Accepted (2026-10-30, волна 21, кластер A1 — зависимости и мёртвый дубль)
* Cycle: 180 (волна 21)
* Связан с:
  - ADR-0363 (реестр объявлений DSN-драйверов + гейт `tools/check_dsn_drivers.py`),
  - ADR-0383 (деградация соединений; tenant-изоляция raw SQL),
  - ADR-0381 (матрица «тип БД × sync/async» и дефолт sync-драйвера PG `psycopg`),
  - ADR-0385 (риск Pillow 12.x — пин `<13` удерживается из-за `streamlit`),
  - ADR-0388 (политика безопасной загрузки изображений),
  - ADR-0393 (предел ожидания OCR в DSL-шаге),
  - ADR-0100 (прецедент удаления мёртвого дубля — god-file `dsl/builders/eip.py`)
* Затрагивает:
  - `pyproject.toml` (extra `db_drivers`, extra `sources-cdc`),
  - `uv.lock` (метаданные проекта: `requires-dist` по extras),
  - `src/backend/services/rpa/ocr_processor.py` (удалён),
  - `tests/unit/services/rpa/test_ocr_processor.py` (удалён),
  - `tests/unit/services/rpa/test_ocr_processor_timeout.py` (удалён),
  - `tests/unit/core/config/test_driver_extra_placement.py` (новый),
  - `tests/unit/services/rpa/test_ocr_processor_removed.py` (новый),
  - `docs/roadmap/OWNER_TASKS.md` (позиции 2 и 6 — актуализация)

---

## Контекст

Волна 21 закрывает технические открытые задачи по векам из реестра
owner-задач. Кластер A1 — «зависимости и мёртвый дубль» (ADR-0402).

**1. `psycopg[binary]` объявлен не в том extra (G11, owner-задача 2).**
`psycopg[binary]>=3.1,<4.0.0` был объявлен только в extra `sources-cdc`,
тогда как соседние драйверы БД (`oracledb`, `aioodbc`, `aiomysql`,
`clickhouse-connect`, `pyodbc`) живут в extra `db_drivers`. При этом
`sync_driver` PostgreSQL по умолчанию — именно `psycopg`
(`core/config/database.py`: `Field(default="psycopg")`, ADR-0381). Любой
образ, собранный без `sources-cdc` (в частности prod-образ, ставящий
`db_drivers`), получал `ModuleNotFoundError` в
`infrastructure/database/database/initializer.py` → warning
«Sync-драйвер для БД недоступен; sync_engine=None» → durable jobstore
APScheduler молча заменялся на memory. То есть extra «драйверов БД» не был
самодостаточным.

**2. Мёртвый дубль OCR-процессора (owner-задача 6).**
OCR был реализован дважды: `services/rpa/ocr_processor.py` (протокол
`OCRProcessor`, `PytesseractOCRProcessor`, `NoOpOCRProcessor`, фабрика
`from_environment`) и DSL-шаг `ocr`
(`dsl/engine/processors/rpa/operations/imageocrprocessor.py`, класс
`ImageOcrProcessor`). Проверка потребителей: 0 импортов, 0 lazy-импортов,
0 DI-регистраций в `src/` — сервисная копия была мёртвой. Предел ожидания
дублировался: ADR-0368 починил сервисную копию, ADR-0393 добавил тот же
двойной предел (`pytesseract` timeout + `asyncio.wait_for`) в DSL-копию,
которая вдобавок умеет `exchange.fail(...)` с понятным сообщением.

**3. Pillow 13 — блокирующий внешний пин (owner-задача 2a).**
Пин `pillow>=12.3.0,<13.0.0` стоит в трёх местах `pyproject.toml`
(`rpa`, `rpa-windows`, `multimodal-rag`). Факты, проверенные в этой волне:
`streamlit` в `uv.lock` — версия **1.63.0**, её метаданные требуют
`pillow<13,>=7.1.0`; установлен `pillow 12.3.0`; индекс PyPI из этого
окружения **недоступен** (`curl https://pypi.org/simple/pillow/` → таймаут
20 с, HTTP 000), поэтому снятие пина нельзя ни проверить, ни зафиксировать
в lock-файле. 59 CVE Pillow 12.x (5 CRIT) приняты осознанно (ADR-0385 A5).

---

## Решение

### 1. `psycopg[binary]` объявлен в extra `db_drivers`

* `pyproject.toml:212-226` — в extra `db_drivers` добавлено
  `"psycopg[binary]>=3.1,<4.0.0"` с комментарием-обоснованием (ADR-0402).
  Extra `db_drivers` теперь самодостаточен для дефолтного sync-PG.
* `pyproject.toml:516-524` — в extra `sources-cdc` объявление
  **сохранено**: `psycopg` там не «лишний дубль», а CDC-транспорт
  (`pgoutput` logical replication, `infrastructure/sources/cdc.py`), и его
  удаление сломало бы compose-образ (`ops/compose/Dockerfile:38` ставит
  `--extra sources-cdc`) и подсказку в тексте ошибки CDC. Экстра в pip/uv —
  union: одно и то же требование в двух extras не конфликтует (прецедент:
  `rank-bm25` в core-зависимостях и в extra `rag`).
* `uv.lock` пересобран (`uv lock`, 712 пакетов, разрешение — из кэша,
  сети не потребовалось); `uv lock --check` — зелёный. В метаданных
  проекта появились две записи `requires-dist`:
  `psycopg[binary]<4.0.0,>=3.1; extra == "db-drivers"` и
  `...; extra == "sources-cdc"`.
* `uv sync --extra db_drivers` выполнен (с `--inexact`, чтобы не вынести
  из dev-окружения пакеты других extras); установленный проект теперь
  декларирует `psycopg` в обоих extras.

### 2. Мёртвый дубль OCR удалён (прецедент ADR-0100)

* Удалён `src/backend/services/rpa/ocr_processor.py` (215 LOC) — 0
  потребителей в `src/`.
* Удалены его тесты: `tests/unit/services/rpa/test_ocr_processor.py` и
  `tests/unit/services/rpa/test_ocr_processor_timeout.py`. Покрытие
  таймаута не потеряно: DSL-канон закрыт тестами
  `tests/unit/dsl/engine/processors/rpa/operations/test_imageocrprocessor.py`
  и `tests/unit/dsl/engine/processors/rpa/test_adr0393_rpa_guards.py`
  (`test_ocr_step_times_out`, `test_ocr_step_has_default_timeout`).
* Канон — DSL-шаг `ocr` (`ImageOcrProcessor`): capability-гейт
  `rpa.image.ocr`, `exchange.fail` с понятным сообщением вместо пустой
  строки, безопасная загрузка изображения (ADR-0388).
* Инвариант «одна реализация OCR» закреплён новым тестом
  `tests/unit/services/rpa/test_ocr_processor_removed.py`: модуль
  отсутствует, ни один модуль `src/` его не импортирует, канон на месте.

### 3. Pillow 13 — owner-задача (кодовых правок нет)

Пункт (а) owner-задачи 2 не закрывается кодом: снятие пина требует
обновления `streamlit` (или явного принятия 59 CVE) и пересборки
lock-файла, а индекс PyPI из текущего окружения недоступен. Пункт
зафиксирован в `docs/roadmap/OWNER_TASKS.md` §2 с критериями приёмки:
`streamlit` ≥ версии, допускающей `pillow>=13`; пин снят в трёх местах
`pyproject.toml`; `uv lock` без `pillow<13`; `uv audit --frozen` не
содержит Pillow; `tools/config_audit.py --scope orphans` → 0.

---

## Альтернативы (отклонённые)

* **Полностью убрать `psycopg` из `sources-cdc`** — отклонено: extra
  становится пустым, compose-образ (`ops/compose/Dockerfile:38`) теряет
  CDC-драйвер, а подсказка «добавьте optional extra sources-cdc» в
  `infrastructure/sources/cdc.py` становится ложной. Перенос объявления
  без смены состава образа — риск регрессии CDC в контейнере.
* **Переименовать extra `db_drivers` → `db-drivers`** — отклонено:
  ломает `pip install 'gd-advanced-tools[db_drivers]'` из сообщений
  рантайм-guard'а и документации; в `uv.lock` имя и так нормализуется.
* **Перенести канон OCR в слой `services`** — отклонено: DSL-шаг `ocr`
  уже в реестре процессоров, покрыт тестами и имеет capability-гейт;
  перенос означал бы ломающее изменение публичного API DSL и переписывание
  маршрутов.
* **Оставить сервисную копию как «библиотеку для внешних потребителей»** —
  отклонено: публичного API вне `src/` нет (0 импортов в репозитории,
  включая `extensions/`), а документация `docs/rpa/RPA_GUIDE.md`
  каноном называет DSL-шаг `ocr`.
* **Снять пин Pillow и разблокировать lock «по сети»** — отклонено:
  индекс PyPI из окружения недоступен (таймаут), lock неразрешим;
  принятие 59 CVE без решения владельца — не наш выбор.

---

## Последствия

* **Позитивные**: extra `db_drivers` самодостаточен — образ, ставящий
  только его, получает sync-драйвер PostgreSQL и не деградирует в
  `sync_engine=None`; в `src/` осталась одна реализация OCR; lock-файл
  синхронизирован с манифестом.
* **Осознанные изменения поведения**: `pip install gd-advanced-tools`
  без extras по-прежнему не ставит `psycopg` — изменился только состав
  `db_drivers`; `psycopg` теперь заявлен в двух extras (union, конфликта
  нет).
* **Потолок решения**: дублирование объявления `psycopg` в `sources-cdc`
  снимается только вместе с переводом compose-образа на
  `--extra db_drivers` и переприцеливанием подсказки в
  `core/config/db_drivers.py` (реестр объявлений) — это вне зоны кластера,
  см. «Связи».
* **Вне зоны (волна 21)**: `core/config/features/infrastructure.py` —
  feature-flag `rpa_ocr_enabled` и его описание по-прежнему ссылаются на
  удалённый сервисный OCR-процессор; флаг больше не управляет
  реализацией (канон закрыт capability-гейтом `rpa.image.ocr`), его
  удаление/переприцеливание — задача владельца конфигурации.

---

## Проверка

* `.venv/bin/python -m pytest tests/unit/core/config/test_driver_extra_placement.py tests/unit/services/rpa/test_ocr_processor_removed.py -q -p no:randomly` — **6 passed** (до правок: 3 failed — дефект воспроизведён).
* `.venv/bin/python -m pytest tests/unit/core/config tests/unit/services/rpa tests/unit/dsl/engine/processors/rpa tests/unit/docs/test_workflow_docs_wave20.py -q -p no:randomly` — 1380 passed, 2 skipped (pre-existing env-зависимые skip'ы).
* `uv lock --check` → `Resolved 712 packages` (зелёный); `uv sync --extra db_drivers --inexact --offline` → OK.
* `.venv/bin/python tools/check_declared_dependencies.py` — 0 новых необъявленных зависимостей.
* `.venv/bin/python tools/check_dsn_drivers.py --ci --scope declarations` — «All referenced drivers are declared in extras», exit 0.
* `.venv/bin/python tools/config_audit.py --scope orphans` — 0.
* `.venv/bin/python tools/check_layers.py --strict` — 41 (baseline, новых нет).
* `.venv/bin/python tools/check_docstrings.py src --max-allowed 0` — 0 missing.
* `.venv/bin/python -m ruff check <файлы кластера>` — clean.

---

## Связи с другими ADR

- ADR-0363 — реестр `DB_DRIVER_DECLARATIONS` объявляет `psycopg` в extra
  `sources-cdc`; переприцеливание подсказки на `db_drivers` — отдельная
  правка (вне зоны, требует перевода compose-образа).
- ADR-0381 — дефолт sync-драйвера PG `psycopg`; теперь его extra
  совпадает с extra остальных драйверов БД.
- ADR-0385 / ADR-0388 — пин Pillow `<13` (owner-задача, кодовых правок
  нет) и безопасная загрузка изображений в канонном OCR-шаге.
- ADR-0393 — двойной предел ожидания OCR в DSL-шаге (покрытие таймаута
  перешло к канону вместе с удалением сервисной копии).
- ADR-0100 — прецедент удаления мёртвого дубля (проверка «0 потребителей
  + идентичный результат тестов»).
- ADR-0401 — волна 20, кластер W4: тот же формат ADR и тот же перечень
  гейтов перед сдачей.
