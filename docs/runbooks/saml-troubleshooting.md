# Runbook: SAML SSO troubleshooting

> Owner: K1.

## Symptom

* User не может залогиниться через `/auth/saml/login`.
* `/auth/saml/acs` возвращает 401 "SAML validation failed".
* InResponseTo не совпадает → "replay defence".

## Detection

```bash
# Логи:
kubectl logs deploy/<service> | grep saml
# saml.login.initiated request_id=...
# saml.acs.rejected reason="..."
```

## Diagnosis

### Replay defence сработал
* `InResponseTo unknown or already used` → AuthnRequest ID не известен.
* Возможные причины:
  - Cookie session-storage не работает (Redis down?).
  - Replay-window (`replay_window_seconds`, default 300s) истёк.
  - Multiple SP instances без shared session-storage.

### Signature mismatch
* IdP X509 cert не совпадает с конфигом SP.
* Solution: verify через `parse_idp_metadata` (S6 K1 W1).

### Missing required attributes
* `tenant_from_saml_attributes` raises `ValueError: tenant_id required`.
* Configure attribute mapping в IdP (см. `core/auth/saml/sp_handler.py`).

## Mitigation

### Restart SP-session-store
```bash
# Если Redis-backed:
kubectl exec deploy/<redis> -- redis-cli FLUSHDB
# затем user логинится заново
```

### Force certificate refresh
```bash
# Если IdP cert ротировался:
curl -X POST http://<api>/api/v1/admin/saml/reload-metadata
```

### Verify config
```bash
.venv/bin/python -c "
from src.backend.core.auth.saml import SamlBackend, SamlConfig
config = SamlConfig(
    sp_entity_id='...',
    sp_acs_url='...',
    sp_x509_cert='...',
    sp_private_key='...',
    idp_entity_id='...',
    idp_sso_url='...',
    idp_x509_cert='...',
)
backend = SamlBackend(config=config)
print('python3-saml available:', backend.is_available())
"
```

## Verification

* `curl http://<api>/api/v1/auth/saml/login` → 302 redirect к IdP.
* После SAML auth → `saml_session` cookie set, principal logged.
* `saml.acs.success` event в audit.

## Rollback to JWT

При sustained SAML failures — переключить default auth:

```bash
kubectl set env deploy/<service> DEFAULT_AUTH=jwt
```

## Postmortem template

См. `incident-response.md`. Обязательно:
* request_id первой failed AuthnRequest;
* IdP version + cert fingerprint;
* какой attribute был missing/wrong.
