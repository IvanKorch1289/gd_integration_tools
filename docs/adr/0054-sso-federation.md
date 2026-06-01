# ADR-0054 — SSO Federation (SAML 2.0 + per-tenant IdP)

* Статус: Accepted (Sprint 3, К1 W3, 2026-05-13)
* Связано с: V15 R-V15-1, V15 Auth-стек (V7); PLAN.md V18.1 §S3 К1 W3 шаг 2.

## Контекст

R-V15-1 (capability plugin contract) и V7 Auth-стек требуют, чтобы non-public
endpoints поддерживали корпоративный Single Sign-On с per-tenant identity
provider'ами (Keycloak/Okta/AzureAD). В банке несколько тенантов с разными
IdP, и часть из них использует только SAML 2.0 (Okta SAML, AzureAD SAML).
JWT-bridge нужен для совместимости с внутренним FastAPI auth_guard.

Открытые вопросы:

* Какой протокол — SAML 2.0 или OIDC (или оба)?
* Где хранить per-tenant IdP-конфигурацию?
* Как маппить IdP-группы на capability-scope'ы?

## Решение

1. **SAML 2.0 + JWT bridge** — primary поток. SP (Service Provider) принимает
   SAML AuthnResponse, валидирует подпись через IdP-сертификат, извлекает
   ``NameID`` и атрибуты, и выпускает короткоживущий internal JWT (TTL 15 минут).
   Все downstream-сервисы используют JWT для авторизации (как для legacy
   API-key + новый mTLS).

2. **Per-tenant IdP Registry в Vault** — путь ``secret/data/sso/<tenant>/idp``
   с полями:
   * ``entity_id`` — IdP entity-id;
   * ``sso_url`` — IdP SAML SSO URL;
   * ``x509_cert`` — публичный сертификат IdP (PEM);
   * ``allow_create_user`` — bool (autoprovisioning);
   * ``groups_to_capabilities`` — JSON-mapping ``{"<idp-group>": ["<cap-name>:<scope>", ...]}``.

   Регистрация через ``services/auth/sso_registry.py::SsoRegistry`` —
   read-through cache с TTL 300 сек.

3. **Groups → Capabilities mapping** — после успешной SAML-аутентификации
   извлекаются IdP-группы (Okta ``groups`` claim, AzureAD ``wids`` claim,
   Keycloak ``roles``); каждая мапится на 0..N capability-scope'ов через
   ``groups_to_capabilities``. Результат прикрепляется к JWT как ``caps``-claim
   и используется ``CapabilityGate.declare(...)`` при инициализации tenant-сессии.

4. **Refresh-cron** — IdP-метаданные (``x509_cert``, ``sso_url``) обновляются
   ежесуточно через ``infrastructure/scheduler/sso_metadata_refresh.py`` (cron
   ``0 3 * * *``). Cache инвалидируется по signal от Vault audit-log
   (``secret_modified`` event).

5. **Fallback на API-key + mTLS** — если SAML недоступен или IdP вернул ошибку,
   tenant может использовать API-key (R1) или mTLS (Wave 1.3) как backup —
   определяется ``auth.fallback_chain = ["saml", "mtls", "api_key"]`` в settings.

## Последствия

* `+` Federation поверх SAML 2.0 покрывает 95% корпоративных IdP без custom
  адаптеров.
* `+` Per-tenant конфигурация в Vault — изоляция секретов между tenants
  + audit-trail.
* `+` Capability-mapping переиспользует существующий ``CapabilityGate``,
  не вводя параллельной системы permissions.
* `+` Refresh-cron исключает stale-cert issues (типичный source of failure).
* `−` SAML XML парсинг требует ``python3-saml>=1.16`` или ``signxml``;
  выбран ``python3-saml`` (более зрелый, OneLogin maintainer).
* `−` JWT short-lived (15 мин) требует refresh-token flow; реализуется
  как cookie-based refresh в R2 (Sprint 5).
* `−` OIDC откладывается на Sprint 7 (после первого production-rollout SAML).

## Альтернативы рассмотрены и отклонены

* **OIDC-only** — отклонено, потому что у банка часть IdP не поддерживает
  OIDC (Okta SAML, legacy SiteMinder).
* **Authlib SAML** — отклонено: меньшая зрелость, нет встроенного
  signature-validation flow.
* **Custom SAML XML парсер** — отклонено: high-risk (XML signature wrapping,
  XXE), лучше переиспользовать audited библиотеку.

## CI gates (Sprint 3 К1 W3)

* ``make ci`` — composite (format/lint/type/security/WAF strict + AI safety).
* ``.github/workflows/security.yml`` — bandit + safety + pip-audit + gitleaks
  + trivy-fs (ADR-0054 W3 step 3).
* ``tests/integration/auth/test_sso_*.py`` — SAML response mocking
  (мок-IdP через ``saml-tools``-fixture).

## Roadmap

* **Sprint 3 W3 (текущий)** — ADR + SsoRegistry skeleton + groups→caps mapping.
* **Sprint 5 R2** — refresh-token cookie flow, AzureAD первый production.
* **Sprint 6** — OIDC рядом с SAML (без замены), интеграционный тест suite
  с реальным Keycloak.
