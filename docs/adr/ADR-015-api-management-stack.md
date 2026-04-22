# ADR-015: API Management stack (quotas + versioning + developer portal)

* Статус: accepted
* Дата: 2026-04-21
* Фазы: G2

## Контекст

Необходима полноценная API-management поверх FastAPI: хешированные
API keys, multi-tenant quotas, versioning (header+URL) с RFC 8594
Sunset-headers, auto-generated SDKs, developer portal.

## Решение

1. API-key authentication: хранение **только hash** (SHA-256).
   Проверка через `APIKeyAuth.verify()`.
2. Quotas: per-tenant monthly/daily ограничения в Redis (
   token-bucket с длинным окном).
3. Versioning: header `API-Version: v1`, `Deprecation: true`,
   `Sunset: <date>`. Совместимо с RFC 8594.
4. Developer portal — Streamlit-page `docs_portal` (встроенная
   try-it-out, SDK download, changelog). Базовый scaffolding,
   расширяется в L1.
5. SDK-generation — существующий `tools/generate_api_client.py`.

## Альтернативы

- **Внешний API Gateway (Kong/APISIX)**: хороший вариант для крупных
  установок; в scope приложения оставляем встроенную реализацию,
  совместимую с внешним gateway (если заказчик его использует).

## Последствия

- Hash-only API key storage обязателен.
- Sunset headers видны клиентам до удаления API версии.
- Developer portal в Streamlit интегрируется с auth и quota-meter.
