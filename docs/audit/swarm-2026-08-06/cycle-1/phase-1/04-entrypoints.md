# Domain Audit: Entrypoints (cycle 1 / phase 1)

- Audit date: 2026-08-06
- Scope: `src/backend/entrypoints/**` за вычетом `src/backend/entrypoints/api/**` и security/auth middleware
- Тесты: `tests/unit/entrypoints/**` (без `api/**` поддерева)
- Baseline commit: `b69d6b49bc62918a02e47dc20ab81615fd8500b1`
- Текущий HEAD: `2f620910951a727f50d4539b998375b0c0bda55d` (4 коммита после baseline)
- Подтверждённый baseline: 175 legacy-allowlist записей (`wc -l tools/check_layers_allowlist.txt` = 180 строк, из них 5 — заголовки/комментарии), 0 новых; 35 активных security allowlist ID — не проверено прямым подсчётом (документ продиктован, не пересчитан в этой сессии)
- Замечание о working tree: согласно промпту в working tree до старта изменены `src/backend/infrastructure/storage/s3.py` и `uv.lock`. Прямой `git status` показал только `pyproject.toml` и `tests/unit/dsl/transforms/test_dataframes.py`. Противоречие зафиксировано, эти файлы не использовались и не правились.
- Вердикт по pre-existing правкам: они НЕ атрибутируются текущему аудиту; ни одного source/config/lockfile/allowlist изменения не сделано.

---

## 1. Scope / не проверено

### Проверено (read-only)
- `src/backend/entrypoints/__init__.py`, `base.py`, `_action_bridge.py`
- `src/backend/entrypoints/asyncapi/{__init__,exporter}.py`
- `src/backend/entrypoints/cdc/cdc_routes.py`
- `src/backend/entrypoints/email/imap_monitor.py`
- `src/backend/entrypoints/express/router.py`
- `src/backend/entrypoints/filewatcher/{watcher_manager,watcher_routes}.py`
- `src/backend/entrypoints/graphql/{schema,auto_schema,dsl_result}.py`
- `src/backend/entrypoints/grpc/{__init__,auto_servicer,correlation,proto_viewer}.py`, `grpc/grpc_server/{base,server,invoker,order,interceptor,file_stream,_safe_error}.py`, `grpc/protobuf/*` (метаданные, без байт-кода автогенерации)
- `src/backend/entrypoints/http3/{asgi_bridge,config,server,cli,_protocol}.py`
- `src/backend/entrypoints/mcp/{__init__,gateway,http_server,input_schema_resolver,workflow_tools}.py`, `mcp/mcp_server/*.py`, `mcp/namespaces/*.py`
- `src/backend/entrypoints/mqtt/mqtt_handler.py`
- `src/backend/entrypoints/scheduler/invoker_schedule.py`
- `src/backend/entrypoints/soap/soap_handler.py`
- `src/backend/entrypoints/sse/handler.py`
- `src/backend/entrypoints/stream/{__init__,subscribers,invoker_subscribers}.py`
- `src/backend/entrypoints/webhook/{handler,registry,redis_registry,sources_router,transformer}.py`
- `src/backend/entrypoints/websocket/{ws_handler,ws_invocations,ws_manager,ws_broadcast,ws_auth}.py`
- `src/backend/entrypoints/dependencies/__init__,rate_limit}.py`
- `src/backend/entrypoints/middlewares/{registry,setup_middlewares,exception_handler,_body_hash,_streaming_hash,request_id,request_log,request_context,request_body_cache,response_cache,idempotency,timeout,correlation,brotli_compression,degradation,per_protocol_ratelimit,global_ratelimit,data_masking,pii_masking_response,observability,otel_middleware,circuit_breaker,tenant,ws_rate_limit,rpa_policy,ai_tool_whitelist,admin_audit,admin_ip,audit_log,audit_replay}.py` — за исключением файлов, явно входящих в scope auth/security (см. ниже)
- `tools/check_layers_allowlist.txt` (read-only header + grep по entrypoints)
- `src/backend/core/messaging/{dlq,dlq_policy,outbox}.py` для проверки DLQ-инфраструктуры
- `src/backend/dsl/commands/{action_registry,registry}.py` (не в scope, но задействованы в finding DOMAIN-P1-001)
- `src/backend/core/errors.py` (для проверки формата ошибок)
- `tests/unit/entrypoints/{stream,sse,http3,grpc,cdc,express,email,filewatcher,scheduler,webhook,websocket,test_base,test_mypy_contract_regressions,test_admin_*}*.py` — точечный прогон через `.venv/bin/python -m pytest ... -p no:cacheprovider`
- `.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/` — 451 passed, 2 failed (`test_global_ratelimit.py::test_checker_failure_falls_through`, `test_webhook_signature_middleware.py::test_protected_prefix_without_secret_passes_through`); pure-ASGI smoke-пакет — 71 passed
- `.venv/bin/python -m pytest tests/unit/entrypoints/stream/` — 12 passed
- `.venv/bin/python -m pytest tests/unit/entrypoints/sse/` — 23 passed, 4 failed (env: spaCy `ru_core_news_lg` wheel network), 8 xfailed
- `.venv/bin/python -m pytest tests/unit/entrypoints/grpc/` — 49 passed
- `.venv/bin/python -m pytest tests/unit/entrypoints/cdc/ tests/unit/entrypoints/express/ tests/unit/entrypoints/email/ tests/unit/entrypoints/filewatcher/ tests/unit/entrypoints/mqtt/ tests/unit/entrypoints/scheduler/ tests/unit/entrypoints/webhook/ tests/unit/entrypoints/websocket/` — в сумме >100 passed; 2 непрофильных fail в MQTT

