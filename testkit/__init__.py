"""Testkit — переиспользуемые pytest-фикстуры для интеграционных тестов.

Назначение пакета:
    Содержит фабрики тестовых сертификатов, контейнеров IdP (Keycloak),
    стабов внешних API и прочих ресурсов, которые требуются нескольким
    test-suite одновременно. Импорт фикстур выполняется явно из
    ``conftest.py`` тестового пакета — pytest11 entry-point на данный
    момент не используется, чтобы избежать конфликта с существующим
    конфигом.

Модули:
    auth_fixtures: SAML SSO (Keycloak via testcontainers, IdP/SP metadata).
    mtls_fixtures: Self-signed CA + server/client cert chain для mTLS.

Пакет добавлен в Sprint 3 W1 К1 (Security) как каркас для SAML/mTLS E2E.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
