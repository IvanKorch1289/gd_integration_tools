// К5 (Wave K5/perf-gate) — read-heavy профиль admin/routes endpoint.
//
// Запуск:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 tests/perf/k6_action_routes.js
//
// SLO (V10 #14):
//   * http_req_duration p(95) < 200ms
//   * http_req_failed < 1%
//   * iteration RPS > 1000

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export const options = {
  stages: [
    { duration: '20s', target: 50 },
    { duration: '60s', target: 100 },
    { duration: '20s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'],
    http_req_failed: ['rate<0.01'],
    iterations: ['rate>1000'],
  },
};

export default function () {
  const r = http.get(`${BASE_URL}/api/v1/admin/routes`);
  check(r, { 'status 2xx/4xx': (resp) => resp.status >= 200 && resp.status < 500 });
}
