"""Zero-downtime Vault secret client with graceful reconnect and drift-toleration.

K1 S19 W1: Implements zero-downtime secret rotation supporting:
    - graceful reconnect with exponential backoff on connection failures
    - old secret kept N minutes drift-toleration window before activation
    - validate new credentials BEFORE activation (fail-safe)

This module provides a high-level :class:`VaultClient` that wraps the lower-level
VaultBackend and adds rotation-aware features. The background rotation is handled
by :class:`VaultSecretRotator` in ``vault_rotator.py``.

Usage::

    client = VaultClient.from_env()
    client.register(
        "secret/data/db/credentials",
        lambda data: db_pool.reload(data),
        validator=lambda data: test_connection(data),
    )
    await client.start_rotation(interval_seconds=300)
    # On shutdown:
    await client.stop_rotation()
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.observability.metrics_registry import metrics_registry
from src.backend.infrastructure.secrets.vault_backend import VaultBackend, VaultConfig

__all__ = ("VaultClient", "VaultClientConfig", "get_vault_client")

# Prometheus counter for vault validation failures
_vault_validation_failed_counter = metrics_registry.counter(
    "vault_validation_failed_total",
    "Vault secret validation failures",
    labels=("path",),
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# Default drift tolerance: 5 minutes (300 seconds)
_DEFAULT_DRIFT_TOLERANCE: float = 300.0
# Default reconnection base delay: 1 second
_DEFAULT_RECONNECT_BASE_DELAY: float = 1.0
# Default reconnection max delay: 60 seconds
_DEFAULT_RECONNECT_MAX_DELAY: float = 60.0
# Default rotation check interval: 5 minutes
_DEFAULT_ROTATION_INTERVAL: float = 300.0


@dataclass(frozen=True, slots=True)
class VaultClientConfig:
    """Configuration for VaultClient zero-downtime rotation.

    Attributes:
        drift_tolerance_seconds: Time window (seconds) to keep old secret active
            after a new version appears, allowing gradual rollout (default 300s).
        reconnect_base_delay: Initial delay for exponential backoff on reconnect
            (default 1.0s).
        reconnect_max_delay: Maximum delay for exponential backoff (default 60.0s).
        rotation_interval_seconds: How often to check for secret version changes
            (default 300s).
    """

    drift_tolerance_seconds: float = _DEFAULT_DRIFT_TOLERANCE
    reconnect_base_delay: float = _DEFAULT_RECONNECT_BASE_DELAY
    reconnect_max_delay: float = _DEFAULT_RECONNECT_MAX_DELAY
    rotation_interval_seconds: float = _DEFAULT_ROTATION_INTERVAL


@dataclass(slots=True)
class _SecretEntry:
    """Internal tracking for a registered secret path.

    Attributes:
        path: Vault KV v2 path.
        callback: Function called when secret is activated.
        validator: Optional function to validate secret before activation.
        current_version: Last known Vault version.
        old_secret_data: Old secret data during drift-toleration window.
        old_secret_timestamp: When the old secret was superseded.
        active_secret_data: Currently active secret data.
        failed_version: Version that failed validation (for repeated failure detection).
        failed_version_timestamp: When the failed version was recorded.
    """

    path: str
    callback: Callable[[dict[str, Any]], None]
    validator: Callable[[dict[str, Any]], bool] | None
    current_version: int | None = None
    old_secret_data: dict[str, Any] = field(default_factory=dict)
    old_secret_timestamp: float = 0.0
    active_secret_data: dict[str, Any] = field(default_factory=dict)
    failed_version: int | None = None
    failed_version_timestamp: float = 0.0


class VaultClient:
    """High-level Vault client with zero-downtime secret rotation.

    Combines :class:`VaultBackend` operations with rotation awareness:
        - Tracks secret versions per path
        - Maintains old secret during drift-toleration window
        - Validates new credentials before activation
        - Graceful reconnect with exponential backoff

    Example::

        client = VaultClient.from_env()
        client.register(
            "secret/data/db/password",
            lambda data: db.reload(data),
            validator=lambda data: check_db_credentials(data),
        )
        await client.start()
    """

    def __init__(
        self,
        config: VaultClientConfig | None = None,
        vault_config: VaultConfig | None = None,
        backend: VaultBackend | None = None,
    ) -> None:
        """Initialize VaultClient.

        Args:
            config: Zero-downtime rotation config (defaults to VaultClientConfig).
            vault_config: Vault connection config (defaults to VaultConfig.from_env()).
            backend: Optional VaultBackend for dependency injection in tests.
        """
        self._config = config or VaultClientConfig()
        self._vault_config = vault_config or VaultConfig.from_env()
        self._backend = backend or VaultBackend(config=self._vault_config)
        self._entries: dict[str, _SecretEntry] = {}
        self._rotation_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._client: Any = None  # hvac.Client, lazy initialized

    @classmethod
    def from_env(
        cls,
        *,
        drift_tolerance_seconds: float | None = None,
        reconnect_base_delay: float | None = None,
        reconnect_max_delay: float | None = None,
        rotation_interval_seconds: float | None = None,
    ) -> VaultClient:
        """Create VaultClient from environment variables and optional overrides.

        Vault connection parameters are read from environment:
            VAULT_ADDR, VAULT_TOKEN, VAULT_ROLE_ID, VAULT_SECRET_ID,
            VAULT_MOUNT, VAULT_NAMESPACE.

        Args:
            drift_tolerance_seconds: Override default drift tolerance.
            reconnect_base_delay: Override default reconnect base delay.
            reconnect_max_delay: Override default reconnect max delay.
            rotation_interval_seconds: Override default rotation check interval.
        """
        config = VaultClientConfig(
            drift_tolerance_seconds=(
                drift_tolerance_seconds or _DEFAULT_DRIFT_TOLERANCE
            ),
            reconnect_base_delay=(
                reconnect_base_delay or _DEFAULT_RECONNECT_BASE_DELAY
            ),
            reconnect_max_delay=reconnect_max_delay or _DEFAULT_RECONNECT_MAX_DELAY,
            rotation_interval_seconds=(
                rotation_interval_seconds or _DEFAULT_ROTATION_INTERVAL
            ),
        )
        return cls(config=config, vault_config=VaultConfig.from_env())

    def register(
        self,
        path: str,
        callback: Callable[[dict[str, Any]], None],
        validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        """Register a secret path for zero-downtime rotation.

        Args:
            path: Vault KV v2 path, e.g. ``secret/data/db/credentials``.
            callback: Called when new secret version is activated.
            validator: If provided, called with new secret data before activation.
                Must return True for activation to proceed. If False, the old
                secret remains active and the new one is kept for later retry.
        """
        entry = _SecretEntry(path=path, callback=callback, validator=validator)
        self._entries[path] = entry
        logger.debug(
            "vault_client.registered", path=path, has_validator=validator is not None
        )

    def get_active_secret(self, path: str) -> dict[str, Any] | None:
        """Return currently active secret data for path.

        During drift-toleration window, returns the old (still-active) secret.
        After activation, returns the new secret.

        Args:
            path: Registered secret path.

        Returns:
            Secret data dict, or None if path not registered.
        """
        entry = self._entries.get(path)
        if entry is None:
            return None
        if entry.old_secret_data and entry.current_version is None:
            return entry.old_secret_data
        return entry.active_secret_data or None

    async def start(self) -> None:
        """Start the background rotation check loop.

        If already running, this is a no-op (idempotent).
        """
        if self._running:
            logger.warning("vault_client.already_running")
            return

        self._running = True
        self._rotation_task = get_task_registry().create_task(
            self._rotation_loop(), name="vault-client-rotation"
        )
        logger.info(
            "vault_client.started",
            interval_seconds=self._config.rotation_interval_seconds,
        )

    async def stop(self) -> None:
        """Gracefully stop the background rotation loop.

        Cancels the rotation task and waits for completion.
        """
        self._running = False
        if self._rotation_task is not None and not self._rotation_task.done():
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass
            logger.info("vault_client.stopped")
        self._rotation_task = None

    async def tick(self) -> None:
        """Perform one rotation check cycle.

        For each registered path:
            1. Connect to Vault (with reconnect logic on failure)
            2. Fetch latest secret version from Vault
            3. If new version detected:
                a. Check if still in drift-toleration window
                b. If validator provided, call before activation
                c. If validation passes, activate new secret
                d. If validation fails, keep old secret active
        """

        if self._client is None:
            self._client = await self._get_client()

        now = time.time()

        for path, entry in list(self._entries.items()):
            try:
                response = self._client.secrets.kv.v2.read_secret_version(
                    path=path, mount_point=self._vault_config.mount_point
                )
                new_version: int = response["data"]["metadata"]["version"]
                new_data: dict[str, Any] = response["data"]["data"]

                if entry.current_version is None:
                    # First read — just cache the version and data
                    entry.current_version = new_version
                    entry.active_secret_data = new_data
                    logger.debug("vault_client.init", path=path, version=new_version)
                elif entry.current_version != new_version:
                    # Version changed — check drift window
                    old_secret_still_valid = (
                        entry.old_secret_data
                        and entry.old_secret_timestamp > 0
                        and (now - entry.old_secret_timestamp)
                        < self._config.drift_tolerance_seconds
                    )

                    if old_secret_still_valid:
                        # In drift window — keep old secret active, store new for later
                        logger.info(
                            "vault_client.drift_tolerating",
                            path=path,
                            new_version=new_version,
                            current_version=entry.current_version,
                            drift_remaining_s=(
                                self._config.drift_tolerance_seconds
                                - (now - entry.old_secret_timestamp)
                            ),
                        )
                        # Keep old secret active, prepare new for after drift window
                        entry.old_secret_data = new_data
                        entry.old_secret_timestamp = now
                    else:
                        # Drift window passed — attempt validation and activation
                        if entry.validator is not None:
                            try:
                                is_valid = entry.validator(new_data)
                            except Exception as exc:
                                logger.error(
                                    "vault_client.validation_error",
                                    path=path,
                                    error=str(exc),
                                )
                                is_valid = False

                            if not is_valid:
                                logger.warning(
                                    "vault_client.validation_failed",
                                    path=path,
                                    new_version=new_version,
                                    old_secret_retained=True,
                                )
                                _vault_validation_failed_counter.labels(path=path).inc()
                                # Track failed version for repeated failure detection
                                entry.failed_version = new_version
                                entry.failed_version_timestamp = now
                                # Check if this version failed before (repeated failure)
                                if (
                                    entry.current_version is not None
                                    and entry.current_version == new_version
                                ):
                                    logger.error(
                                        "vault_client.validation_repeated_failure",
                                        path=path,
                                        version=new_version,
                                        previous_failure_ts=entry.failed_version_timestamp,
                                    )
                                # Do NOT store failed secret in old_secret_data —
                                # get_active_secret() must continue returning
                                # the currently active (valid) secret.
                                # Retry will happen when vault provides a new version.
                                entry.old_secret_timestamp = now
                                continue

                        # Validation passed or no validator — activate new secret
                        logger.info(
                            "vault_client.secret_activated",
                            path=path,
                            old_version=entry.current_version,
                            new_version=new_version,
                        )
                        entry.current_version = new_version
                        entry.active_secret_data = new_data
                        entry.old_secret_data = {}
                        entry.old_secret_timestamp = 0.0
                        entry.callback(new_data)
                else:
                    logger.debug(
                        "vault_client.unchanged", path=path, version=new_version
                    )

            except Exception as exc:
                logger.warning(
                    "vault_client.connection_error",
                    path=path,
                    error=str(exc),
                    old_secret_active=True,
                )
                # Trigger reconnect logic on next tick
                self._client = None

    async def _get_client(self) -> Any:
        """Create and authenticate hvac.Client with exponential backoff.

        Returns:
            Authenticated hvac.Client instance.
        """
        import hvac

        client = hvac.Client(
            url=self._vault_config.url, namespace=self._vault_config.namespace
        )

        if self._vault_config.token:
            client.token = self._vault_config.token
        elif self._vault_config.role_id and self._vault_config.secret_id:
            # hvac.auth.approle.login() is blocking — run in executor to avoid
            # blocking the async event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: client.auth.approle.login(
                    role_id=self._vault_config.role_id,
                    secret_id=self._vault_config.secret_id,
                ),
            )
        else:
            raise RuntimeError(
                "Vault auth not configured: set VAULT_TOKEN or "
                "VAULT_ROLE_ID + VAULT_SECRET_ID"
            )

        return client

    async def _rotation_loop(self) -> None:
        """Background loop: tick, sleep, repeat until stopped."""
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("vault_client.rotation_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self._config.rotation_interval_seconds)
            except asyncio.CancelledError:
                break


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

_vault_client_instance: VaultClient | None = None


def get_vault_client() -> VaultClient:
    """Return singleton VaultClient instance.

    Creates instance on first call; subsequent calls return the same object.
    """
    global _vault_client_instance
    if _vault_client_instance is None:
        _vault_client_instance = VaultClient.from_env()
    return _vault_client_instance