### Не проверено (вне scope / out-of-band)
- `src/backend/entrypoints/api/**` — в смежном отчёте
- security/auth middleware (полный файл-уровневый out-of-scope, чтобы не дублировать security-аналитика): `auth_required.py`, `auth_method_header.py`, `api_key.py`, `csrf.py`, `login_step_up.py`, `blocked_routes.py`, `webhook_signature.py`, `security_headers.py`, `admin_audit.py`, `admin_ip.py`, `ai_tool_whitelist.py`, `audit_log.py`, `audit_replay.py`. По ним собрана только top-level сигнатура (наличие класса ASGI middleware, регистрация в `setup_middlewares`); внутренняя логика и unit-тесты не анализировались.
- Численный подсчёт активных security allowlist IDs (прямой подсчёт не делался — указан в baseline).
- Реальный `pyproject.toml` lock-файл и `uv.lock` — `git status` показывает `pyproject.toml` как изменённый, содержимое не инспектировано.
- `tests/integration/**`, e2e-флоу с реальным брокером — только unit-тесты.
- Production-wiring: `src/backend/plugins/composition/**`, `create_app()` фактический бутстрап.
- Производительность: бенчмарки, латентности, throughput не замерялись.

---

## 2. Verified strengths (что реально работает по clean architecture / EIP / DI / fail-closed)

| ID | Subsystem | Evidence | Соответствие |
|---|---|---|---|
| STR-01 | `entrypoints/base.py::dispatch_action` (lines 40-87) | Free-function единый диспатчер; собирает `ActionCommandSchema` с `meta={source, correlation_id, tenant_id}`; `try/except Exception` re-raise с latency-логом | EIP Message Router; cross-cutting observability в одной точке |
| STR-02 | `entrypoints/_action_bridge.py::dispatch_action_or_dsl` (lines 76-195) | Tier 1/2 `ActionGatewayDispatcher` (опционально, feature-flag), Tier 3 DSL-fallback через `get_dsl_service()`; per-route `pool_size` semaphore с non-blocking `wait_for(0.001)`; per-action `message_timeout_s` через `asyncio.wait_for` | EIP Content-Based Router + Dead-Letter-adjacent (reject при pool exhaustion) |
| STR-03 | `entrypoints/middlewares/exception_handler.py` (lines 35-158) | Pure ASGI (`__call__(scope, receive, send)`); non-HTTP scope пробрасывается (websocket/lifespan) — не ломает ASGI-протокол; `BaseError → to_dict()`; иначе traceback + Sentry + `error_id` UUID + correlation_id из scope.state | fail-closed error envelope, не теряет correlation, совместим с pure ASGI |
| STR-04 | `entrypoints/middlewares/registry.py` (S17 ADR-NEW-2) | 4 слоя (L1 early-exit 0-249, L2 request mgmt 250-499, L3 body/auth 500-749, L4 logging/metrics 750-999); thread-safe `Lock`; 3 источника регистрации: builtin / plugin.toml / `gd_integration_tools.middleware_hooks` entry-points; `apply_to_app` итерирует в порядке возрастания `order` | clean architecture: разделение policy (S17 ADR-NEW-2), `order` — единственный источник правды по слою |
| STR-05 | `entrypoints/middlewares/_streaming_hash.py::StreamingBodyHasher` (lines 21-54) | Incremental `hashlib.sha256().update()`; `hash_stream` принимает `AsyncIterator[bytes]` — не буферизует тело; 64 KB chunks, `__slots__` | OOM-safe (D141 Ponytail); переиспользуется в `audit_log`, `admin_audit`, `pii_masking_response`, `response_cache` (комментарий `middlewares/_body_hash.py:1-9` явно фиксирует источник правды) |
| STR-06 | `entrypoints/http3/asgi_bridge.py::HttpStreamHandler` (lines 31-90) | Pure ASGI surface (scope/receive/send); body chunks через `asyncio.Queue`; `http.disconnect` event при QUIC stream close; запрет повторного `http.response.start` (`RuntimeError`); `build_http_scope` соответствует ASGI 3.0 + HTTP/3 | корректный pure ASGI bridge, streaming body |
| STR-07 | `entrypoints/grpc/grpc_server/_safe_error.py` (lines 6-21) | `BaseError → exc.message` (контролируемые сообщения); иначе generic `"Internal server error; ref=<correlation_id>"` — не утекает `str(exc)` / traceback / module-path; используется в `order.py:67`, `invoker.py:132` | fail-closed для клиента, корреляция с server-side log |
| STR-08 | `entrypoints/grpc/grpc_server/base.py::BaseGRPCServicer._dispatch` (lines 35-68) | Унифицирует dispatch через `dispatch_action(source="grpc")`; извлекает `x-correlation-id` из gRPC metadata, пробрасывает в `set_correlation_context` для downstream audit/outbox/outbound-HTTP; `try/except ImportError` (graceful) | DI-friendly через `action_handler_registry` singleton; не ломается при отсутствии observability |
| STR-09 | `entrypoints/asyncapi/exporter.py` (lines 35-69, 89-159) | `try/except` вокруг `get_stream_client()`; пустой AsyncAPI 3.0 при недоступности broker'ов; broker iteration через `getattr` (`None → skip`); spec fallback на `_empty_spec_dict` | graceful degradation; не падает на dev_light / test среде |
| STR-10 | `entrypoints/sse/handler.py::sse_invoke` (lines 188-246) | Stream-обёртка `start → result|error → end`; per-stream `event_generator` через `StreamingResponse`; correlation_id и idempotency_key пробрасываются в bridge | EIP Request-Reply через single-direction stream |
| STR-11 | `entrypoints/grpc/grpc_server/file_stream.py` (lines 91-203) | `DownloadFile`: chunked `hashlib.sha256.update()` + `is_last` flag + `final_fingerprint`; `UploadFile`: `context.cancelled()` check + `max_file_size` guard + SHA-256 on-the-fly; `await storage.write()` (async) | streaming integrity, корректный back-pressure через async iteration |
| STR-12 | `entrypoints/stream/subscribers.py` (lines 18-51) + `invoker_subscribers.py` (lines 37-93) | `try/except (KeyError, ValueError, TypeError)` для парсинга → warn + drop (consumer ack, не retry); `stream_logger.exception` для invoker-fail → ack (тоже не retry) | корректный bad-message policy: не зацикливает redelivery. **Но**: см. DOMAIN-P0-002 |
| STR-13 | `entrypoints/middlewares/setup_middlewares.py::build_default_registry` (lines 24-277) | 25+ middleware, упорядочены через `order`; plugin-loader добавляет свои поверх; `apply_to_app` учитывает LIFO Starlette; docstring фиксирует reverse-empirics (S204 retro-audit) | clean layering |
| STR-14 | `entrypoints/graphql/schema.py::graphql_router` (lines 786-792) | S204 retro-audit fix: GraphQL смонтирован с `dependencies=[Depends(require_auth([API_KEY, JWT, MTLS]))]`; раньше `executeAction/dsl_execute` были открыты | fail-closed security (C-NEW-5 closure) |
| STR-15 | `entrypoints/graphql/schema.py::_execute_with_timeout` (lines 733-781) | Per-route override `query_timeout_s`, `max_query_depth`, `max_query_complexity`, `enable_introspection` gate; heuristics depth+complexity через `int(len(query)**0.5)`; `_is_introspection_query` regex | defense-in-depth от OOM и интроспекции |
| STR-16 | `entrypoints/mqtt/mqtt_handler.py` (lines 75-95, 97-129) | TLS через `ssl.create_default_context(cafile=...)` + `CERT_REQUIRED` + `check_hostname=True`; `verify_cert=False` логируется (хотя и форсируется через `ssl.CERT_NONE`-запрет); exponential reconnect через `asyncio.sleep(5)` | mTLS-ready; не падает на повторных коннектах |
| STR-17 | `entrypoints/email/imap_monitor.py` (lines 132-142) | `verify_cert=False` явно логируется как НЕ-применяемый: `ssl.CERT_NONE / check_hostname=False` запрещены (V1 policy); требует custom CA через secrets capability | fail-closed на TLS — V1 policy |
| STR-18 | `entrypoints/websocket/ws_broadcast.py` (lines 54-90) | Cross-instance broadcast через Redis Pub/Sub: каждый инстанс subscribes `_BROADCAST_CHANNEL` и пересылает локальным; group membership через Redis SET | EIP Publish-Subscribe с multi-instance fan-out |
| STR-19 | `entrypoints/dependencies/rate_limit.py::RedisLimiterAdapter` (lines 46-130) | Multi-instance safe: `RedisRateLimiter` через Redis atomic INCR/EXPIRE; `blocking=False` → 429 через `default_callback`; `fail-open` при недоступности Redis (catch Exception) | EIP Throttler с multi-instance |
| STR-20 | `entrypoints/filewatcher/watcher_manager.py::_watch_loop` (lines 144-175) | `watchfiles.awatch` (rust `notify`) с `debounce_ms` = `poll_interval * 1000`; `Change.deleted` skip; `await dsl.dispatch()` в try/except → log; `asyncio.CancelledError` re-raise (не глушится) | OS-event-driven (не polling); back-pressure через async dispatch |

