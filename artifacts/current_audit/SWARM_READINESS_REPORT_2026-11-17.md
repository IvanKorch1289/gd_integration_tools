# Роевой отчёт по готовности и развитию проекта — волна 34

**Дата:** 2026-11-18 · **Срез:** `master` @ `4139a9579` (+ волна 34, 19 коммитов) ·
**Метод:** 8 параллельных агентов (инфраструктура, capability-контур, движок,
мутационный гейт, инверсия слоёв × 3) + собственные прогоны гейтов, полная
регрессия `tests/unit` в каноническом CI-режиме, групповой coverage-прогон и
холодный прогон mutation-гейта.

> Волна 33 закрыла «декларативно закрытые» пункты. Волна 34 закрывает
> **оставшиеся долги кодом**: межслойные зависимости (37 → 0), enforcement
> capability в движке, честность мутационного гейта, перемер покрытия и
> инфраструктурные артефакты прод-контура.

---

## 1. Резюме

**Вердикт: ГОТОВ К ПРОДУ С ОГОВОРКАМИ.** Кодовый контур прод-готов: полная
регрессия в CI-режиме зелёная, все блокирующие гейты проходят, долг
межслойных зависимостей обнулён.

Главный результат волны 34 — **обнуление долга слоёв и честность гейтов**.

| Показатель | Было (волна 33) | Стало (волна 34) | Источник |
|---|---|---|---|
| Регрессия `tests/unit` (CI-режим) | 24 122 passed, 0 failed | **24 328 passed, 0 failed** (159 skipped, 52 xfailed, 48 xpassed), 597 с | `.run/wave34-logs/reg_ci_r4.txt` |
| Межслойные нарушения | 40 (долг 37 + контракты 3) | **3** (долг **0** + 3 осознанных контракта) | `tools/check_layers.py --strict` |
| Enforcement capability | только в процессорах (7 из 64) | **в движке** — перед каждым шагом | ADR-0456 |
| Coverage (line-rate, метрика гейта) | 74 % (branch-число) | **77.68 %** (branch 75 %) | `.baselines/coverage.json` |
| Mutation-гейт | fail-open (мог «прозеленеть» без прогона) | **fail-closed**, контракт 0/1/2/3, SKIPPED с причиной; baseline 21.6 % переподтверждён холодным прогоном | ADR-0452 |
| Инфраструктурные 6 действий | артефакты готовы, развёртывания нет | сервисы **в compose.prod** + гейт `make infra-readiness` | `docs/ops/infra-release-checklist.md` |
| OpenAPI | 447 путей | **447 путей** (не изменилось) | smoke на пересобранном app |
| Декоративные capability-декларации | 0 | 0 | `tools/check_decorative_capabilities.py` |
| CVE | 0 неигнорируемых | 0 | `make cve-gate` |

**Что изменилось за волну 34:** инверсия всех межслойных зависимостей
`src/ → extensions` через core-реестр ресурсов, инверсия `core → services.ai`
и `infrastructure/workflow → dsl`, engine-wide enforcement capability,
честный мутационный гейт, перемер покрытия, compose-сервисы прод-инфры,
гейт готовности инфры, фикс CI-режима (polars).

---

## 2. Что закрыто кодом

### 2.1. Межслойные зависимости: долг 37 → 0 (ADR-0450, ADR-0457)

Три независимые инверсии:

1. **`core → services.ai` (6)** — реализация AI-модулей перенесена в core
   (`core/ai/gateway/*`, `core/ai/guardrails/lakera_client.py`,
   `core/ai/metrics.py`, `core/ai/prompt_registry.py`, `core/ai/multi_agent.py`),
   в `services/ai/*` остались re-export шимы; публичные пути импорта и
   identity объектов сохранены. `core/security/connector_auth.py` обращается к
   `services.authorization` через DI-provider (`core/di/providers/auth.py`).
2. **`infrastructure/workflow → dsl` (4)** — `Exchange` перенесён в core
   (`core/engine/exchange.py`, в `dsl/engine/exchange.py` — совместимый шим);
   `worker.py` получает зависимости инъекцией (DSL-aware адаптер —
   `plugins/composition/workflow_worker.py`); CDC-клиент берёт dispatcher снаружи.
3. **`src/ → extensions` (27)** — **реестр ресурсов расширений**
   (`core/extension_registry.py`): расширение **отдаёт** схемы/сервисы/модели,
   потребитель **забирает** их по ключу `(domain, kind, name)`. Покрыты
   entrypoints (18), dsl (7), services (3).

**Проверка честности инверсии:** количество путей OpenAPI не изменилось
(**447** до и после) — HTTP-поверхность не поехала; набор зарегистрированных
action'ов не изменился; регрессия зелёная.

