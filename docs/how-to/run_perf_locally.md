# Run perf locally

Запуск SLO-gate против локального backend.

## Предусловия

* `k6` установлен (https://k6.io/docs/getting-started/installation/);
* `make dev-light` запущен в фоне.

## Smoke-профиль

```bash
make perf-smoke BASE_URL=http://127.0.0.1:8000
```

## Enforced gate

```bash
make perf-gate BASE_URL=http://127.0.0.1:8000
```

* `p95 < 200ms`
* `RPS > 1000`
* `error rate < 1%`

## Длинный профиль

```bash
make perf-full BASE_URL=http://127.0.0.1:8000
```

3 минуты, 100 VU, mixed-mix (health + admin-routes + admin-actions + readiness).

## CI

`.github/workflows/perf.yml` запускает `k6_action_routes.js` на каждом PR
и комментирует summary в обсуждении.
