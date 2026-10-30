# PROD_READINESS_GAPS — 2026-09-14 (обновлено)

> Реестр позиций, не позволяющих заявить «ГОТОВ К ПРОДУ» без оговорок, либо
> требующих внешних условий. Каждая: owner, тип, причина, минимальный шаг,
> done-criterion, риск, срок. Метод/evidence: `CURRENT_BASELINE.md`,
> `FUNCTIONAL_TEST_REPORT.md` (2026-09-11), `repository-navigation-audit.md`.

## G1. Coverage sweep на	dev-box не достигает ≥70% объединённо

- **Тип**: test-infra. **Owner**: platform-team (QA-инфра).
- **Причина**: полный unit-набор (17.5k тестов) под coverage требует >2 ч
  последовательного прогона на dev-box; чанки >25 мин нестабильны (timeout-kill
  терял данные appends); часть suite'ов (perf, chaos, e2e) по определению
  исключена. Замер этой сессии — см. CURRENT_BASELINE (комбинированный
  coverage.xml + gate).
- **Шаг**: CI-runner с `pytest -n auto --cov` (parallel=true уже в pyproject) +
  единый `coverage combine` на CI; локальные чанки — только для диагностики.
- **Done**: coverage.xml с CI ≥70%, gate strict PASS в pipeline.
- **Риск**: локальные числа невоспроизводимы → возможен дрейф вниз без сигнала.
- **Срок**: следующий спринт.

## G2. Push load SLO p99<300ms @300 VU — не измерен на prod-like host

- **Тип**: infra. **Owner**: perf-team + infra.
- **Причина**: dev-box не воспроизводит prod-контенцию; reference 444 RPS /
  p99 150ms есть (LOAD_TEST_RESULTS_2026-09-05), push-профиль требует выделенного
  хоста с prod-yaml.
- **Шаг**: прогон locust-профиля 300 VU на pre-prod стенде.
- **Done**: отчёт с p99 <300ms либо формальный SLO-exception с владельцем.
- **Риск**: неизвестный p99 под пиками → SLA-риск на приёме.
- **Срок**: до приёма в prod.

## G3. R2.DEPS-3: 34 outdated, из них MAJOR-цепочки с родительскими пинами

- **Тип**: dependency. **Owner**: platform-team.
- **Причина**: цепочки aio-pika→aiormq→pamqp, elasticsearch→elastic-transport,
  protobuf/thinc/deepeval, rich→textual, redis 5→8, mypy 1→2 требуют
  скоординированных миграций; patch-хвост (googleapis-common-protos,
  presidio-anonymizer, python-semantic-release) заблокирован родительскими пинами.
- **Шаг**: волнами по одной цепочке: `uv lock --upgrade-package` + прогон
  доменных suite'ов + коммит. Начать с redis 5→8 (наибольший security-хвост).
- **Done**: outdated ≤30 либо каждая позиция с ADR-планом (текущий документ —
  временная ADR-замена).
- **Риск**: накопление security-debt; redis 5.x EOL-окно.
- **Срок**: 2 спринта.

## G4. SOAP business invoke — ✅ ЗАКРЫТО (2026-09-11, `49d929b05`)

- **Тип**: code (P2). **Owner**: entrypoints-team. **Статус**: закрыт.
- **Корень**: `create_app()` никогда не вызывал `register_app_state()` —
  `app.state.invoker` (и reply_registry/vault_refresher) не заполнялись;
  SOAP-роут объявляет `Depends(get_invoker_dep)` → AttributeError в
  dependency-solve → 500 (маскировался CancelledError-шумом очистки
  aiosqlite-сессии, что уводило три раунда диагностики в сторону).
- **Фикс**: вызов `register_app_state(app)` в `_configure_application_components`
  (guarded, как остальные шаги композиции).
- **Live-верификация**: `POST /soap/invoke` с конвертом InvokeRequest
  (action=users.list) + JWT → **200**, `status=ok`, result присутствует;
  незарегистрированная операция → **404 SOAP Fault** (протокольно-корректный
  ответ); forged token → 401.
- **Косметика в backlog**: результат list-экшнов сериализуется через str()
  ORM-объектов — применить _jsonable-нормализацию из auto_register в
  Invoker-сериализации.