**Осталось 3 записи** в `tools/check_layers_contract.txt` — осознанные
контракты `services → dsl` (ADR-0348, вариант C): публичные фасады, намеренно
отдающие DSL-примитивы. Их устранение требует переноса `BaseProcessor` в core
(решение по матрице слоёв), а не правки кода.

### 2.2. Engine-wide enforcement capability (ADR-0456)

Проверка capability шага перенесена из процессоров (opt-in, 7 из 64) **в
движок**: `dsl/engine/capability_guard.py` вызывается до `processor.process()`
в основном пути, параллельном пути и во вложенных шагах.

* шаг **без** capability-декларации → поведение не меняется (обратная совместимость);
* шаг **с** декларацией → канонический гейт (runtime-resolver, ADR-0366),
  отказ = `failed` + `stopped`, шаг **не выполняется**, статус `denied` в trace;
* идемпотентность: `capability_verified` не даёт второй проверки и второго
  audit-события `capability.check`;
* `capability_action` (по умолчанию `execute`, у `AuditProcessor` — `write`):
  scope запроса движка совпадает с запросом самого процессора;
* `function.call` объявлена в `routes/jupyter_hub_run` и `routes/osint_agent`,
  capability стала public в vocabulary (как `audit.write`) — плагина-владельца
  нет, рантайм-контроль не ослаблен.

### 2.3. Инфраструктурные 6 действий (ADR-0455, продолжение)

* **compose.prod**: добавлены сервисы `clickhouse` (DDL audit-трейла
  накатывается на первом старте), `open-webui` (`WEBUI_SECRET_KEY` из
  секрет-хранилища), `jupyterhub` (конфиг `ops/compose/jupyterhub/`) —
  pinned-образы, healthcheck, resource limits, без секретов в compose;
* **профиль prod**: `clickhouse.{enabled,host,http_port,…}`,
  `jupyter_hub.{enabled,base_url}`; `waf.allow_hosts` += clickhouse,
  jupyterhub (иначе outbound-клиенты блокировались бы strict-allowlist'ом);
* **гейт `tools/check_infra_readiness.py`** (`make infra-readiness`):
  fail-closed проверка **конфигурации** всех 6 пунктов чек-листа (JWKS https,
  режим снапшота `service-role` + DSN, ClickHouse, OpenWebUI + согласованность
  `fallback_chain`, JupyterHub, `database.replica_dsn`). Секреты в Vault →
  предупреждение, небезопасное значение → падение.

**За владельцем остаётся развёртывание** (ключи в `docs/ops/infra-release-checklist.md`):
keypair + JWKS-сервис (https), роль БД `snapshot_service` + DSN снапшота,
ClickHouse/OpenWebUI/JupyterHub в кластере, `DB_REPLICA_DSN` (null допустим).

### 2.4. Мутационный гейт: fail-closed (ADR-0452, доработка)

Найдено 7 дефектов, из-за которых «зелёный» гейт мог означать «прогон не
состоялся»: fail-open на устаревших stats-файлах, стирание кэша вердиктов
(`rsync --delete` по `mutants/**/*.meta`), вызов бинарника из PATH, тихий
fallback при битом baseline, CI-шаг без таймаута, сломанная обёртка под
mutmut 3.x, нулевой score без тестов.

Контракт гейта: **0 = PASS, 1 = FAIL, 2 = SKIPPED (с причиной), 3 = ERROR**.
Порог берётся из `.baselines/mutation.json`. SKIPPED не маскируется под PASS.

### 2.5. Coverage: перемер (ADR-0453)

Grouped-прогон переведён в канонический CI-режим (`-n 2 --dist loadfile` —
на dev-box 4 воркера давали OOM). Перемер: **77.68 %** line-rate (branch 75 %).
Baseline приведён к метрике гейта: прежние 74 % были branch-числом, а гейт
сравнивает line-rate из `coverage.xml` — baseline и гейт мерили разное.

### 2.6. CI-режим: найден корень падения polars

`_module_installed("polars")` возвращал `False`, когда в `sys.modules` лежал
stub без `__spec__` (`find_spec` бросает `ValueError`): cleanup считал, что
пакет «не установлен», и сносил его подмодули → следующий ленивый импорт
`polars.lazyframe` начинал циклический импорт и падал с
`ImportError: cannot import name '_is_generator'`. Исправлено: поиск по
`sys.path` через `PathFinder` + кэш полного графа polars один раз на воркер.

---

## 3. Что осталось за владельцем

| # | Позиция | Что нужно | Влияние |
|---|---|---|---|
| 1 | **Развёртывание инфры** (6 действий) | keypair+JWKS (https), роль БД + DSN снапшота, ClickHouse, OpenWebUI, JupyterHub, `DB_REPLICA_DSN` | без ключа/секрета сервисы не поднимаются; `make infra-readiness --strict` покажет блокирующие пункты |
| 2 | **Аутентификация JupyterHub** | заменить `DummyAuthenticator` на корпоративный IdP (OIDC/LDAP) до публикации порта | иначе вход без пароля |
| 3 | **3 контракта `services → dsl`** | решение по матрице слоёв (перенос `BaseProcessor` в core) или принятие как постоянной | гейт не растёт, но долг ≠ 0 в абсолютных числах |
| 4 | **Mutation-гейт в CI** | отдельный job с таймаутом ~15 мин **или** кэш `mutants/` между прогонами | сейчас CI даёт SKIPPED (честно, но не enforcement) |
| 5 | **Allowlist CVE без даты ревью** | 5 PYSEC-записей (2026-10-15) — дата ревью, severity, обоснование | риск «забытых» advisory |
| 6 | **Scope-optional capability в route-гейте** | гейт проверяет scope только для scope-required capability | `function.call`-подобные capability могут быть объявлены с неполным scope (тест на покрытие scope есть) |
| 7 | **Платформенный scope по БД** | сверка поведения на SQLite/Oracle vs PG с RLS | фоновые потоки различаются по окружениям |

---

## 4. Проверки волны 34

| Проверка | Результат |
|---|---|
| `pytest tests/unit -q --timeout=120 -n 2 --dist loadfile` | **24 328 passed, 0 failed**, 159 skipped, 52 xfailed, 48 xpassed (597 с) — `.run/wave34-logs/reg_ci_r4.txt` |
| `tools/check_layers.py` | 0 новых нарушений; долг **0**, контракты 3 — `tools/check_layers.py --strict` → 3 |
| `tools/check_decorative_capabilities.py` | 0 новых (долг 0) |
| `tools/check_route_capabilities.py` | OK (роутов 7, плагинов 12) |
| `tools/check_docstrings.py` | 0 missing (2600 файлов) |
| `ruff check` / `ruff format --check` | чисто по изменённым файлам (79 файлов в репозитории требуют форматирования — **pre-existing**, вне волны) |
| `mypy -p src` | 12 ошибок = baseline (`.baselines/mypy.json`), регрессий нет |
| `tools/check_coverage_gate.py --strict` | PASS: 77.68 % ≥ 70 % (baseline 77.68 %) |
| `tools/checks/check_mutmut.py --timeout 1500` | **PASS: 21.6 %** (холодный прогон, killed 247 / total 1142) — см. §4.1 |
| OpenAPI | 447 путей — не изменилось |

### 4.1. Мутационный baseline: переподтверждён холодным прогоном

Baseline **21.6 %** подтверждён холодным прогоном (пустая рабочая копия
`mutants/`, без кэша вердиктов): killed 247 / total 1142 = **21.6 %** → гейт
PASS.

Промежуточное расхождение (17.5 %) оказалось **артефактом измерения**, а не
регрессией покрытия: прогон шёл на устаревшей копии `mutants/`, а фаза
«clean tests» падала — двойной сбор модуля tenant-фильтра в рабочей копии
mutmut'а давал «Table 'am_plain' is already defined» (одинаковое имя таблицы
при повторном объявлении в том же MetaData). Исправлено уникальным именем
таблицы; после этого холодный прогон воспроизводит baseline точно.