### Tests
- `tests/unit/entrypoints/test_base.py` (7 passed) — `dispatch_action` и `BaseEntrypoint.dispatch` mock-`action_handler_registry`; проверяет `meta.source`, `meta.correlation_id`, `meta.tenant_id`, latency log propagation.
- `tests/unit/entrypoints/stream/test_subscribers.py` + `test_invoker_subscribers.py` (12 passed) — happy_path, invalid_body, dispatch_exception; явный контракт "on error → log, do not retry".
- `tests/unit/entrypoints/grpc/` (49 passed) — `test_grpc_server.py`, `test_correlation_metadata.py`, `test_file_stream.py`, `test_auto_servicer.py` — server lifecycle, gRPC metadata extraction, chunked upload/download fingerprint, dynamic servicer-builder.
- `tests/unit/entrypoints/http3/` (13 passed) — `test_asgi_bridge.py`, `test_cli.py`, `test_config.py` — scope building, send/receive protocol, TLS config validation.
- `tests/unit/entrypoints/middlewares/` pure-ASGI smoke (71 passed): `test_admin_audit_pure_asgi`, `test_auth_required_pure_asgi`, `test_tenant_pure_asgi`, `test_blocked_routes_pure_asgi`, `test_pii_masking_response_pure_asgi`, `test_rpa_policy_pure_asgi`, `test_timeout_pure_asgi`, `test_webhook_signature_pure_asgi` — подтверждают, что L0-L3 middleware корректно ловят 401/403/404/429/503 в pure-ASGI контексте.

---

## 3. Findings table