- **Шаг**: (1) локализовать cancel-scope (трассировка `anyio.CancelScope.cancel`);
  (2) решить семантику: honest 504/SOAP-Fault при отмене + запрет кидать отмену
  поверх незавершённой DB-транзакции.
- **Done**: `/soap/invoke` с валидной операцией → 200 SOAP-response (или корректный
  SOAP Fault без потери JSON-обёртки).
- **Риск**: SOAP-потребители получают opaque 500; отмена поверх транзакции.
- **Срок**: следующий спринт.

## G5. gRPC business dispatch: мост готов (2026-09-11), остались контракты proto

- **Тип**: code/feature. **Owner**: entrypoints-team. **Статус**: частично закрыт `c348cee87`.
- **Сделано**: RPC auto-доменов более не падают UNIMPLEMENTED NotImplementedError —
  мост `auto_servicer._make_dispatch_behavior` диспетчеризует в
  `dispatch_action("<domain>.<rpc>", source="grpc")` (алиас create→add,
  data-wrap для CRUD, dict→ParseDict). Live-verified: transport → AuthInterceptor
  → регистрация экшнов (добавлена в standalone serve) → dispatch → сервис → БД.
- **Остаток**: (а) proto-стабы lossy — `Get(EmptyRequest)` без id, списки не
  маппятся в single-message, `UserSchemaIn` не несёт обязательные поля
  (SecretStr→Any) — нужна **регенерация proto v2** из JSON-schema экшенов;
  (б) standalone `InvokerGRPCServicer.Invoke` — `get_invoker` DI требует
  app_state, которого в standalone нет (нужен composition-бридж).
- **Done**: (а) proto v2 сгенерированы, Get/List/Create с полным фиделити;
  (б) Invoke в standalone отвечает данными.
- **Риск**: gRPC-потребители имеют транспорт+auth, но бизнес-вызовы через
  авто-домены ограничены; полный обходной путь сегодня — REST/auto.
- **Срок**: следующий спринт.

## G6. MQ-протоколы (Kafka/Rabbit/Redis Streams) — BLOCKED(infra)

