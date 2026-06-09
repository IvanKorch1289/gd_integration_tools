# Toxiproxy Setup Runbook (S46 W4, TD-020)

**Status**: docs-only (operator action, not agent-automatable)
**Refs**: TD-020, ADR-0111 (S41 chaos formalize)

## Background

`tests/chaos/` содержит **69 test functions** (per S41 W6 audit):
- **36 pass** в dev-light mode (without toxiproxy daemon).
- **33 skipped** — требуют running toxiproxy instance.

Skipped tests покрывают: cache failures, redis disconnects, vault errors,
smtp timeouts, express chain, database connection drops.

## Operator Setup Steps

### 1. Install toxiproxy server

```bash
# macOS
brew install toxiproxy

# Linux (apt)
sudo apt-get install -y toxiproxy-server

# Or via Docker (recommended для CI)
docker run -d --name toxiproxy -p 8474:8474 ghcr.io/shopify/toxiproxy
```

### 2. Verify toxiproxy API

```bash
curl http://localhost:8474/version
# Expected: {"version":"2.x.x","api_version":"1.0"}
```

### 3. Configure proxies для каждого backend service

`tests/chaos/conftest.py` ожидает следующие proxies:

| Proxy name | Listen port | Upstream |
|---|---|---|
| `redis_cache` | 26379 | localhost:6379 |
| `redis_queue` | 26380 | localhost:6379 |
| `vault` | 28200 | localhost:8200 |
| `postgres` | 25432 | localhost:5432 |
| `smtp` | 21025 | localhost:1025 |
| `clickhouse` | 29000 | localhost:9000 |

Bootstrap script (one-time):

```bash
#!/bin/bash
API=http://localhost:8474
create_proxy() {
  curl -sX POST $API/proxies -d "{\"name\":\"$1\",\"listen\":\"$2\",\"upstream\":\"$3\"}"
}
create_proxy redis_cache  26379 localhost:6379
create_proxy redis_queue  26380 localhost:6379
create_proxy vault        28200 localhost:8200
create_proxy postgres     25432 localhost:5432
create_proxy smtp         21025 localhost:1025
create_proxy clickhouse   29000 localhost:9000
```

### 4. Configure backend services to use proxies

Edit `.env.test` (or equivalent):

```bash
REDIS_URL=redis://localhost:26379
VAULT_URL=http://localhost:28200
POSTGRES_URL=postgresql://user:pass@localhost:25432/db
SMTP_HOST=localhost
SMTP_PORT=21025
CLICKHOUSE_URL=http://localhost:29000
```

### 5. Run chaos tests

```bash
# Activate venv
source .venv/bin/activate

# Run all chaos tests
uv run pytest tests/chaos/ -v

# Expected: 69/69 pass (or 66/69 if some infra intentionally disabled)
```

### 6. Add toxic scenarios

Toxiproxy supports latency, bandwidth limits, connection drops. S46+ W4
scope: ensure baseline infra works. Per-scenario toxic injection
(``SCENARIOS = ("slow", "error", "disconnect")`` in
``tests/chaos/_chaos_helpers.py``) = S47+ D.

## CI Integration

Add toxiproxy sidecar to GitHub Actions / GitLab CI:

```yaml
# .github/workflows/chaos.yml (NEW, S47+ D)
services:
  toxiproxy:
    image: ghcr.io/shopify/toxiproxy
    ports:
      - 8474:8474
      - 26379:26379
      # ... other proxies
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Connection refused` on proxy | toxiproxy not running | `docker start toxiproxy` |
| Tests still skipped | `TOXIPROXY_URL` env not set | check conftest.py fixture |
| Random failures | Upstream service down | check `docker ps` for redis/vault/pg |

## TD-020 Status

- **S41 W6**: ADR-0111 formalize — 36/69 pass, 33 skipped.
- **S46 W4** (this): setup runbook (operator action).
- **S47+ D**: CI integration + full toxic scenarios.

## Estimated Effort

- Operator setup: ~30 min (one-time).
- CI integration: 1-2 waves.
- Toxic scenarios: 1-2 waves.

**Severity: low** (chaos coverage gap, not blocker; production protected
by WAF, rate limits, retry policies per ADR-0112, ADR-0113).