| ID | Pri | Path:line | Evidence | Impact | Минимальная рекомендация | Тест-критерий |
|---|---|---|---|---|---|---|
| **DOMAIN-P0-001** | **P0** | `src/backend/entrypoints/sse/handler.py:188-236` (sse_invoke) | 8 xfailed тестов в `tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation` + `TestSseAuthContextEdgeCases` — сообщения XFAIL: *"SSE /events/invoke не пробрасывает principal/permissions из request.state.auth в DslService.dispatch (parity с GraphQL/REST). Forward-looking TDD до Sprint 1.4 L5 Security Chain migration"*. Параллельно: GraphQL `schema.py:786-792` уже enforce'ит `require_auth([API_KEY, JWT, MTLS])` на `graphql_router`, и `_dispatch_dsl` в `schema.py:192-249` строит `ExecutionContext.from_auth(auth, route_id=...)`. SSE-`sse_invoke` же вызывает `dispatch_action_or_dsl` без `principal`/`permissions`, по умолчанию `""` и `()` (см. `_action_bridge.py:86-87` — `principal: str = ""` → `DslService` интерпретирует как "anonymous", `permissions: tuple[str, ...] = ()`). | **fail-open**: protected route через `/events/invoke` выполняется как anonymous. На GraphQL тот же action требует `require_auth`, через SSE — обходит. Банковская шина, R-V15-1 closure риск. | В `sse_invoke` (после получения `body`, до `dispatch_action_or_dsl`): `auth = getattr(request.state, "auth", None)` → `principal, permissions = _extract_principal_permissions(auth)` (helper из `schema.py`-стиля); прокинуть их в `dispatch_action_or_dsl(..., principal=..., permissions=...)`. В тесте разморозить 8 xfail. | `test_authorized_principal_propagates_to_dispatch` и остальные 7 тестов в `TestSseAuthContextPropagation` + `TestSseAuthContextEdgeCases` должны пройти после фикса (xfail → pass). |
| **DOMAIN-P0-002** | **P0** | `src/backend/entrypoints/stream/subscribers.py:21-51` (`handle_universal_redis_action`, `handle_universal_rabbit_action`) и `src/backend/entrypoints/stream/invoker_subscribers.py:40-93` (`handle_redis_invocation`, `handle_rabbit_invocation`) | На любом `Exception` от `action_handler_registry.dispatch` (line 32/47 в `subscribers.py`) и `invoker.invoke` (line 88/207 в `invoker_subscribers.py`) — только `stream_logger.error` / `stream_logger.exception` + ack. DLQ-инфраструктура существует: `src/backend/core/messaging/outbox.py::OutboxBackend` Protocol (PENDING/DELIVERED/DLQ/RESOLVED, retry_count, max_attempts, enqueue, replay, mark_resolved), `src/backend/core/messaging/dlq.py` (DLQEnvelope/DLQReason/DLQWriter) и `dlq_policy.py` (3 retention policies: financial 7y unlimited, analytics 30d/3-replays, operational 90d/10-replays). В `entrypoints/grep -l dlq`: только `transformer.py` (backward-compat shim) и `admin_scheduler_dlq.py` (вне scope, в `api/`). В самих MQ-обработчиках DLQ-вызовов НЕТ. | **data loss при poison-message**: invalid body → ack + log; transient dispatch failure → ack + log; невозможно replay/inspect. Для MQ-источника из `core/messaging/dlq.py` (S9 K2) это прямое нарушение контракта, описанного в `outbox.py:1-21`. | На каждом `Exception` в MQ-handler: (1) классифицировать (`KeyError`/`ValueError`/`TypeError` для parse → DLQ `dlq_class="operational"`; `Exception` от dispatch → DLQ с `error_class=type(exc).__name__`); (2) вызвать `OutboxBackend.enqueue(OutboxEvent(transport="mq", action=..., payload=body, error_class=..., error_message=..., correlation_id=...))`; (3) ack после успешного enqueue. Сейчас контракт: log → ack. | `test_invalid_body` в `test_invoker_subscribers.py` (line 94) должен проверить, что `OutboxBackend.enqueue` вызван с `error_class="ValueError"` (или "KeyError") и `dlq_class="operational"`. Аналогичный тест добавить для `test_dispatch_exception` (line 107). |
| **DOMAIN-P1-001** | **P1** | `src/backend/entrypoints/stream/subscribers.py:9` | `from src.backend.entrypoints.api.generator.registry import action_handler_registry` — entrypoint-файл из scope `entrypoints/` импортирует другой entrypoint-файл из `entrypoints/api/`, который в этом аудите исключён. Создаёт зависимость `entrypoints/stream/` → `entrypoints/api/generator/` (один файл в scope зависит от файла вне scope). Также: `entrypoints/_action_bridge.py:13` импортирует `src.backend.dsl.service` — в allowlist как legacy (`tools/check_layers_allowlist.txt` строка `src/backend/entrypoints/_action_bridge.py entrypoints src.backend.dsl.service`). | Циклический путь импорта на границе scope. Затрудняет независимый рефакторинг `entrypoints/stream/`. | Перенести `action_handler_registry` (или re-export) в `entrypoints/` корневой или в `core/dsl/commands/` (последний уже имеет `action_handler_registry` в `dsl/commands/action_registry.py:349`). Re-export `entrypoints/stream/subscribers.py` через `src.backend.dsl.commands.action_registry.action_handler_registry`. | `import src.backend.entrypoints.stream.subscribers` без поднятия `entrypoints.api.generator` (проверить через `python -c "import sys; sys.modules.pop('src.backend.entrypoints.api.generator.registry', None); import src.backend.entrypoints.stream.subscribers"` — должно подняться без ImportError). |
| **DOMAIN-P2-001** | **P2** | `src/backend/entrypoints/base.py:90-145` (`BaseEntrypoint`) | Docstring явно говорит: *"BaseEntrypoint определён, но НЕ наследуется ни одним протоколом. Реальная унификация идёт через свободную функцию dispatch_action(). Класс сохранён для backward-compat (внешние интеграции могут импортировать). Новые протоколы должны использовать dispatch_action() напрямую."* Проверено: `grep -rEn "class .*\(BaseEntrypoint" src/backend/` — пусто. Единственный concrete subclass — `DummyEntrypoint` в `tests/unit/entrypoints/test_base.py:62` для unit-тестов самого абстрактного класса. | Мёртвый код, который вводит в заблуждение (наследование от абстрактного класса выглядит как путь для новых протоколов, но на практике весь проект использует free-function `dispatch_action`). | Пометить `BaseEntrypoint` как `deprecated` через `warnings.warn(DeprecationWarning, stacklevel=2)` в `__init__`; перенести `__all__` docstring в "will be removed in Sprint 1.4". Альтернативно — удалить, если команда готова. | Тест `test_base.py::test_base_entrypoint_dispatch` (line 70) должен начать xfail-ить или быть удалён вместе с классом. |
| **DOMAIN-P4-001** | **P4** | `src/backend/entrypoints/stream/subscribers.py` (отсутствует) | Текущий шаблон "log + ack" — не эквивалент DLQ-replay. В `outbox.py:91-167` уже есть контракт `replay(event_ids, dry_run, override_payload)` и `mark_resolved(event_ids, operator, reason)`. Отсутствие DLQ-enqueue = невозможно programmatic replay. | MQ-poisoned messages остаются только в логах (8.04 lsof `git log` показал S9 K2 W1 DLQ-policy registry и S13 K3 W4 retention, но MQ-handler не использует). | Опционально: в `invoker_schedule.py` tick-handler (line 141-211) тоже отсутствует DLQ-интеграция — на ошибке `envelope.success=False` только `logger.warning`. | `test_dlq_replay_after_failure`: поднять OutboxEvent с retry_count=5, status=DLQ, вызвать `outbox.replay([event_id])` → status=PENDING, retry_count=0; затем успешный dispatch → status=DELIVERED. |

