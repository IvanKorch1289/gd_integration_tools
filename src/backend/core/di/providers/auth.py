"""Auth domain providers — API keys, JWT backend (joserfc), JWKS cache.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 6 funcs (3 get + 3 set) + 2 private helpers
(``_build_jwks_cache_or_none``, ``_build_jwt_blacklist_or_none``).

Singleton cache ``_overrides`` is per-domain (NOT shared).

Cross-domain ref: :func:`_build_jwt_blacklist_or_none` вызывает
:func:`src.backend.core.di.providers.cache.get_redis_kv_client_provider`
через **late import** (внутри функции) — нет module-level circular dep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.backend.core.di.module_registry import resolve_module

if TYPE_CHECKING:
    from src.backend.core.auth.jwt_backend import JwtBackend

_overrides: dict[str, Any] = {}


# ─────────────── Wave 6.5a: entrypoints/api/dependencies — auth ───────────────


def get_api_key_manager_provider() -> Any:
    """Возвращает singleton ``APIKeyManager``.

    Реализация: ``infrastructure.security.api_key_manager.get_api_key_manager``.
    Используется в ``entrypoints/api/dependencies/{auth,auth_selector}.py``.
    """
    if "api_key_manager" in _overrides:
        return _overrides["api_key_manager"]
    module = resolve_module("security.api_key_manager")
    return module.get_api_key_manager()


def set_api_key_manager_provider(manager: Any) -> None:
    """Установить override для ``api_key_manager`` provider (test-инжекция)."""
    _overrides["api_key_manager"] = manager


# ─────────────── Wave [s2/k1-2-jwt-jwks]: JWT backend (joserfc) ───────────────


def get_jwt_backend_provider() -> JwtBackend:
    """Возвращает singleton :class:`JwtBackend` (joserfc-based).

    Wave [s2/k1-2-jwt-jwks]: заменяет прямое использование ``python-jose``
    в :func:`_verify_jwt` (auth_selector). Backend строится из
    :class:`SecureSettings` (для HS-алгоритмов) либо :class:`JwksSettings`
    (для RS/ES — pull JWKS из IdP). Если в overrides — берётся override.

    ADR-0411: **режим определяется алгоритмом** и режимы взаимно
    исключаются — симметричный (``HS*``) или асимметричный
    (``RS*``/``ES*``). Смешивать нельзя: иначе публичный ключ можно
    использовать как HMAC-секрет (algorithm confusion). «Тихого» downgrade
    нет: в асимметричном режиме shared secret не используется, а в
    симметричном — не подставляется JWKS.

    Returns:
        Типизированный экземпляр :class:`JwtBackend`.

    Raises:
        ValueError: Если для асимметричного алгоритма не задан ни
            ``security.jwks_url``, ни ``security.jwt_public_key_path``.

    """
    if "jwt_backend" in _overrides:
        return cast("JwtBackend", _overrides["jwt_backend"])
    from src.backend.core.auth.jwt_backend import JwtBackend
    from src.backend.core.config.security import secure_settings

    algorithm = str(secure_settings.algorithm)
    secret_value = _secret_value(secure_settings.secret_key)

    if algorithm.startswith("HS"):
        # Симметричный режим: только secret, jwks/public_key не подключаем.
        backend = JwtBackend(
            algorithms=[algorithm],
            secret=secret_value,
            leeway=getattr(secure_settings, "jwt_leeway", 60),
            blacklist=_build_jwt_blacklist_or_none(),
        )
    else:
        # Асимметричный режим: публичный ключ (PEM) и/или JWKS.
        jwks = _build_jwks_cache_or_none()
        public_key = _load_public_key_or_none()
        if jwks is None and public_key is None:
            raise ValueError(
                f"JWT backend: для алгоритма {algorithm} нужен "
                "security.jwks_url (JWKS-endpoint) или "
                "security.jwt_public_key_path (PEM публичного ключа)."
            )
        kid = str(getattr(secure_settings, "jwt_kid", "") or "") or None
        backend = JwtBackend(
            algorithms=[algorithm],
            secret=None,
            jwks=jwks,
            public_key=public_key,
            kid=kid,
            leeway=getattr(secure_settings, "jwt_leeway", 60),
            blacklist=_build_jwt_blacklist_or_none(),
        )
    _overrides["jwt_backend"] = backend
    return backend


def _secret_value(raw: Any) -> str:
    """Достаёт значение ``SecretStr`` без маскирования."""
    return raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)


def set_jwt_backend_provider(backend: Any) -> None:
    """Установить/сбросить override для ``jwt_backend`` provider (test-инжекция).

    ``None`` сбрасывает override и возвращает к singleton.
    """
    if backend is None:
        _overrides.pop("jwt_backend", None)
    else:
        _overrides["jwt_backend"] = backend


# ─────────────── JWKS cache (singleton, опциональный) ───────────────


def get_jwks_cache_provider() -> Any:
    """Возвращает singleton :class:`JwksCache` или ``None``.

    JWKS-кеш активируется только если ``SecureSettings.jwks_url`` задан.
    """
    if "jwks_cache" in _overrides:
        return _overrides["jwks_cache"]
    cache = _build_jwks_cache_or_none()
    _overrides["jwks_cache"] = cache
    return cache


def set_jwks_cache_provider(cache: Any) -> None:
    """Установить/сбросить override для ``jwks_cache`` provider (test-инжекция).

    ``None`` сбрасывает override и возвращает к singleton.
    """
    if cache is None:
        _overrides.pop("jwks_cache", None)
    else:
        _overrides["jwks_cache"] = cache


def _build_jwks_cache_or_none() -> Any:
    """Создаёт :class:`JwksCache` если ``SecureSettings.jwks_url`` задан."""
    from src.backend.core.config.security import secure_settings

    url = getattr(secure_settings, "jwks_url", None)
    if not url:
        return None
    from src.backend.core.auth.jwks_cache import JwksCache

    ttl = getattr(secure_settings, "jwks_cache_ttl", 300)
    timeout = getattr(secure_settings, "jwks_fetch_timeout", 5.0)
    return JwksCache(url, ttl=ttl, timeout=timeout)


def _load_public_key_or_none() -> Any:
    """Загружает публичный ключ (PEM) из ``security.jwt_public_key_path``.

    Returns:
        JWK-объект joserfc или ``None``, если путь не задан.

    Raises:
        FileNotFoundError: Если файл указан, но отсутствует.
        ValueError: Если PEM нечитаем или это не RSA/EC-ключ.

    """
    from src.backend.core.config.security import secure_settings

    path = str(getattr(secure_settings, "jwt_public_key_path", "") or "")
    if not path:
        return None
    from src.backend.core.security.jwt_keys import load_public_key_pem

    return load_public_key_pem(path)


def _build_jwt_blacklist_or_none() -> Any:
    """Создаёт :class:`RedisJwtBlacklist` если ``blacklist_enabled=True``.

    Cross-domain ref: использует :func:`cache.get_redis_kv_client_provider`
    через late import внутри функции (нет module-level circular dep).
    """
    from src.backend.core.config.security import secure_settings

    if not getattr(secure_settings, "jwt_blacklist_enabled", False):
        return None
    try:
        from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

        # Late import — avoids module-level circular dep (auth ↔ cache).
        from src.backend.core.di.providers.cache import get_redis_kv_client_provider

        redis = get_redis_kv_client_provider()
        return RedisJwtBlacklist(redis)
    except (
        ImportError,
        AttributeError,
        RuntimeError,
        ConnectionError,
        OSError,
    ) as redis_exc:  # pragma: no cover — Redis может быть недоступен в test/dev_light
        # cycle-9/D-AUDIT-1079: narrow exceptions + observability.
        # ImportError — module missing, AttributeError — API change,
        # RuntimeError — DI unavailable, ConnectionError/OSError — Redis
        # network failure.
        import logging

        logging.getLogger(__name__).debug(
            "auth_provider.redis_jwt_blacklist_unavailable",
            extra={"error": str(redis_exc)},
        )
        return None


__all__ = (
    "get_ad_directory_client_provider",
    "get_api_key_manager_provider",
    "get_jwks_cache_provider",
    "get_jwt_backend_provider",
    "set_ad_directory_client_provider",
    "set_api_key_manager_provider",
    "set_jwks_cache_provider",
    "set_jwt_backend_provider",
)


# ─────────────── Cycle 29 P1-#2: AD/LDAP directory client provider ────────────


def get_ad_directory_client_provider() -> Any:
    """Вернуть зарегистрированную factory для создания LDAP-клиента.

    Factory регистрируется composition-слоем (plugins/composition) через
    ``set_ad_directory_client_provider``. Возвращает callable, принимающий
    ``config`` и ``connection_factory`` kwargs.

    Raises:
        RuntimeError: Если composition-слой не зарегистрировал factory.

    """
    if "ad_directory_client_factory" in _overrides:
        return _overrides["ad_directory_client_factory"]
    raise RuntimeError(
        "LDAP client factory is not registered by the composition layer. "
        "Call set_ad_directory_client_provider(factory) at startup."
    )


def set_ad_directory_client_provider(factory: Any) -> None:
    """Зарегистрировать/сбросить factory для LDAP-клиента (composition/test).

    ``None`` сбрасывает registration.
    """
    if factory is None:
        _overrides.pop("ad_directory_client_factory", None)
    else:
        _overrides["ad_directory_client_factory"] = factory


# ─────────────── S48 W10: core → services.security layer bridge ──────────────


def get_security_facade_provider() -> Any:
    """DI-provider для ``services.security.SecurityFacade``.

    S48 W10 swarm audit (A1 Core #5): раньше ``core/auth/facade.py:318,463``
    делали inline import из ``src.backend.services.security.facade`` —
    нарушение layer rule (core → services). Теперь core вызывает через
    canonical DI provider. Resolve через ``resolve_module`` — late import,
    чтобы избежать module-level circular dependency.
    """
    if "security_facade" in _overrides:
        return _overrides["security_facade"]
    module = resolve_module("security.facade")
    return module.get_security_facade()


def set_security_facade_provider(facade: Any) -> None:
    """Override для ``security_facade`` provider (test/mock injection)."""
    _overrides["security_facade"] = facade
