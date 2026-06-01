# Reference rego scaffold для AuthorizationGateway.opa_step (S18 W3, S-L8-2).
#
# Назначение:
#   Минимальный пример OPA-policy, который вызывается через
#   `OPAClient.query("authz/default", input_doc)`. Production-политики
#   (per-route / per-tenant) расширяют этот пакет — см. wave S19+
#   carryover в `.claude/KNOWN_ISSUES.md`.
#
# Контракт input:
#   {
#     "principal": "<plugin-id-или-user>",
#     "resource":  "<capability-name-или-endpoint-path>",
#     "action":    "<read|write|check|invoke>",
#     "tenant_id": "<tenant_id-из-RequestContext>",
#     "correlation_id": "<squoznoy-id>"
#   }
#
# Контракт output (читается OPAClient.query):
#   {
#     "allow":   true|false,
#     "reasons": ["<строки-причин>"]
#   }
#
# Запуск локального OPA:
#   opa run --server --addr :8181 \
#     src/backend/infrastructure/policy/opa/policies/
#
# Syntax-check без OPA-server:
#   opa eval -d authz_default.rego "data.authz.default.allow" \
#     --input '{"principal":"p1","resource":"db.read","action":"check","tenant_id":"acme"}'

package authz.default

import future.keywords.if
import future.keywords.in

# default deny — fail-closed (соответствует OPAClient `allow=False` при errors)
default allow := false
default reasons := ["no_matching_rule"]

# Demo allow rule: principal "demo_admin" → разрешён read-action в любом tenant.
# Production-политики живут в отдельных rego-файлах (этот файл — scaffold).
allow if {
    input.principal == "demo_admin"
    input.action == "read"
}

reasons := ["demo_admin_read"] if {
    input.principal == "demo_admin"
    input.action == "read"
}