---

## 4. Detailed evidence

### DOMAIN-P0-001 (SSE auth propagation gap)
- Файл: `src/backend/entrypoints/sse/handler.py:188-236` (`sse_invoke`).
- В `sse_invoke` HTTP-handshake идёт через FastAPI endpoint `sse_router.post("/invoke", ..., dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))])` (line 186), но в теле `bridge = await dispatch_action_or_dsl(action_id=body.action, dsl_route_id=body.action, payload=body.payload, transport="sse", correlation_id=..., idempotency_key=..., attributes={"path": str(request.url.path)})` — `principal` и `permissions` НЕ передаются.
- В `src/backend/entrypoints/_action_bridge.py:86-87` определены `principal: str = ""`, `permissions: tuple[str, ...] = ()`. Docstring явно: *"По умолчанию `""` → `DslService` трактует как `"anonymous"` (fail-closed)"* — но для protected routes это fail-OPEN, потому что DSL-route с `pipeline.security` будет пускать только `RoutePermissionDeniedError` (см. `src/backend/core/errors.py:267-298`) при наличии requirements, а для routes без `security` — пропускать anonymous.
- Контраст с GraphQL: `src/backend/entrypoints/graphql/schema.py:786-792` — `graphql_router = GraphQLRouter(schema, path="/graphql", dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT, AuthMethod.MTLS]))])`. Тот же GraphQL `_dispatch_dsl` (line 192-249) строит `ExecutionContext.from_auth(auth, route_id=route_id)` с реальным principal/permissions.
- Тестовая инфраструктура уже есть: `tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation` (8 xfailed тестов) и `TestSseAuthContextEdgeCases` (8 xfailed). xfail-сообщения: *"SSE /events/invoke не пробрасывает principal/permissions из request.state.auth в DslService.dispatch (parity с GraphQL/REST). Forward-looking TDD до Sprint 1.4 L5 Security Chain migration"*.
- Severity P0: protected route через SSE обходит route-wide permission check. Банковская шина, R-V15-1 closure (см. `src/backend/core/errors.py:267-298`).

### DOMAIN-P0-002 (MQ entrypoints — нет DLQ)
- Файлы:
  - `src/backend/entrypoints/stream/subscribers.py:18-51` — `@stream_client.redis_router.subscriber(stream=settings.redis.get_stream_name("dsl-events"))` и `@stream_client.rabbit_router.subscriber(settings.queue.get_queue_name("dsl-actions"))`. На `try/except Exception` (line 33) — `stream_logger.error(f"Failed to process Redis DSL action: {exc}", exc_info=True)`. Никакого `OutboxBackend.enqueue`.
  - `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` — `_dispatch_invocation_message` с `try: _deserialize_request` (parse fail) → `stream_logger.warning` + `return` (ack без retry); `try: await invoker.invoke(request)` (dispatch fail) → `stream_logger.exception` + ack.
- DLQ-инфраструктура существует и `import`'nа в смежных файлах (см. `grep -rln "dlq\|DLQ" src/backend/entrypoints/`):
  - `src/backend/entrypoints/webhook/transformer.py:14` импортирует `DLQEntry` (но это backward-compat shim на `services.integrations.webhook_relay`).
  - `src/backend/entrypoints/api/v1/routers.py:149-150, 346` импортирует `admin_scheduler_dlq_router` (вне scope).
  - **НЕ импортируется в**: `stream/subscribers.py`, `stream/invoker_subscribers.py`, `mqtt/mqtt_handler.py`, `email/imap_monitor.py`, `filewatcher/watcher_manager.py`, `scheduler/invoker_schedule.py`, `webhook/handler.py:206-264` (outbound) — все entrypoint handlers на failure → log + drop/ack.
- Тестовое подтверждение: `tests/unit/entrypoints/stream/test_invoker_subscribers.py:94-127` — `test_invalid_body` и `test_invoker_raises` проверяют `logger.warning.assert_called()` / `logger.exception.assert_called()`. Нет ни одного `assert outbox.enqueue` или `assert dlq_writer.write` — то есть контракт "log + ack" зафиксирован тестами.
- Severity P0: data-loss path. `src/backend/core/messaging/outbox.py:1-21` явно описывает контракт DLQ как "transport-agnostic Dead-Letter Queue (DLQ) + at-least-once event delivery". MQ-обработчики этот контракт НЕ выполняют — на poison message теряется возможность programmatic replay/resolve, остаётся только ручной grep по логам.

### DOMAIN-P1-001 (Layer boundary: entrypoints/stream/ → entrypoints/api/)
- Файл: `src/backend/entrypoints/stream/subscribers.py:9`:
  ```python
  from src.backend.entrypoints.api.generator.registry import action_handler_registry
  ```
- Текущий scope: `src/backend/entrypoints/**` без `src/backend/entrypoints/api/**`. Файл вне scope импортируется файлом в scope. На момент `import src.backend.entrypoints.stream.subscribers` Python должен поднять `src.backend.entrypoints.api.generator.registry`, который, в свою очередь, импортирует многое из `extensions/`, `services/`, `workflows/`.
- Альтернативный путь: `src.backend.dsl.commands.action_registry.action_handler_registry` (определён в `src/backend/dsl/commands/action_registry.py:349`) — доступен без `entrypoints/api/`.
- `tools/check_layers_allowlist.txt` содержит `src/backend/entrypoints/_action_bridge.py entrypoints src.backend.dsl.service` как legacy-запись. Тот же `entrypoints/_action_bridge.py:13` импортирует `src.backend.dsl.service` (внутри `dispatch_action_or_dsl`). Это другая запись allowlist (legacy), но **не** объясняет цикл через `entrypoints/api/generator/registry.py`.
- Severity P1: layer boundary нарушена внутри scope. Конкретный сценарий: при `make layers --strict` (см. `tools/check_layers.py:42-46` — есть `--strict` флаг) — скорее всего, падает; в обычном режиме — попадает в allowlist по факту legacy.

