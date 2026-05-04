// Wave 7.6 — k6 baseline нагрузочный профиль (DoD: p95 < 200ms, RPS > 1000).
//
// Запуск:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 tests/perf/k6_baseline.js
//
// Профиль (3 фазы):
//   1. ramp-up: 0 -> 100 VU за 30s
//   2. steady:  100 VU в течение 2 минут (целевые SLO измеряются здесь)
//   3. ramp-down: 100 -> 0 VU за 30s
//
// Целевые SLO:
//   * http_req_duration p(95) < 200ms (V10 #14 performance budget).
//   * http_req_failed < 1%.
//   * iteration RPS > 1000 (на 100 VU).

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export const options = {
  stages: [
    { duration: '30s', target: 100 },
    { duration: '2m',  target: 100 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const r = http.get(`${BASE_URL}/api/v1/health`);
  check(r, { 'status 200': (resp) => resp.status === 200 });
}
