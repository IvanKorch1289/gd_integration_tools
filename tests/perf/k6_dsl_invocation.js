// К5 (Wave K5/perf-gate) — DSL route invocation профиль.
//
// Изоляция от К2: ROUTE_ID читается из env-var. К2 при готовности
// route.toml full-cycle подменяет ROUTE_ID без изменения JS.
//
// Запуск:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e ROUTE_ID=health.ping \
//          tests/perf/k6_dsl_invocation.js

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const ROUTE_ID = __ENV.ROUTE_ID || 'health.ping';

export const options = {
  stages: [
    { duration: '15s', target: 25 },
    { duration: '60s', target: 75 },
    { duration: '15s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<300'],
    http_req_failed: ['rate<0.02'],
  },
};

export default function () {
  const payload = JSON.stringify({ route_id: ROUTE_ID, payload: {} });
  const r = http.post(`${BASE_URL}/api/v1/dsl/invoke`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });
  check(r, { 'status 2xx/4xx': (resp) => resp.status >= 200 && resp.status < 500 });
}
