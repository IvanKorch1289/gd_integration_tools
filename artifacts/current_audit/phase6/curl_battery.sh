#!/usr/bin/env bash
# Phase 6 — cURL battery for live app (deferred: requires running infra).
#
# USAGE (when infra is up):
#   make dev &     # boots uvicorn on :8000 by default
#   ./artifacts/current_audit/phase6/curl_battery.sh http://127.0.0.1:8000
#
# This battery was generated but NOT executed in the audit conversation because
# MongoDB / Postgres / Redis / Vault are not running in this dev container.
# App correctly fail-fasts on missing infrastructure (verified in uvicorn.log):
#   "LifecycleStartupError: start_mongo_client timeout 30.0s"
#
# Each line below is the command executed (or to be executed) followed by the
# expected status / artifact path. STATUS column reflects what would happen
# when infra is up (per FastAPI auto-registered routes).

set -euo pipefail
HOST=${1:-http://127.0.0.1:8000}
RES=artifacts/current_audit/phase6/curl_results.jsonl
mkdir -p artifacts/current_audit/phase6

probe() {
    local name=$1
    local method=$2
    local url=$3
    local expect=$4
    local extra_headers=${5:-""}
    local body=${6:-""}
    local code
    local elapsed
    if [ -n "$body" ]; then
        code=$(curl -s -o /tmp/_b.json -w "%{http_code}|%{time_total}|%{size_download}" \
              -X "$method" -H "Content-Type: application/json" \
              $extra_headers -d "$body" "$HOST$url")
    else
        code=$(curl -s -o /tmp/_b.json -w "%{http_code}|%{time_total}|%{size_download}" \
              -X "$method" $extra_headers "$HOST$url")
    fi
    IFS='|' read -r status time size <<< "$code"
    # JSON-escape name (colons) and expect for valid JSONL.
    safe_name=$(printf '%s' "$name" | sed 's/"/\\"/g')
    safe_path=$(printf '%s' "$url" | sed 's/"/\\"/g')
    safe_expect=$(printf '%s' "$expect" | sed 's/"/\\"/g')
    printf '{"name":"%s","method":"%s","path":"%s","status":%s,"time_s":%s,"bytes":%s,"expect":"%s"}\n' \
        "$safe_name" "$method" "$safe_path" "$status" "$time" "$size" "$safe_expect" >> "$RES"
    printf "  %-45s %3s %6ss %6sB  exp:%s\n" "$name" "$status" "$time" "$size" "$expect"
}

: > "$RES"
echo "=== liveness & openapi ==="
probe "live:healthz"          GET   "/api/v1/health/live"     200
probe "live:healthz-full"     GET   "/api/v1/health/full"     200
probe "ready:readiness"       GET   "/api/v1/health/ready"    200
probe "openapi:json"          GET   "/openapi.json"           200
probe "openapi:docs-swagger"  GET   "/docs"                   200
probe "openapi:docs-redoc"    GET   "/redoc"                  200

echo "=== action dispatch ==="
probe "action:list"           GET   "/api/v1/actions"                 200
probe "action:dispatch-anon"  POST  "/api/v1/actions/system.info/execute" "401-or-403"
probe "action:dispatch-ok"    POST  "/api/v1/actions/system.info/execute" "200" \
        "-H 'Authorization: Bearer \${TOKEN}'"

echo "=== protocols ==="
probe "graphql:ui"            GET   "/graphql"                200
probe "graphql:schema"        GET   "/api/v1/graphql/schema"  200
probe "soap:wsdl"             GET   "/soap?wsdl"              200
probe "websocket:open-handshake"  GET   "/ws"               101
probe "sse:stream"            GET   "/api/v1/sse/stream"      200

echo "=== feature flag toggle ==="
probe "ff:disabled"           GET   "/api/v1/feature_flag/foo"     200 \
        "-H 'X-Feature-Flags: foo=false'"
probe "ff:enabled"            GET   "/api/v1/feature_flag/foo"     200 \
        "-H 'X-Feature-Flags: foo=true'"

echo "=== tenant A/B isolation ==="
probe "tenantA:probe"         GET   "/api/v1/tenants/probe"   200 \
        "-H 'X-Tenant-Id: tenant-a'"
probe "tenantB:probe"         GET   "/api/v1/tenants/probe"   200 \
        "-H 'X-Tenant-Id: tenant-b'"

echo "=== negative paths ==="
probe "404:not-found"         GET   "/api/v1/this-route-does-not-exist"  404
probe "405:bad-method"        DELETE "/api/v1/health/live"              405
probe "422:bad-body"          POST  "/api/v1/actions/system.info/execute" 422 \
        "-H 'Authorization: Bearer \${TOKEN}'" \
        "{\"bad\":\"shape\"}"

echo "=== dsl console ==="
probe "dsl:routes-list"       GET   "/api/v1/dsl/routes"               200
probe "dsl:routes-exec"       POST  "/api/v1/dsl/routes/health/exec"   200

echo "=== admin auth ==="
probe "admin:login-form"      GET   "/api/v1/admin/auth/login"         200
probe "admin:csrf"            GET   "/api/v1/admin/auth/csrf"          200

echo "all probes written to: $RES"
