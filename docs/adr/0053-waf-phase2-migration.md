# ADR-0053 — WAF Phase-2: flip `outbound_via_facade=True` по умолчанию

* Статус: Accepted (Wave [s1/k1-waf-phase2], 2026-05-12)
* Связано с: ADR-0050 (WAF strict + Single Entry), V15 R-V15-5, PLAN.md V16 §S1.

## Контекст

Phase-1 (ADR-0050) ввёл `OutboundHttpClient` как single entry для исходящего
HTTP с поддержкой WAF allow/deny-list и payload-scanner'а. На уровне
`BaseExternalAPIClient` уже есть auto-routing-ветка: при
`outbound_via_facade=True` все её субклассы (DadataClient, SkbClient,
...) автоматически идут через фасад.

Phase-1 оставлял `outbound_via_facade=False` по умолчанию, чтобы не
сломать существующие интеграции (telegram_bot, express_bot, prom-collector
без объявленных capabilities). К концу Sprint 1 К1+К2 необходимо
переключить default в `True`, чтобы:

* новые сервисы автоматически попадали в WAF-режим без явной конфигурации;
* CI gate `make check-waf-coverage` отражал реальное покрытие, а не
  отлично знающую о флаге allowlist.

## Решение

1. **`outbound_via_facade=True` по умолчанию** в `core/config/waf.py`.
2. **`strict=False` остаётся по умолчанию** — flip strict-mode (deny-all
   на пустом allow-list) выполняется отдельным follow-up в S2/S3 после
   per-team review allow-list'а.
3. Файлы из `tools/check_waf_coverage_allowlist.txt`, которые **не**
   переходят на `OutboundHttpClient` в этой Wave, остаются в allowlist
   как известный технический долг. Список follow-up зон:
   * `services/ai/ai_providers.py` — 8 callsites cloud-LLM;
   * `services/ops/notification_adapters.py` — 7 callsites уведомлений;
   * `infrastructure/sinks/{http_sink,webhook_sink}.py` — outbound sinks;
   * `infrastructure/sources/polling.py` — long-poll fetcher;
   * `services/ops/notification_hub.py`, `services/ops/webhook_scheduler.py`;
   * `infrastructure/clients/external/{telegram_bot,express_bot}.py` —
     требуют capability declarations в plugin.toml.

4. Для уже мигрированных через `BaseExternalAPIClient` сервисов (DadataClient,
   SkbClient) flip default `True` означает: **все новые запросы
   автоматически идут через OutboundHttpClient** без изменения вызывающего
   кода. Это zero-touch миграция.

## Альтернативы

1. **Big-bang миграция всех 21 callsites в этой Wave**.
   Минусы: высокий риск регрессий, особенно в TLS/cert plumbing
   (`verify=`, `cert=`); каждый callsite требует индивидуального тестирования.
   Откладывается на per-team follow-up.

2. **Оставить `outbound_via_facade=False`**.
   Минусы: DoD К1 в PLAN.md V16 требует `make check-waf-coverage` зелёный
   с уменьшенным allowlist'ом; без flip default'а нет принудительного
   incentive для миграции.

3. **Сделать `outbound_via_facade` enum (`off/auto/strict`) вместо bool**.
   Минусы: усложнение конфигурации без существенного выигрыша. Будущее
   `strict=True` решает ту же задачу через флаг `strict`.

## Последствия

* `BaseExternalAPIClient` субклассы автоматически идут через фасад,
  WAF allow/deny проверяется на каждом запросе. Тесты `test_base_external_api_outbound.py` и `test_waf_policy_wiring.py` подтверждают
  поведение.
* `make check-waf-coverage` по-прежнему пропускает файлы из allowlist'а
  (legacy `httpx.AsyncClient` без BaseExternalAPIClient-обёртки). Это
  baseline — финальный strict CI gate включается отдельным ADR.
* Документация (Sphinx) обновляется ссылкой на этот ADR.

## Проверка

* `tests/integration/security/test_waf_facade_default_on.py`:
  * `waf_settings.outbound_via_facade is True`;
  * `BaseExternalAPIClient` маршрутизирует через фасад без явной конфигурации.
* `tests/integration/test_base_external_api_outbound.py` (существует) —
  smoke per-callsite миграция.
* CI gate `make check-waf-coverage` остаётся green с тем же allowlist'ом.