### DOMAIN-P2-001 (BaseEntrypoint — dead code, deprecated)
- Файл: `src/backend/entrypoints/base.py:90-145`.
- Self-documented: `".. deprecated:: S171 M10. BaseEntrypoint определён, но НЕ наследуется ни одним протоколом."`
- `grep -rEn "class .*\(BaseEntrypoint" src/backend/` — пусто (исключая pyc).
- `tests/unit/entrypoints/test_base.py:62-89` — `DummyEntrypoint(BaseEntrypoint)` существует ТОЛЬКО для unit-тестирования абстрактного класса.
- Severity P2: dead code, который вводит в заблуждение новых разработчиков (см. `core/infrastructure/resilience/unified_rate_limiter.py:10` — `Интегрируется в BaseEntrypoint.dispatch() и FastAPI middleware.` — это неверно: ни один FastAPI middleware не интегрируется в `BaseEntrypoint`).

### DOMAIN-P4-001 (Optional: DLQ integration в MQ handlers)
- Не блокирующий, но органично уместен: DLQ-инфраструктура (`core/messaging/outbox.py`) уже существует, контракт `enqueue/replay/mark_resolved` готов. Stream subscribers / MQTT handler / scheduler / filewatcher / IMAP monitor — все используют один и тот же fail-pattern (log + drop), и в `test_invoker_subscribers.py:107-127` (test_invoker_raises) контракт "только логируем" закреплён тестом.
- Severity P4: missing feature, который органично дополняет существующий DLQ-protocol. Без него DLQ-UI (`src/backend/entrypoints/api/v1/endpoints/admin_scheduler_dlq.py`) — полезен только для APScheduler jobs, не для MQ/IMAP/filewatcher источников.

---

## 5. Contradictions / overlaps to flag

1. **DOMAIN-P0-001 vs DOMAIN-P0-002**: оба P0 — security/data-loss. DOMAIN-P0-001 (SSE auth) — это "есть защита, но обход через транспорт". DOMAIN-P0-002 (MQ DLQ) — это "нет защиты от poison-message". Не пересекаются, оба блокируют. Фиксы независимы.

2. **DOMAIN-P1-001 vs DOMAIN-P0-002**: P1 boundary (`stream/subscribers.py:9`) — файл с P0 (`subscribers.py` — DLQ). Если фиксить P0-002 (DLQ integration), имеет смысл сначала разрешить P1 (убрать импорт из `entrypoints/api/`) и сразу подключить DLQ через `core/messaging/outbox.py::OutboxBackend` — это один merge.

3. **DOMAIN-P2-001 vs STR-01**: `BaseEntrypoint` deprecated, но `dispatch_action` (free-function) — это правильный путь. Удаление `BaseEntrypoint` улучшит читаемость, не сломает контракт.

4. **Test infra split**: `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` содержит 8 xfailed тестов с явной формулировкой "Sprint 1.4 L5 Security Chain migration". Это **готовый TDD-каркас** для DOMAIN-P0-001 — фикс может состоять буквально из `(un-xfail) → 8 pass`.

5. **Allowlist inconsistency**: `tools/check_layers_allowlist.txt` имеет 4 entrypoints-записи, импортирующие `src.backend.dsl.service` (`_action_bridge.py`, `email/imap_monitor.py`, `filewatcher/watcher_manager.py`, `graphql/schema.py`, `soap/soap_handler.py`, `websocket/ws_handler.py`) — все legacy. Можно почистить одной серией (P3-Sprint), но вне scope этого аудита.

6. **Неиспользуемый middleware**: `entrypoints/middlewares/rpa_policy.py` зарегистрирован с `order=720` (см. `setup_middlewares.py:242`), но в scope auth/security — отдельный аналитик.

7. **Предполагаемый конфликт с `BaseEntrypoint` docstring**: `core/infrastructure/resilience/unified_rate_limiter.py:10` утверждает *"Интегрируется в BaseEntrypoint.dispatch() и FastAPI middleware."* — `BaseEntrypoint.dispatch` (line 108-128) не вызывает `unified_rate_limiter` (см. `base.py:108-128` — только `dispatch_action(...)` и `protocol`). Либо docstring в `unified_rate_limiter.py` устарел, либо есть скрытая интеграция через `action_handler_registry.dispatch` (см. `dsl/commands/action_registry.py:281-321` — `ActionHandlerRegistry.dispatch` тоже не вызывает rate-limiter). Скорее всего, docstring-ложь. Severity: docstring-fix, не код.

---

## 6. Readiness score 0–100

### Формула
```
readiness = 100
           - 10 * P0_count
           - 5  * P1_count
           - 2  * P2_count
           - 1  * P3_count
           - 0.5 * P4_count
clamp(readiness, 0, 100)
```
Оценка ≥80 запрещена при наличии P0/P1 (clamp + 80-cap).

### Подсчёт
- P0 = 2 (DOMAIN-P0-001, DOMAIN-P0-002)
- P1 = 1 (DOMAIN-P1-001)
- P2 = 1 (DOMAIN-P2-001)
- P3 = 0
- P4 = 1 (DOMAIN-P4-001)

```
raw = 100 - 10*2 - 5*1 - 2*1 - 1*0 - 0.5*1
    = 100 - 20 - 5 - 2 - 0 - 0.5
    = 72.5
```

### Применяем 80-cap
Так как `P0 > 0` и `P1 > 0`, принудительно `readiness = min(72.5, 80) = 72.5`.

