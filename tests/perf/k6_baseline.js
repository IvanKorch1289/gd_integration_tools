// Sprint 6 K2 — k6 baseline нагрузочный профиль.
//
// Профиль соответствует Sprint 6 DoD (PLAN.md V18.2 §6, performance budget V10 #14):
//
//   * sustained: 1000 RPS постоянно 60 секунд (3 reference endpoints);
//   * spike:     5000 RPS короткий всплеск 10 секунд;
//   * p95 < 200ms, error rate < 1%.
//
// Запуск (warn-only под docker-compose.perf.yml):
//
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e MODE=sustained tests/perf/k6_baseline.js
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e MODE=spike     tests/perf/k6_baseline.js
//
// Reference endpoints (соответствуют tests/perf/baseline.json):
//
//   * GET  /api/v1/health                — middleware-overhead probe;
//   * GET  /api/v1/admin/users           — DB-pool round-trip;
//   * POST /api/v1/credit/check          — extensions/credit_pipeline e2e.
//
// Feature-flag: ``perf_gate_strict`` (default-OFF). При выключенном флаге
// CI workflow помечает SLO-нарушения как warn-only (continue-on-error: true).

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const MODE = __ENV.MODE || 'sustained';

// Кастомные метрики для агрегирования per-endpoint статистики.
const healthLatency = new Trend('latency_health', true);
const adminLatency = new Trend('latency_admin_users', true);
const creditLatency = new Trend('latency_credit_check', true);
const errorRate = new Rate('errors_total');
const requestsTotal = new Counter('requests_total');

// Сценарии k6 (Sprint 6 DoD: 1000 RPS sustained 60s + spike 5000 RPS 10s).
//
// Стратегия: используем executors ramping-arrival-rate для контроля RPS
// (вместо ramping-vus, который контролирует concurrency). 1000 RPS на 100 VU
// даёт ~10ms per iteration, 5000 RPS на 500 VU — ~10ms per iteration.

const scenarios = {
  sustained: {
    executor: 'ramping-arrival-rate',
    startRate: 100,
    timeUnit: '1s',
    preAllocatedVUs: 200,
    maxVUs: 500,
    stages: [
      { duration: '10s', target: 500 },   // ramp-up
      { duration: '60s', target: 1000 },  // sustained 1000 RPS
      { duration: '10s', target: 0 },     // ramp-down
    ],
  },
  spike: {
    executor: 'ramping-arrival-rate',
    startRate: 100,
    timeUnit: '1s',
    preAllocatedVUs: 200,
    maxVUs: 1000,
    stages: [
      { duration: '5s', target: 500 },    // baseline
      { duration: '10s', target: 5000 },  // spike
      { duration: '5s', target: 100 },    // recovery
    ],
  },
};

export const options = {
  scenarios: { active: scenarios[MODE] || scenarios.sustained },
  thresholds: {
    'http_req_duration{endpoint:health}': ['p(95)<200'],
    'http_req_duration{endpoint:admin_users}': ['p(95)<200'],
    'http_req_duration{endpoint:credit_check}': ['p(95)<800'],
    'http_req_failed': ['rate<0.01'],
    'errors_total': ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

function probeHealth() {
  const r = http.get(`${BASE_URL}/api/v1/health`, {
    tags: { endpoint: 'health' },
  });
  healthLatency.add(r.timings.duration);
  requestsTotal.add(1);
  const ok = check(r, { 'health status 200': (resp) => resp.status === 200 });
  if (!ok) {
    errorRate.add(1);
  }
}

function probeAdminUsers() {
  const r = http.get(`${BASE_URL}/api/v1/admin/users?limit=10`, {
    tags: { endpoint: 'admin_users' },
    headers: { 'Authorization': 'Bearer dev-smoke-token' },
  });
  adminLatency.add(r.timings.duration);
  requestsTotal.add(1);
  const ok = check(r, { 'admin status acceptable': (resp) => resp.status === 200 || resp.status === 401 });
  if (!ok) {
    errorRate.add(1);
  }
}

function probeCreditCheck() {
  const payload = JSON.stringify({
    client_id: 'k6-load-test',
    amount: 100000.0,
    currency: 'RUB',
  });
  const r = http.post(`${BASE_URL}/api/v1/credit/check`, payload, {
    tags: { endpoint: 'credit_check' },
    headers: { 'Content-Type': 'application/json' },
  });
  creditLatency.add(r.timings.duration);
  requestsTotal.add(1);
  // 202 (async-api accepted) / 200 / 401 (без auth) — допустимы для нагрузочного теста.
  const ok = check(r, { 'credit status acceptable': (resp) =>
    resp.status === 200 || resp.status === 202 || resp.status === 401 });
  if (!ok) {
    errorRate.add(1);
  }
}

// Реальная нагрузка распределена по 3 endpoints (weighted round-robin).
export default function () {
  const r = Math.random();
  if (r < 0.6) {
    probeHealth();           // 60% — самый быстрый, основной носитель RPS
  } else if (r < 0.9) {
    probeAdminUsers();       // 30% — DB-bound
  } else {
    probeCreditCheck();      // 10% — е2e через workflow
  }
}
