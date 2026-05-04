# Tutorial — Build a REST Connector

Цель: создать REST-коннектор к внешнему HTTP API через
``BaseHTTPClient``-протокол.

## Что вы узнаете
- Как структурировать клиентский класс с retry/circuit-breaker.
- Как обернуть его в service-фасад.
- Как зарегистрировать в DI.

## Шаги

1. `src/infrastructure/clients/external/myapi_client.py`:
   ```python
   class MyApiClient:
       def __init__(self, http: HttpClientProtocol):
           self._http = http
       async def search(self, q: str) -> list[dict]:
           return await self._http.make_request("GET", "/search", params={"q": q})
   ```
2. Service: `src/services/integrations/myapi.py` — обернуть и
   зарегистрировать через `app_state_singleton`.
3. Action endpoint: `endpoints/myapi.py` с `ActionSpec`.
4. Smoke: `curl /api/v1/myapi/search?q=test`.

## Проверка
- Запрос проходит за < 500 мс на dev_light.
- `circuit_breaker_state{name="myapi"}` доступна в Prometheus.

## Next steps
- [DSL route](write-dsl-route.md)
- [Multi-tenant setup](multi-tenant-setup.md)
