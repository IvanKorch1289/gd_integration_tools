"""CertBackend registry (S171 M22, D258).

Pattern (D258, Ponytail): extensions могут регистрировать
свои CertBackend implementations (HSM, cloud-KMS, custom) без
изменения core.

Inspired by D102 (facade) + D187 (facade single-import):
- register(backend_id, backend_class) — добавить backend
- get(backend_id) — получить класс (создаёт экземпляр)
- unregister(backend_id) — удалить
- list_ids() — список всех зарегистрированных
- contains(backend_id) — проверка

5 built-in backends (vault/postgres/mongo/memory/consul)
регистрируются автоматически при первом импорте модуля.
"""
# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger("security.cert_store.registry")

__all__ = ("CertBackendRegistry", "get_cert_backend_registry")


class CertBackendRegistry:
    """Registry CertBackend implementations (D258).

    Использование (extension plugin):
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            get_cert_backend_registry,
        )
        from src.backend.infrastructure.security.cert_store.backend_base import (
            CertBackend,
        )

        class MyCustomBackend(CertBackend):
            async def get(self, service_id): ...
            async def set(self, service_id, pem): ...
            # ... и т.д.

        get_cert_backend_registry().register("my_hsm", MyCustomBackend)
    """

    def __init__(self) -> None:
        self._backends: dict[str, type[CertBackend]] = {}

    def register(self, backend_id: str, backend_class: type[CertBackend]) -> None:
        """Регистрация backend класса по id (D258)."""
        if not backend_id:
            raise ValueError("backend_id обязательно")
        if backend_id in self._backends:
            logger.warning(
                "cert.registry.override id=%s old=%s new=%s",
                backend_id,
                self._backends[backend_id].__name__,
                backend_class.__name__,
            )
        self._backends[backend_id] = backend_class
        logger.info(
            "cert.registry.register id=%s class=%s",
            backend_id, backend_class.__name__,
        )

    def unregister(self, backend_id: str) -> None:
        """Удаление backend по id."""
        if backend_id in self._backends:
            del self._backends[backend_id]
            logger.info("cert.registry.unregister id=%s", backend_id)

    def get(self, backend_id: str) -> type[CertBackend]:
        """Получить CertBackend класс по id (raises KeyError)."""
        if backend_id not in self._backends:
            raise KeyError(
                f"CertBackend {backend_id!r} не зарегистрирован. "
                f"Доступные: {sorted(self._backends.keys())}"
            )
        return self._backends[backend_id]

    def contains(self, backend_id: str) -> bool:
        """Проверить наличие backend по id."""
        return backend_id in self._backends

    def list_ids(self) -> list[str]:
        """Список всех зарегистрированных id (sorted)."""
        return sorted(self._backends.keys())

    def instantiate(self, backend_id: str, **kwargs: Any) -> "CertBackend":
        """Создать экземпляр backend по id (D258 convenience method)."""
        cls = self.get(backend_id)
        return cls(**kwargs)


# Global singleton — singleton pattern (D102 facade single-import)
_global_registry: CertBackendRegistry | None = None


def get_cert_backend_registry() -> CertBackendRegistry:
    """Получить глобальный CertBackend registry (D258)."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CertBackendRegistry()
        _register_builtin_backends(_global_registry)
    return _global_registry


def _register_builtin_backends(reg: CertBackendRegistry) -> None:
    """Регистрация 5 built-in backends (lazy import, D258)."""
    from src.backend.infrastructure.security.cert_store.backend_vault import (
        VaultCertBackend,
    )
    from src.backend.infrastructure.security.cert_store.backend_postgres import (
        PostgresCertBackend,
    )
    from src.backend.infrastructure.security.cert_store.backend_mongo import (
        MongoCertBackend,
    )
    from src.backend.infrastructure.security.cert_store.backend_memory import (
        MemoryCertBackend,
    )
    from src.backend.infrastructure.security.cert_store.backend_consul import (
        ConsulCertBackend,
    )
    reg.register("vault", VaultCertBackend)
    reg.register("postgres", PostgresCertBackend)
    reg.register("mongo", MongoCertBackend)
    reg.register("memory", MemoryCertBackend)
    reg.register("consul", ConsulCertBackend)
