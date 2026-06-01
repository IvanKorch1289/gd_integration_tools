# Migration: WAF Phase-2 (Sprint 8 → Sprint 10)

> Status: Phase-2 default-ON принят в Sprint 1 K1. BLOCKER #3 закрыт в S8.
> Sprint 9 K1 W3 формализовал allowlist owner+target.
> Sprint 10 — миграция 12 файлов из allowlist'а на OutboundHttpClient.

## Rationale

См. ADR-0050 (single entry), ADR-0053 (Phase-2 default-ON), ADR-0061
(allowlist tightening). Все исходящие HTTP-запросы должны идти через
`src/backend/core/net/OutboundHttpClient` с capability-gate + WAF
policy + payload scanner.

## Phase summary

| Phase | Что | Когда | Статус |
|---|---|---|---|
| Phase-1 | OutboundHttpClient + auto-routing | S1 K1 | ✅ |
| Phase-2 default | feature_flag → True | S1 K1 | ✅ |
| Phase-2 BLOCKER #3 | tests via OutboundHttpClient | S8 K1 W1 | ✅ |
| Phase-3 allowlist tightening | owner+target формализация | S9 K1 W3 | ✅ |
| Phase-3 migration | 12 файлов миграция | S10 K1-K5 | 🔄 |
| Phase-4 R3 migration | оставшиеся 9 файлов | S11 R3 | ⏳ |

## Migration recipe (для одного callsite)

### Шаг 1: identify

```python
# Старый код:
async with httpx.AsyncClient(timeout=30) as client:
    response = await client.post(url, json=payload, headers=headers)
```

### Шаг 2: declare capability в plugin.toml

```toml
[capabilities]
"net.outbound.api.example.com:external" = "for external API integration"
```

### Шаг 3: replace через make_http_client

```python
# Новый код:
from src.backend.core.net import make_http_client

client = make_http_client(
    caller="my_plugin",
    target_host="api.example.com",
    target_kind="external",
    timeout_seconds=30,
)
response = await client.post(url, json=payload, headers=headers)
```

### Шаг 4: tests

* unit-test: проверить, что capability check вызывается;
* integration-test: проверить, что WAF policy блокирует unauthorized hosts.

### Шаг 5: удалить из allowlist

`tools/check_waf_coverage_allowlist.txt` — удалить строку для этого файла.

### Шаг 6: verify

```bash
make check-waf-coverage-strict  # должно пройти с 0 violations
```

## S10 file-by-file targets

См. ADR-0061 — 12 файлов с owner=Kk + target=s10.

## Special cases

* `core/security/vault_cipher.py` — внутренний rotator через Vault;
  требует Vault namespace в capability policy → S11 R3.
* `infrastructure/clients/storage/clickhouse.py` — ClickHouse HTTP не
  REST; требует extension OutboundHttpClient для non-OAS клиентов → S11 R3.

## Related

* ADR-0050, ADR-0053, ADR-0061
* `core/net/outbound_http.py`
* `tools/check_waf_coverage.py`
* PLAN.md V19.1 §S9 K1 W3
