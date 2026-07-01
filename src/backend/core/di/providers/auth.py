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

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_INFRA = "src." + "backend.infrastructure"

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


def get_jwt_backend_provider() -> Any:
    """Возвращает singleton :class:`JwtBackend` (joserfc-based).

    Wave [s2/k1-2-jwt-jwks]: заменяет прямое использование ``python-jose``
    в :func:`_verify_jwt` (auth_selector). Backend строится из
    :class:`SecureSettings` (для HS-алгоритмов) либо :class:`JwksSettings`
    (для RS/ES — pull JWKS из IdP). Если в overrides — берётся override.
    """
    if "jwt_backend" in _overrides:
        return _overrides["jwt_backend"]
    from src.backend.core.auth.jwt_backend import JwtBackend
    from src.backend.core.config.security import secure_settings

    secret = secure_settings.secret_key
    secret_value = (
        secret.get_secret_value()
        if hasattr(secret, "get_secret_value")
        else str(secret)
    )
    jwks = _build_jwks_cache_or_none()
    algorithms = [secure_settings.algorithm]
    if jwks is not None and "RS256" not in algorithms:
        algorithms = list(set(algorithms + ["RS256"]))
    blacklist = _build_jwt_blacklist_or_none()
    backend = JwtBackend(
        algorithms=algorithms,
        secret=secret_value if any(a.startswith("HS") for a in algorithms) else None,
        jwks=jwks,
        leeway=getattr(secure_settings, "jwt_leeway", 60),
        blacklist=blacklist,
    )
    _overrides["jwt_backend"] = backend
    return backend


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
    return JwksCache(url, ttl=ttl)


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
    except Exception:  # pragma: no cover — Redis может быть недоступен в test/dev_light
        return None


__all__ = (
    "get_api_key_manager_provider",
    "get_jwks_cache_provider",
    "get_jwt_backend_provider",
    "set_api_key_manager_provider",
    "set_jwks_cache_provider",
    "set_jwt_backend_provider",
)
