# ADR-0050 — WAF strict + Single Entry для исходящего HTTP

* Статус: Accepted (Wave 1, S1+S2+S3, 2026-05-08)
* Связано с: V15 R-V15-5, R-V15-13, R-V15-14, V15.1 Single-Entry; PLAN.md V16 §S1.

## Контекст

К1 (релизный security gate) требует, чтобы все ``net.outbound:<host>:external``
запросы проходили через WAF-pipeline с allow/deny-list, payload-scanner и
audit-event на каждый запрос (см. R-V15-5). Текущая база содержит ~37
прямых ``httpx.AsyncClient(...)`` callsite'ов в плагинах и сервисах,
часть которых обходит WAF. Без единой точки входа невозможно гарантировать:

* что host прошёл allow-list;
* что capability ``net.outbound:<host>`` задекларирована плагином;
* что payload-scanner и rate-limiter применены.

## Решение

1. **Single Entry** — все исходящие HTTP вызовы во вновь добавляемом и
   рефакторящемся коде идут через ``src.backend.core.net.OutboundHttpClient``.
   Регистрация в svcs выполняется в ``waf_setup.register_outbound_http_client()``
   (Wave 1.4). Альтернативные пути (прямой ``httpx.AsyncClient``) ловит
   CI-gate ``tools/check_waf_coverage.py``.

2. **Глобальная WafPolicy** — конструируется из ``WafSettings`` в
   ``register_waf_policy()`` (Wave 1.4). Поля:
   * ``allow_hosts`` / ``deny_hosts`` — списки хостов;
   * ``strict`` — пустой allow-list трактуется как deny-all (R3 prod-gate);
   * ``max_payload_bytes`` — лимит body (10 MiB по умолчанию).

3. **mTLS-канал** — ``HttpBaseSettings`` расширены полями ``client_cert_path``,
   ``client_key_path``, ``client_cert_password`` (Wave 1.3). Если оба ``*_path``
   пустые — ``cert`` не передаётся (backward-compat). При заполнении —
   tuple ``(cert, key[, password])`` пробрасывается в ``httpx.AsyncClient``;
   ротация сертификата сбрасывает кэш клиента под locked-секцией.

4. **Vault-backed секреты** — ``SECRETS_BACKEND=vault`` использует
   ``VaultSecretsBackend`` (hvac KV v2) — Wave 1.2. Stub
   ``NotImplementedError`` удалён.

5. **Migration через feature-flag** — ``WAF_OUTBOUND_VIA_FACADE`` (default
   ``False``) переключает ``BaseExternalAPIClient`` между legacy ``HttpClient``
   и ``OutboundHttpClient`` (Wave 1.5). Phase-1: флаг ``False``, прежнее
   поведение сохраняется. Phase-2 (после staging-smoke): ``True`` — все
   business-сервисы идут через facade.

## Последствия

* `+` Унифицированный audit-trail на ``waf.audit`` logger; structured event
  с outcome для observability dashboard.
* `+` Capability-gate централизован: один ``CapabilityGate.check`` для всех
  outbound вызовов в ядре.
* `+` mTLS включается заполнением settings без правок callsite'ов.
* `−` Существующие 37 callsite'ов прямых ``httpx.AsyncClient`` остаются в
  allowlist (``tools/check_waf_coverage_allowlist.txt``); миграция вынесена
  в зоны К2-К5 по соответствующим разделам каталога.
* `−` Phase-2 (Wave 1.5 Phase-2) требует декларации
  ``net.outbound:<host>`` во всех сервисных манифестах; до включения
  ``WAF_OUTBOUND_VIA_FACADE=True`` запускается grep по
  ``services/integrations/*`` для добавления отсутствующих деклараций.

## CI gates (Wave 1.8)

* ``make check-waf-coverage`` — soft-режим (учитывает allowlist).
* ``make check-waf-coverage-strict`` — игнорирует allowlist; обязателен
  для CI/release.
* ``make check-ai-safety`` — workspace + sandbox + capability tests.
* ``make ci`` — composite (format/lint/type/security/WAF strict + AI safety).
* ``make pr`` — ``ci + docs``.

## Phase-out план для legacy `HttpClient`

* **Wave 1.5 Phase-2 (post-staging-smoke):** ``WAF_OUTBOUND_VIA_FACADE=True``
  в production overlay; SKB/DaData/etc. идут через ``OutboundHttpClient``.
* **К2-К5:** миграция per-zone allowlist'а:
  * К2 — ``services/ai/*`` (ai_providers, ai_moderation);
  * К3 — ``infrastructure/clients/external/*`` (express/telegram bots);
  * К4 — ``services/ops/*`` (notification/webhook);
  * К5 — DSL-процессоры (proxy/forward, ml_inference) + sources/sinks.
* После каждой зоны — удаление соответствующих записей из
  ``check_waf_coverage_allowlist.txt`` и проверка ``--strict``.