- **Тип**: infra. **Owner**: infra + QA.
- **Причина**: брокеры недоступны на dev-box (docker-socket permission,
  M6-#3); подписчики/паблишеры код-верифицированы unit-тестами, live
  producer-consumer не прогонялся в этой сессии.
- **Шаг**: поднятие compose-профиля на CI-runner с docker; прогон
  smoke-сценариев из `tests/integration`.
- **Done**: FUNCTIONAL_TEST_REPORT-строки Kafka/Rabbit/Redis Streams = PASS.
- **Риск**: контрактные regression между версиями брокеров не ловятся.
- **Срок**: вместе с G2 (один стенд).

## G7. MCP HTTP mount default-OFF; MCP серверная часть не верифицирована live

- **Тип**: config/test. **Owner**: ai-team.
- **Причина**: `mcp.http_enabled=false` (default, D-AUDIT-20810) — по дизайну;
  live-проверка MCP tool-call требует подъёма с флагом + auth-конфигурации.
- **Шаг**: dev-профиль с http_enabled=true; smoke: tools/list + restricted call.
- **Done**: матрица MCP = PASS (или явное решение «только stdio-транспорт»).
- **Риск**: низкий (фича off by default).
- **Срок**: по плану ai-team.

## G8. Documentation accuracy: мета-доки с битыми ссылками и противоречиями

- **Тип**: docs (P1, частично исправлено). **Owner**: docs-owner.
- **Исправлено 2026-09-11**: README-пути `/events` и `/webhooks`; navigation
  audit зафиксировал расхождения.
- **Осталось**: CLAUDE.md — 4 битых пути (PLAN.md, /root/.claude/plans/…,
  gap-analysis/, graphify-out/wiki/); mkdocs nav `api/` (каталог не существует);
  README «114 actions» vs ARCHITECTURE «35+ actions»; двойная нумерация
  спринтов в AGENTS.md; дубли docs/workflow|workflows, docs/migration|migrations.
- **Шаг**: волна doc-fix по §8 navigation audit (каждая правка — атомарный
  commit; числа — только из `manage.py` inventory).
- **Done**: 0 битых путей в CLAUDE.md/mkdocs nav; согласованные числа actions.
- **Риск**: AI-агенты/новые разработчики ориентируются на «источник правды»,
  которого не существует.
- **Срок**: следующий спринт.

## G9. 8 S20-scaffold pre-prod gates в WARN (требуют прод-трафика)

- **Тип**: test-infra. **Owner**: SRE.
- **Причина**: semantic-cache hit-rate, RCA и др. — warn-only до появления
  прод-трафика; не кодо-дефекты.
- **Шаг**: переключение gate в enforcing после 2 недель трафика.
- **Done**: 33/36 PASSED enforcing.
- **Риск**: отсутствует (осознанный scaffold).
- **Срок**: post-production.

## G10. Navigation debt (CONSOLIDATE/DEPRECATE/DELETE-кандидаты)

- **Тип**: architecture. **Owner**: architecture-team.
- **Причина**: полный список — navigation audit §8: байт-в-байт дубль
  `core/services/base_external_api.py` (0 импортёров), тройная терминология
  plugin, тройной дубль AI-процессоров, runtime-dead `entrypoints/email|scheduler`,
  `dsl/setup.py`, `audit_versioning.py`.
- **Шаг**: волнами per navigation-audit verdicts; удаление — только после
  полного static+dynamic proof и в новом release cycle.
- **Done**: 0 CONSOLIDATE-пар с живыми потребителями по обе стороны.
- **Риск**: дубли расходятся поведением → скрытые баги (прецедент —
  create_task-контракт в этой сессии).
- **Срок**: 2-3 спринта.

## G11. DSN-драйверы вне extras: `pyodbc` (MSSQL sync), `ibm_db_sa` (DB2)

- **Тип**: dependency. **Owner**: platform-team.
- **Статус**: 🟡 ЧАСТИЧНО ЗАКРЫТ (2026-10-28, гриллинг раунд 2, Q2 —
  согласовано владельцем, lock-чанж выполнен).
- **Причина**: DSN-конструкторы (`core/config/database.py`) упоминали
  `pyodbc` и `ibm_db_sa`, но они не были объявлены ни в `[project.dependencies]`,
  ни в одном extra — сборка DSN падала бы в рантайме как
  `ModuleNotFoundError` внутри SQLAlchemy. Дополнительно: `psycopg`
  (новый дефолт sync-драйвера PostgreSQL) объявлен в extra `sources-cdc`,
  а не в `db_drivers`; `aiosqlite` — в `dev-light`/test-extra'ах, не в core.
- **Закрыто**: `clickhouse-connect>=0.7.0,<1.0.0` и `pyodbc>=5.0.0,<6.0.0`
  объявлены в extra `db_drivers` (`pyproject.toml:216-217`), lock обновлён
  (`uv lock` → 681 пакет, `uv lock --check` — зелёный); allowlist'ы очищены
  (`check_declared_dependencies` 78 → 77 записей, `check_dsn_drivers` — только
  `ibm_db_sa`); `DB_DRIVER_DECLARATIONS` дополнен `pyodbc`/`clickhouse_connect`;
  DSN MSSQL sync теперь собирается: `mssql+pyodbc://sa:P%40ssw0rd@host:1433/db`.
  Гейт `tools/check_dsn_drivers.py` получил разделение scope: в CI блокирует
  только класс «драйвер не объявлен» (`--scope declarations`), availability
  требует установленных extras и не блокирует.
- **Осталось**: `ibm_db_sa` — проприетарный пакет (требует установки IBM DB2),
  в публичных extras недоступен → остаётся в allowlist. `psycopg[binary]`
  объявлен в `sources-cdc`, а не в `db_drivers`: prod-образ без этого extra
  деградирует sync-движок в `None` + warning; перенос — отдельное решение
  (увеличивает образ).
- **Риск**: MSSQL/DB2 нельзя сконфигурировать без ручной установки драйвера;
  в compose-образе (`--extra dev-light`) `oracledb`/`aioodbc`/`aiomysql`
  тоже отсутствуют.
- **Срок**: закрыто для `pyodbc`/`clickhouse-connect`; `ibm_db_sa` — Sprint 36+.

---

## G12. Capability-декларации процессоров не проверяются в рантайме

- **Тип**: security-архитектура. **Owner**: platform-team + владелец
  авторизации.
- **Статус**: 🟡 ЗАФИКСИРОВАН, ПОЧИНКА ОТЛОЖЕНА (ADR-0361, гриллинг раунды 1–2).
- **Причина**: `BaseProcessor.auth_check` ведёт в синхронный
  `AuthorizationGateway.check`, где единственный allow-источник — exact
  in-memory policy (в проде пусто), sync-хуки Casbin/OPA отсутствуют (есть
  только async `casbin_step`/`opa_step`), а `CapabilityGate.check` в этом пути
  не вызывается → **deny для любого** `required_capability` (41+ процессоров).
  Runtime-проверка: `allowed=False, reason='policy denied: read'`; контрольный
  эксперимент — после `add_policy("anonymous","read","rpa.file.list","allow")`
  → allow.
- **Что сделано в Wave 13**: capability-охват НЕ расширялся (добавление
  `required_capability` сломало бы процессор); риски закрыты доменными
  guard'ами (ADR-0359) и path-allowlist (ADR-0358); декларативность
  зафиксирована гейтом `tools/check_decorative_capabilities.py` (baseline 45).
- **Шаг (отдельный ADR + владелец)**: кандидаты — единый app-level gateway с
  OPA/Casbin в processor-пути; либо sync-реализация `_casbin_check`/`_opa_check`;
  маппинг principal→plugin НЕ рекомендуется (открывает 71 core-capability для
  `principal=anonymous`).

---

## GAP-WF-4.5. SLA-алертинг workflow не реализован (`SlaTracker` мёртв)

- **Тип**: code (P1). **Owner**: K3 DSL+Workflow.
- **Статус**: 🟡 ЗАФИКСИРОВАН (волна 20, инвентаризация кластера W5).
- **Причина**: класс `SlaTracker`
  (`src/backend/services/workflows/sla_alerting.py`) существует, но **не
  инстанцируется нигде в `src/`** — ни в `lifespan`, ни в worker'ах, ни в
  composition root. `WorkflowFacade` принимает `sla_tracker` только как
  опциональный параметр, а сам фасад в `src/` не создаётся. Email/Slack-
  эскалация по `soft_limit_seconds` / `hard_limit_seconds` в рантайме не
  работает.
- **Шаг (требует владельца)**: зарегистрировать `WorkflowFacade` (+
  `SlaTracker`) в composition root **либо** удалить класс и опциональный
  параметр фасада. Документация не может закрыть позицию: отсутствие
  инстанцирования — следствие неполной интеграции сервисного слоя.
- **Done**: `SlaTracker` инстанцируется в composition root **или** класс
  удалён; утверждение в
  [runbook'е HITL](../runbooks/hitl-stuck-workflow.md) соответствует коду.
- **Сводка**: [OWNER_TASKS.md](OWNER_TASKS.md) § 8.

---

## Обновление 2026-09-14 (волны 6–9)

| Изменение | Коммит |
|---|---|
| G4 SOAP invoke → ✅ ЗАКРЫТ (underscore→dot + type coercion) | `1d93316aa` |
| G5(b) standalone Invoke → ✅ (state bootstrap + get_invoker fix) | `a6730dced` |
| P0 bootstrap-admin (reference-only seed) → ✅ | `e7ab9aeba` |
| OP-3/OP-6 гейты → blocking CI jobs | `d201251ba` |
| CVE-diff в SBOM gate | `619040c6c` |
| Contract matrix (action × REST/gRPC/SOAP) | `35f06b299` |
| Write-CRUD восстановлен (ServiceHelper) | `a6730dced` |
| auth_login admin_roles claim | `817eff4c1` |
| Temporal runtime app fix | `5ee45d8db` |

Оставшиеся инфраструктурные: G1/G2/G6 — требуют CI-runner, prod-стенд, брокеры.
Оставшиеся кодовые: G5(a) proto v2 (backlog), G8 docs хвост (backlog), G10 nav debt (backlog).
