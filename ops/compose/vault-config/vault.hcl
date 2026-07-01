# Vault production-like config (S170 P0-6).
#
# Used by docker-compose.prod.yml для local full-stack testing.
# НЕ является production-ready: для реального prod требуется
# HA storage backend (Raft/Consul), external TLS termination,
# unseal через облако/KMS. Этот файл — middle-ground между
# -dev (in-memory, no TLS) и полным prod-grade deployment.
#
# Reference: https://developer.hashicorp.com/vault/docs/configuration

storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1  # compose-level TLS termination через reverse proxy
}

default_lease_ttl = "168h"
max_lease_ttl     = "720h"

ui = true