---

## 5. Документы волны 34

* ADR: `docs/adr/0456-engine-wide-capability-enforcement.md`,
  `docs/adr/0457-extension-resource-registry.md` (+ обновлены 0449–0455);
* `docs/roadmap/OWNER_TASKS.md` §19 — что закрыто;
* `docs/ops/infra-release-checklist.md` — состояние инфры + пункт 12 (гейт);
* `docs/MUTATION_BASELINE.md` — переписан (был устарел на 2026-06-04);
* Логи: `.run/wave34-logs/reg_ci_r4.txt` (регрессия),
  `.run/coverage-baseline-2026-11-17/` (coverage),
  `.run/wave34-logs/mutmut_w34*.txt` (мутации).

---

## 6. Как мерить прогресс (метрики волны 35)

| Метрика | Цель | Сейчас | Источник |
|---|---|---|---|
| Регрессия `tests/unit` (CI-режим) | 0 failed | **0 failed** (24 328 passed) | `.run/wave34-logs/reg_ci_r4.txt` |
| Долг межслойных нарушений | 0 | **0** (+3 контракта) | `tools/check_layers.py --strict` |
| Enforcement capability | движок | ✅ движок (ADR-0456) | `dsl/engine/capability_guard.py` |
| Coverage (line-rate) | ≥ 75 % | **77.68 %** | `.baselines/coverage.json` |
| Mutation score | ≥ baseline | **21.6 %** = baseline (холодный прогон) | `.baselines/mutation.json` |
| Декоративные capability-декларации | 0 | 0 | `tools/check_decorative_capabilities.py` |
| Открытые инфра-действия | ≤ 6 | 6 (за владельцем) | `docs/ops/infra-release-checklist.md` |
