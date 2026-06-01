# Tutorial 08 — OutboundHttpClient + WAF + capability

> **Prerequisites:** plugin создан через `make new-plugin`. ~30 минут.

## Цель

Сделать external HTTP-запрос из плагина через WAF-gated single entry с
capability declaration.

## Шаги

### 1. Объявить capability в plugin.toml

```toml
# extensions/my_plugin/plugin.toml
[[capabilities]]
name = "net.outbound.api.example.com"
scope = "external"
```

### 2. Использовать make_http_client

```python
# extensions/my_plugin/functions/api.py
from src.backend.core.net import make_http_client


async def fetch_data(api_url: str) -> dict:
    client = make_http_client(
        caller="my_plugin",
        target_host="api.example.com",
        target_kind="external",
        timeout_seconds=30,
    )
    response = await client.get(api_url)
    response.raise_for_status()
    return response.json()
```

### 3. Тест на capability denied

Если в `plugin.toml` capability **не объявлен** — попытка вызвать
`make_http_client(target_host="other-host.com", ...)` бросит
`CapabilityDeniedError` + запишет audit-event.

### 4. WAF policy check

```bash
# WAF coverage gate
make check-waf-coverage-strict
# OK: 0 prohibited httpx.AsyncClient usages outside allowlist
```

### 5. Логи + audit

```
{
  "event": "capability.allowed",
  "caller": "my_plugin",
  "capability": "net.outbound.api.example.com:external",
  "trace_id": "..."
}
```

## What's next?

* ADR-0050 — WAF strict single entry.
* ADR-0061 — allowlist tightening.
* Tutorial 09 — DLQ replay при failed outbound.
* Runbook `dlq-replay.md` — что делать при upstream-failure.