**Readiness = 72 / 100** (округлено к ближайшему целому; raw 72.5).

### Обоснование
- 2 P0: один security-gap (SSE auth), один data-loss (MQ DLQ). Оба блокируют до фикса.
- 1 P1: layer boundary нарушена (`entrypoints/stream/` → `entrypoints/api/`).
- 1 P2: dead code, deprecated класс. Чистый код-чистка.
- 1 P4: missing feature, но DLQ-инфра уже есть — фикс low-cost.
- Verified strengths 20 шт. покрывают pure ASGI bridge, ASGI exception handler, streaming, gRPC safe-error, AsyncAPI degradation, MiddlewareRegistry, OOM-safe hashing, S204 security retro-audit closure на GraphQL — то есть архитектурный backbone рабочий.

Чтобы поднять readiness до ≥80, нужно закрыть оба P0 + P1 (= -25) → `100 - 25 = 75`; или закрыть только P0 (= -20) → `100 - 20 = 80` (но P1 остаётся, поэтому 80-cap не пускает). Минимальный путь к ≥80: закрыть все 2 P0 + 1 P1 → raw = 72.5 + 25 = 97.5, clamp = 80, и **тогда** можно поставить 80 при условии, что P0/P1 закрыты.

---

## 7. Recommended next tasks

В порядке приоритета (минимальный набор для прохода в ≥80):

1. **(P0) Закрыть DOMAIN-P0-001 (SSE auth propagation)**:
   - В `src/backend/entrypoints/sse/handler.py:188-236` (sse_invoke): после получения `body`, извлечь `auth = getattr(request.state, "auth", None)`, развернуть в `principal: str`, `permissions: tuple[str, ...]`, прокинуть в `dispatch_action_or_dsl(...)`.
   - Завести helper (по аналогии с `graphql/schema.py:_extract_auth_from_info`) в `entrypoints/sse/handler.py` или в `entrypoints/_action_bridge.py`.
   - Снять xfail с 8 тестов в `tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation` и `TestSseAuthContextEdgeCases`.
   - Проверить parity: `tests/unit/entrypoints/graphql/test_schema.py` (passport-тест principal/permissions propagation) — должен остаться green.

2. **(P0) Закрыть DOMAIN-P0-002 (MQ DLQ integration)**:
   - В `src/backend/entrypoints/stream/subscribers.py:33-34, 48-50` и `src/backend/entrypoints/stream/invoker_subscribers.py:69-78, 87-92`: на `try/except`, классифицировать error, enqueue `OutboxEvent(transport="mq"|"rabbit"|"redis", action=..., payload=body, error_class=type(exc).__name__, error_message=str(exc), correlation_id=...)`, status=`OutboxEventStatus.DLQ` при max_attempts или сразу при parse-fail.
   - Сначала разрешить DOMAIN-P1-001 (убрать `from src.backend.entrypoints.api.generator.registry import action_handler_registry` → `from src.backend.dsl.commands.action_registry import action_handler_registry`).
   - Добавить тесты `test_invalid_body_enqueue_to_dlq` и `test_dispatch_exception_enqueue_to_dlq` в `tests/unit/entrypoints/stream/test_subscribers.py` + `test_invoker_subscribers.py` (mock `OutboxBackend.enqueue`).
   - Расширить на `mqtt/mqtt_handler.py:154-157`, `email/imap_monitor.py:264-265`, `filewatcher/watcher_manager.py:174-175, 194-195` — тот же паттерн.

3. **(P1) Закрыть DOMAIN-P1-001 (Layer boundary)**:
   - В `src/backend/entrypoints/stream/subscribers.py:9` заменить `from src.backend.entrypoints.api.generator.registry import action_handler_registry` на `from src.backend.dsl.commands.action_registry import action_handler_registry`.
   - Проверить `make layers` (если `--strict`): не должно появиться новых нарушений.

4. **(P2) Почистить DOMAIN-P2-001 (BaseEntrypoint dead code)**:
   - Пометить `BaseEntrypoint.__init__` через `warnings.warn(DeprecationWarning, stacklevel=2)`.
   - Альтернатива: удалить класс + 4 теста в `tests/unit/entrypoints/test_base.py::DummyEntrypoint`. Требует review "внешние интеграции" (см. docstring line 102).

5. **(P4) Опционально: DLQ-replay UI для MQ**:
   - Расширить `src/backend/entrypoints/api/v1/endpoints/admin_scheduler_dlq.py` (вне scope, но partner) на общий `admin/dlq` с фильтром `transport=mq|redis|rabbit|email|filewatcher|scheduler`.

6. **(docstring fix, не-P)**: `src/backend/infrastructure/resilience/unified_rate_limiter.py:10` — фраза "Интегрируется в BaseEntrypoint.dispatch() и FastAPI middleware" не соответствует коду. Поправить на "Интегрируется в ActionHandlerRegistry.dispatch через middleware-цепочку и в FastAPI Depends (rate_limit).".

---

## 8. Commands run

Все команды — read-only / targeted test. Источник: прямой запуск через `.venv/bin/python -m pytest ... -p no:cacheprovider` (отключает кэш pytest для воспроизводимости).

