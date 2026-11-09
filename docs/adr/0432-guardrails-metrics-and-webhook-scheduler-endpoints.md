# ADR-0432 — HTTP-поверхности для метрик guardrails и планировщика webhook'ов

* Статус: Accepted (2026-11-09, волна 28)
* Cycle: 187 (волна 28)
* Связан с: ADR-0425 (контракт путей портала), ADR-0345 (tenant-scoping webhook'ов), ADR-0419 (SSRF/WAF hardening)
* Затрагивает:
  - `src/backend/core/di/providers/guardrails.py`, `src/backend/core/di/providers/webhooks.py` (новые),
  - `src/backend/entrypoints/api/v1/endpoints/admin_guardrails.py` (новый),
  - `src/backend/entrypoints/api/v1/endpoints/webhook_scheduler.py` (новый),
  - `src/backend/entrypoints/api/v1/routers.py`, `src/backend/core/ai/gateway_audit_mixin.py`,
  - страницы портала `47_AI_Безопасность.py`, `67_Задачи.py`

---

## Контекст

В портале были панели «Guardrails-метрики» и «Запланированные webhooks», но
серверных эндпоинтов не было (404, ADR-0425). Сервисы
`GuardrailsMetricsService` и `WebhookScheduler` существовали, но не были
подключены: у первого не было DI-провайдера и вызывающей стороны (метрики
никто не наполнял), у второго — HTTP-поверхности.

---

## Решение

1. **DI-провайдеры** (`core/di/providers/{guardrails,webhooks}.py`) отдают
   процессные singleton'ы + поддерживают override для тестов.
2. **`GET /api/v1/admin/guardrails-metrics`** — агрегаты по тенантам;
   **`POST /api/v1/admin/guardrails-metrics/{tenant_id}/false-positive`** —
   ручная отметка FP (404, если метрик нет).
3. Наполнение метрик: AI-шлюз пишет вердикт guardrails в агрегатор в
   завершающем audit-событии (`gateway_audit_mixin._emit_final`, best-effort —
   метрики не ломают вызов).
4. **`GET /api/v1/webhooks/scheduled`** и **`POST /api/v1/webhook/schedule`** —
   планирование отложенной/периодической доставки. URL проходит
   SSRF-guard `assert_safe_url` (иначе планировщик стал бы вектором запросов
   во внутреннюю сеть). Tenant-scoping — по ADR-0345.
5. Страницы портала переведены на живые пути; гейт контракта путей (ADR-0425)
   проверяет, что они существуют на сервере.

---

## Последствия

* Две панели портала работают; остальные «нереализованные» панели остаются
  выключенными (owner-задачи в `OWNER_TASKS.md` §15).
* Планировщик webhook'ов требует Redis: при отключённом Redis эндпоинт
  отвечает 503 (понятная ошибка, а не 500).
* Метрики guardrails живут в памяти процесса (персистентность — задача
  ClickHouse-писателя, который в сервисе предусмотрен, но не подключён).
