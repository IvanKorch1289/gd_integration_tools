# ADR-0404 — Order-dependent тесты: диагностика, устранение загрязнения и гейт

* Статус: Accepted (2026-10-30)
* Автор: wave-21, кластер A3
* Затрагивает: `tests/**`, `tests/unit/conftest.py`, `tests/unit/_xfail_environment.py`

## Контекст

Полный прогон `pytest tests/unit` давал **86 падений в 31 файле**, причём
каждый тест в изоляции проходил. Причина — не «слабые» assert'ы, а
**process-global состояние, которым делятся тестовые модули**:

| Механизм | Симптом |
|---|---|
| `sys.modules[...] = stub` на уровне модуля | подмена `session_manager`/`temporalio`/`polars` переживала тест |
| `importlib.reload(settings_module)` | пересоздавался глобальный singleton `settings` |
| `structlog.reset_defaults()` | stdlib-bridge логгера отключался до конца сессии |
| глобальный breaker-реестр | одна ошибка открывала circuit и ломала 9 тестов |
| `sys.modules` после удаления модуля | новый экземпляр модуля → новый `lru_cache` → новый синглтон |

Особенно коварны два случая:

* `main_session_manager` — PEP-562 `__getattr__` + `@lru_cache`. Удаление
  модуля `session_manager` из `sys.modules` (cleanup conftest) приводило к
  **новому экземпляру синглтона**: `repositories.base.crud_mixin` держал
  старый, а тест патчил новый → декоратор `@main_session_manager.connection()`
  уходил в реальный Postgres (24 падения в `test_base_repository.py`).
* `settings` — `importlib.reload(settings_module)` создавал **новый** объект
  синглтона; ранние импортёры держали старый, поздние — новый, и
  `monkeypatch.setattr(settings.app, "admin_enabled", False)` переставал
  действовать.

Часть падений оказалась **не** order-dependent, а расхождением тестов с
production-контрактом (Protocol-методы, формат вывода гейта, PEP 758) —
они тоже закрыты, но не через банк.

## Решение

1. **Загрязнение устраняется у источника, а не «лечится» skip'ом.**
   Каждый поллитер получил обратимость:
   * outbox-тесты — snapshot/restore `sys.modules["…session_manager"]`;
   * `test_outbox_dispatcher_cutover.py` — snapshot/restore всех
     подменяемых dotted-имён (включая фиктивные
     `…services.outbox.outbox_settings`), из-за которых 5 тестов падали с
     `AttributeError: module 'src.backend.core.config.services' has no
     attribute 'outbox'`;
   * `test_log_sinks/test_pipeline_integration.py` — `structlog.configure(**saved)`
     вместо `structlog.reset_defaults()`;
   * `test_sftp.py` — `settings.transport`-подмена вместо
     `importlib.reload(settings_module)`;
   * `dsl/workflow/compiler/test_step_compilers.py` — реальный
     `temporalio.client` импортируется **до** установки fake'а;
   * frontend-тесты — мок `polars`/`streamlit` ставится только на время
     загрузки страницы и восстанавливается;
   * `tests/unit/conftest.py` — при удалении загрязнённого `polars`
     сносятся и все `polars.*` подмодули; logging-backend инициализируется
     в `pytest_configure` (до циклических импортов).
2. **Глобальное состояние сбрасывается там, где оно глобальное.**
   EventBus-тесты получили autouse-фикстуру сброса breaker-реестра.
3. **Расхождения тест↔production исправлены без ослабления assert'ов:**
   Fake-реализации `RepositoryProtocol`/`ExternalSessionManagerProtocol`
   дополнены до полной поверхности протокола; regex гейта слоёв учитывает
   новый формат вывода; запрет «PEP-758 синтаксиса» заменён запретом
   реально непарсимого `except X, Y as e:` (ADR-0304).
4. **Явный банк xfail** — `tests/unit/_xfail_environment.py`: hook
   `pytest_collection_modifyitems`, xfail с причиной и ссылкой на
   owner-задачу, `strict=True` для детерминированных ограничений.
   Сейчас в банке **1** запись (perf-бенчмарк, недетерминирован по
   природе). `skip` не используется — сигнал не теряется.
5. **Гейт роста банка** — `tests/unit/test_order_dependent_pollution_gate.py`:
   лимит размера банка, проверка существования node-id, закрытый реестр
   order-dependent жертв, AST-скан модульных подмен глобального состояния
   и динамическая проверка пар «поллитер → жертва» в отдельном процессе.

## Альтернативы

* **`pytest.skip` вместо xfail** — отклонено: тест выглядит проверенным,
  сигнал теряется, регрессия не видна.
* **Глобальный `conftest.py`-фикстурный сброс всего подряд** — отклонено:
  скрывает причину и ломает намеренные session-scope override'ы.
* **Правка production-кода** (например, запрет молчаливого переключения
  на stdlib-backend в `infrastructure/logging/factory.py`) — вне зоны
  кластера A3 (production-код не трогаем); вынесено в отчёт.
* **Параллельный прогон (pytest-xdist)** — отклонено: порядок внутри
  воркера не совпадает с serial-порядком, диагностика становится
  невоспроизводимой.

## Последствия

* Полный прогон `tests/unit` перестаёт давать order-dependent падения;
  число падений снижается с 86 (31 файл) до единиц, не связанных с
  загрязнением.
* В `tests/**` появились явные snapshot/restore-паттерны — это цена
  process-wide изоляции; каждый новый такой тест обязан зарегистрироваться
  в `ALLOWED_GLOBAL_STATE_MUTATORS` гейта.
* Банк xfail — только для объективно внешних ограничений; рост банка
  блокируется гейтом и требует ревизии ADR.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit -q -p no:randomly   # 0 падений
.venv/bin/python -m pytest tests/unit/test_order_dependent_pollution_gate.py -q
ruff check tests/unit
```

Гейт падает, если: (а) банк xfail вырос, (б) запись банка указывает на
несуществующий тест, (в) появился файл с маркером
`ADR-0404-ORDER-DEPENDENT`, не зарегистрированный в реестре жертв,
(г) появился новый файл с модульной подменой глобального состояния,
(д) известная пара «поллитер → жертва» снова даёт падения.

## Связи

* ADR-0304 — PEP 758: `except X, Y:` без скобок канонична.
* ADR-0372 — `Settings.reload()` перечитывает конфиг **in-place**.
* ADR-0312 / ADR-0351 — lazy-инициализация logging-бэкенда.
* `docs/roadmap/PROD_READINESS_GAPS.md` — owner-задачи по optional-зависимостям
  и Temporal-окружению.
