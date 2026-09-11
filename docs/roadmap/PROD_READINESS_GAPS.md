# PROD_READINESS_GAPS — 2026-09-11

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

## G4. SOAP business invoke — 500 на валидных WSDL-операциях

- **Тип**: code (P2). **Owner**: entrypoints-team.
- **Причина**: `/soap/invoke` с зарегистрированной операцией (`orderkinds_list`)
  возвращает 500; в трейсе — CancelledError на aiosqlite-сессии (path
  dispatch → invocation bridge). WSDL и auth — PASS; сломан именно dispatch.
- **Шаг**: воспроизвести in-process с ToolClient/ASGITransport на
  testserver-хосте, восстановить конверсию исключений dispatch → SOAP Fault.
- **Done**: `curl -H auth -d envelope` → 200 SOAP-response или корректный
  SOAP Fault (не 500) для известных операций.
- **Риск**: SOAP-потребители получают opaque 500 вместо Fault — диагностика
  на стороне клиента невозможна.
- **Срок**: следующий спринт.

## G5. gRPC business dispatch: auto-servicer'ы абстрактные

- **Тип**: code/feature (P2). **Owner**: entrypoints-team.
- **Причина**: standalone `grpc-serve` поднимает 3 явных servicer'а + 4
  auto-servicer'а; auth-интерцептор PASS (neg+pos). Но RPC auto-доменов
  (users/orders/orderkinds/files) доходят до сгенерированных абстрактных
  методов → UNIMPLEMENTED `NotImplementedError`. Мост
  auto-servicer → ActionDispatcher не реализован.
- **Шаг**: в `auto_servicer.register_auto_servicers` привязать behavior к
  `dispatch_action(action=<domain>.<rpc>, source="grpc", ...)` вместо методов
  сгенерированного базового класса.
- **Done**: grpcio-клиент `List/Get` с валидным api-key получает данные.
- **Риск**: gRPC-потребители (compose-сервис) не имеют бизнес-API.
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
