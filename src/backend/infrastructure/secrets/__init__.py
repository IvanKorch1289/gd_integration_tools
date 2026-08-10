"""Secret-broker подсистема (V15 S1+S3 DoD).

API:

* :class:`SecretBroker` (Protocol) — public-контракт.
* :class:`SecretBrokerImpl` — реализация поверх pluggable backend'ов.
* :class:`VaultBackend` — HashiCorp Vault через ``hvac.Client`` (KV v2).
* :class:`EnvBackend` — fallback на переменные окружения (для dev).
* :class:`RotationScheduler` — push-уведомления подписчикам при ротации.

Capability-runtime-gate (опционально): если ``capability_check`` задан —
``get_secret(name)`` валидирует scope ``secrets.read.<name>`` через gate.
"""

from src.backend.infrastructure.secrets.broker import (
    SecretBroker,
    SecretBrokerImpl,
    SecretValue,
    SubscriberCallback,
)
from src.backend.infrastructure.secrets.env_backend import EnvBackend  # noqa: F401 — re-export
from src.backend.infrastructure.secrets.rotation import RotationScheduler  # noqa: F401 — re-export
from src.backend.infrastructure.secrets.vault_backend import VaultBackend  # noqa: F401 — re-export

__all__ = (
    "EnvBackend",
    "RotationScheduler",
    "SecretBroker",
    "SecretBrokerImpl",
    "SecretValue",
    "SubscriberCallback",
    "VaultBackend",
)