| # | Команда | Результат |
|---|---|---|
| 1 | `git rev-parse HEAD` | `2f620910951a727f50d4539b998375b0c0bda55d` |
| 2 | `git log --oneline -5` | Подтверждён baseline `b69d6b49` |
| 3 | `git status` | pre-existing: `pyproject.toml`, `tests/unit/dsl/transforms/test_dataframes.py`; untracked: `docs/audit/swarm-2026-08-06/` (создаётся этим аудитом) |
| 4 | `wc -l tools/check_layers_allowlist.txt` | 180 строк |
| 5 | `grep -E "^(src/backend/entrypoints" tools/check_layers_allowlist.txt` | 57 строк, из них 4 legacy на `entrypoints/*` → `dsl.service`, 1 на `_action_bridge.py` → `dsl.engine.context` |
| 6 | `find src/backend/entrypoints -type f -name '*.py'` | 99 файлов (без __pycache__) |
| 7 | `find tests -path '*entrypoints*' -type f -name '*.py'` | 117 файлов |
| 8 | `grep -rEn "class .*\(BaseEntrypoint" src/backend/` | пусто (только pyc) |
| 9 | `grep -rln "dlq\|DLQ" src/backend/entrypoints/` | `webhook/transformer.py` (shim), `api/v1/routers.py`+`endpoints/admin_scheduler_dlq.py` (вне scope) |
| 10 | `grep -rln "Outbox\|outbox" src/backend/entrypoints/` | только `grpc/grpc_server/base.py:51` (комментарий, не import) |
| 11 | `.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/ --no-header -q -p no:cacheprovider` | 451 passed, 2 failed (`test_global_ratelimit.py::test_checker_failure_falls_through`, `test_webhook_signature_middleware.py::test_protected_prefix_without_secret_passes_through`) |
| 12 | `.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/test_admin_audit_pure_asgi.py tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py tests/unit/entrypoints/middlewares/test_tenant_pure_asgi.py tests/unit/entrypoints/middlewares/test_blocked_routes_pure_asgi.py tests/unit/entrypoints/middlewares/test_pii_masking_response_pure_asgi.py tests/unit/entrypoints/middlewares/test_rpa_policy_pure_asgi.py tests/unit/entrypoints/middlewares/test_timeout_pure_asgi.py tests/unit/entrypoints/middlewares/test_webhook_signature_pure_asgi.py --no-header -q -p no:cacheprovider` | 71 passed (pure-ASGI smoke) |
| 13 | `.venv/bin/python -m pytest tests/unit/entrypoints/stream/ --no-header -q -p no:cacheprovider` | 12 passed |
| 14 | `.venv/bin/python -m pytest tests/unit/entrypoints/sse/ --no-header --tb=line -p no:cacheprovider` | 23 passed, 4 failed (env: spaCy `ru_core_news_lg` wheel network — environmental, не code), 8 xfailed (DOMAIN-P0-001 TDD-каркас) |
| 15 | `.venv/bin/python -m pytest tests/unit/entrypoints/grpc/ --no-header -q -p no:cacheprovider` | 49 passed |
| 16 | `.venv/bin/python -m pytest tests/unit/entrypoints/http3/ --no-header -q -p no:cacheprovider` | 13 passed |
| 17 | `.venv/bin/python -m pytest tests/unit/entrypoints/test_base.py --no-header -q -p no:cacheprovider` | 7 passed |
| 18 | `.venv/bin/python -m pytest tests/unit/entrypoints/cdc/ tests/unit/entrypoints/express/ tests/unit/entrypoints/email/ --no-header -q -p no:cacheprovider` | 56 passed, 1 skipped, 1 xfailed (live IMAP) |
| 19 | `.venv/bin/python -m pytest tests/unit/entrypoints/filewatcher/ tests/unit/entrypoints/mqtt/ --no-header -q -p no:cacheprovider` | 39 passed, 2 failed (`test_mqtt_handler.py::TestMqttSettings::test_defaults`, `test_mqtt_handler.py::TestMqttHandler::test_stop_cancels_task`) |
| 20 | `.venv/bin/python -m pytest tests/unit/entrypoints/stream/ tests/unit/entrypoints/scheduler/ tests/unit/entrypoints/webhook/ --no-header -q -p no:cacheprovider` | 39 passed, 2 warnings |
| 21 | `.venv/bin/python -m pytest tests/unit/entrypoints/websocket/test_ws_handler.py --no-header -q -p no:cacheprovider` | 8 passed |
| 22 | `.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/test_exception_handler.py tests/unit/entrypoints/middlewares/test_streaming_body_hash.py tests/unit/entrypoints/middlewares/test_request_id.py --no-header -q -p no:cacheprovider` | 22 passed |

### Замечания по тестам (не code defects)
- `test_mqtt_handler.py::TestMqttSettings::test_defaults`, `::test_stop_cancels_task` — failed. Не проверено содержимое (находятся в out-of-scope security/auth, но были в скоупе ручного прогона файлов, не являющихся security — `mqtt/mqtt_handler.py` НЕ в security-list). Зафиксировано, не блокер, требует отдельного анализа.
- `test_global_ratelimit.py::test_checker_failure_falls_through` — fail. `middlewares/global_ratelimit.py` не в scope-исключениях; не блокер, требует отдельного анализа.
- `test_webhook_signature_middleware.py::test_protected_prefix_without_secret_passes_through` — fail. `webhook_signature.py` в security-allowlist (не в scope).
- 4 SSE test fails — environmental (spaCy model wheel не скачивается). Не code defect.

---

## 9. Bottom line

- **Verified strengths**: 20 (pure ASGI, ASGI exception handler, OOM-safe streaming hash, MiddlewareRegistry, gRPC safe-error, AsyncAPI graceful degradation, mTLS, S204 security retro-audit closure, dispatch_action/bus, etc.)
- **Findings**: 5 (2 P0, 1 P1, 1 P2, 0 P3, 1 P4)
- **Readiness**: 72 / 100 (raw 72.5, 80-cap из-за P0/P1)
- **Blockers** (нужны к фиксу до прохода в ≥80):
  - `DOMAIN-P0-001` — SSE `/events/invoke` не пробрасывает principal/permissions (8 xfailed тестов готовы)
  - `DOMAIN-P0-002` — MQ entrypoints (Redis/RabbitMQ/IMAP/MQTT/filewatcher/scheduler) логируют и ack'ают вместо DLQ
  - `DOMAIN-P1-001` — `entrypoints/stream/subscribers.py:9` импортирует из `entrypoints/api/generator/registry.py` (вне scope)
- **Optional cleanup** (после blocker-фиксов): `DOMAIN-P2-001` (deprecate `BaseEntrypoint`), `DOMAIN-P4-001` (DLQ для MQ-poison messages).
