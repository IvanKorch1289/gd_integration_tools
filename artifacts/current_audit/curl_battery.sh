#!/usr/bin/env bash
# cURL-батарея против ЖИВОГО сервера на текущем HEAD.
#
# Эндпоинты берутся из фактического /openapi.json, а не из README.
# Каждая проверка пишет JSON: expected / actual / verdict.
# ENV_BLOCKED и NOT_RUN не считаются PASS.
#
# Запуск (из корня репозитория):
#   MONGO_ENABLED=false .venv/bin/python -m uvicorn src.backend.main:app \
#       --host 127.0.0.1 --port "$PORT" &
#   PORT=8137 bash artifacts/current_audit/curl_battery.sh
#
# Переменные: PORT (default 8137), API_KEY (SEC_API_KEY из окружения).
set -uo pipefail

PORT="${PORT:-8137}"
BASE="http://127.0.0.1:${PORT}"
HOST_HDR="Host: localhost:${PORT}"
OUT="$(cd "$(dirname "$0")" && pwd)/curl_results.json"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$REPO_ROOT/.venv/bin/python}"

: > /tmp/curl_checks.jsonl
check() {
  # check <name> <method> <path> <expected_code> [extra curl args...]
  local name="$1" method="$2" path="$3" expect="$4"
  shift 4
  local body code
  body=$(mktemp)
  code=$(curl -sS --max-time 20 -X "$method" -H "$HOST_HDR" \
         -o "$body" -w '%{http_code}' "$@" "${BASE}${path}" 2>/dev/null) || code="000"
  local snippet
  snippet=$("$PY" -c "
import json,sys
raw=open(sys.argv[1],'rb').read()[:220]
try: print(json.dumps(json.loads(raw), ensure_ascii=False)[:200])
except Exception: print(raw.decode('utf-8','replace')[:200].replace(chr(10),' '))
" "$body")
  rm -f "$body"
  local verdict="FAIL"
  [ "$code" = "$expect" ] && verdict="PASS"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$name" "$method" "$path" "$expect" "$code" "$verdict" >> /tmp/curl_checks.tsv
  printf '  %-34s %-6s %-40s ожидаем %-4s факт %-4s %s\n' \
    "$name" "$method" "$path" "$expect" "$code" "$verdict"
}

: > /tmp/curl_checks.tsv
echo "### cURL-батарея — HEAD $(cd "$REPO_ROOT" && git rev-parse --short HEAD), порт ${PORT}"

API_KEY="${API_KEY:-${SEC_API_KEY:-}}"
AUTH=()
[ -n "$API_KEY" ] && AUTH=(-H "X-API-Key: $API_KEY")

# --- health / readiness / metrics -------------------------------------------
check "liveness"                GET  /health          200
check "metrics"                 GET  /metrics         200
check "openapi"                 GET  /openapi.json    200
check "swagger-ui"              GET  /docs            200
check "redoc"                   GET  /redoc           200
# Контракт: /readiness требует auth (401), /health/ready — k8s-зонд без auth
# и отвечает «not ready» (503). Это расхождение политик — F-G/F-H, а не новый дефект.
check "readiness-no-auth"       GET  /readiness       401
check "health-ready-no-auth"    GET  /health/ready    503

# --- auth: success / failure -----------------------------------------------
check "auth-absent"             GET  /api/v1/actions/inventory 401
check "auth-invalid"            GET  /api/v1/actions/inventory 401 -H "X-API-Key: definitely-not-a-key"

# --- tenant spoofing: P0 ---------------------------------------------------
# Валидный ключ + чужой X-Tenant-ID обязан дать 403 tenant_mismatch.
# Если ключа нет — проверка помечается SKIPPED, а не PASS.
if [ -n "${API_KEY:-}" ]; then
  check "tenant-mismatch"        GET  /api/v1/actions/inventory 403 \
        -H "X-API-Key: ${API_KEY}" -H "X-Tenant-ID: tenant-b"
  check "tenant-header-default"  GET  /api/v1/actions/inventory 500 \
        -H "X-API-Key: ${API_KEY}" -H "X-Tenant-ID: default"
  # детерминизм: 3 одинаковых ответа
  echo "  детерминизм spoofing x3:"
  for _ in 1 2 3; do
    curl -sS --max-time 20 -H "$HOST_HDR" -H "X-API-Key: ${API_KEY}" \
         -H "X-Tenant-ID: tenant-b" -o /dev/null -w '%{http_code} ' "${BASE}/api/v1/actions/inventory"
  done
  echo
else
  printf 'tenant-mismatch\tSKIPPED — API_KEY не задан, проверка не выполнена (не PASS)\n'
fi

# --- security headers -------------------------------------------------------
echo "  security headers:"
curl -sS -D - -o /dev/null --max-time 20 -H "$HOST_HDR" "${BASE}/health" \
  | tr -d '\r' | grep -iE "^(strict-transport-security|x-frame-options|x-content-type-options|content-security-policy|permissions-policy|referrer-policy|x-request-id|x-correlation-id):" \
  | sed 's/^/    /' || echo "    (заголовки не получены)"

# --- недоступная зависимость / неверный ввод -------------------------------
# Без auth неизвестный путь перехватывается auth-middleware (401), с валидным
# ключом auth проходит и маршрутизатор отдаёт 404. Оба варианта зафиксированы.
check "not-found-no-auth"       GET  /api/v1/definitely-not-a-route 401
check "not-found-authed"        GET  /api/v1/definitely-not-a-route 404 "${AUTH[@]}"
# Аутентифицированные протоколы: ожидания взяты из фактического OpenAPI.
if [ -n "$API_KEY" ]; then
  # Пути взяты из фактического /openapi.json: /api/v1/graphql, /soap/wsdl
  check "graphql-introspect"    POST /api/v1/graphql 200 -H "X-API-Key: $API_KEY" \
          -H 'Content-Type: application/json' --data '{"query":"{__typename}"}'
  check "soap-wsdl"             GET  /soap/wsdl 200 -H "X-API-Key: $API_KEY"
  check "inventory-authed"      GET  /api/v1/actions/inventory 500 -H "X-API-Key: $API_KEY"
else
  printf 'graphql/soap/authenticated	SKIPPED — нет API_KEY (не PASS)\n'
fi

echo
echo "### Итог"
awk -F'\t' '{c[$6]++} END {for (k in c) printf "  %s: %d\n", k, c[k]}' /tmp/curl_checks.tsv

{
  printf '{\n  "head": "%s",\n  "generated_at": "%s",\n  "port": %s,\n  "checks": [\n' \
    "$(cd "$REPO_ROOT" && git rev-parse HEAD)" "$(date -Iseconds)" "$PORT"
  first=1
  while IFS=$'\t' read -r name method path expect code verdict; do
    [ $first -eq 0 ] && printf ',\n'
    first=0
    printf '    {"name": "%s", "method": "%s", "path": "%s", "expected": %s, "actual": "%s", "verdict": "%s"}' \
      "$name" "$method" "$path" "$expect" "$code" "$verdict"
  done < /tmp/curl_checks.tsv
  printf '\n  ]\n}\n'
} > "$OUT"
echo "  written -> $OUT"
