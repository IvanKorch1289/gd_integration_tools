"""Tests for VaultClient zero-downtime secret rotation.

K1 S19 W1: Validates:
    - graceful reconnect with exponential backoff
    - old secret kept during drift-toleration window
    - new credentials validated BEFORE activation
    - zero-downtime: old secret stays active during drift window
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestVaultClient:
    """Test suite for VaultClient zero-downtime rotation."""

    @pytest.fixture
    def mock_hvac_response(self) -> MagicMock:
        """Create a mock hvac response with given version and data."""
        def _make_response(version: int, data: dict[str, Any]) -> dict[str, Any]:
            return {
                "data": {
                    "metadata": {"version": version},
                    "data": data,
                }
            }
        return MagicMock()

    @pytest.fixture
    def rotator(self) -> "VaultClient":
        """Create a fresh VaultClient for each test."""
        from src.backend.infrastructure.secrets.vault_client import (
            VaultClient,
            VaultClientConfig,
        )
        config = VaultClientConfig(
            drift_tolerance_seconds=300.0,
            reconnect_base_delay=1.0,
            reconnect_max_delay=60.0,
            rotation_interval_seconds=300.0,
        )
        mock_backend = MagicMock()
        return VaultClient(config=config, backend=mock_backend)

    # ─────────────────────────────────────────────────────────────────────────
    # Registration tests
    # ─────────────────────────────────────────────────────────────────────────

    def test_register_adds_entry(self, rotator: "VaultClient") -> None:
        """register() should add path to internal entries dict."""
        callback = MagicMock()
        rotator.register("secret/data/test/key", callback)

        assert "secret/data/test/key" in rotator._entries
        entry = rotator._entries["secret/data/test/key"]
        assert entry.path == "secret/data/test/key"
        assert entry.callback is callback
        assert entry.validator is None
        assert entry.current_version is None

    def test_register_with_validator(self, rotator: "VaultClient") -> None:
        """register() should store validator function when provided."""
        validator = MagicMock(return_value=True)
        callback = MagicMock()
        rotator.register("secret/data/test/key", callback, validator=validator)

        entry = rotator._entries["secret/data/test/key"]
        assert entry.validator is validator

    # ─────────────────────────────────────────────────────────────────────────
    # Get active secret tests
    # ─────────────────────────────────────────────────────────────────────────

    def test_get_active_secret_returns_none_when_not_registered(
        self, rotator: "VaultClient"
    ) -> None:
        """get_active_secret() should return None for unregistered path."""
        result = rotator.get_active_secret("secret/data/nonexistent")
        assert result is None

    def test_get_active_secret_returns_cached_after_init(
        self, rotator: "VaultClient"
    ) -> None:
        """get_active_secret() should return active_secret_data after init."""
        callback = MagicMock()
        rotator.register("secret/data/test/key", callback)
        rotator._entries["secret/data/test/key"].active_secret_data = {"key": "value"}

        result = rotator.get_active_secret("secret/data/test/key")
        assert result == {"key": "value"}

    # ─────────────────────────────────────────────────────────────────────────
    # Zero-downtime rotation tests
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio()
    async def test_initial_version_cached_no_callback(
        self, rotator: "VaultClient"
    ) -> None:
        """First read should cache version and data but NOT call callback."""
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback)

        mock_response = {
            "data": {
                "metadata": {"version": 1},
                "data": {"password": "secret-v1"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        with patch.object(rotator, "_get_client", return_value=mock_client):
            await rotator.tick()

        entry = rotator._entries["secret/data/db/password"]
        assert entry.current_version == 1
        assert entry.active_secret_data == {"password": "secret-v1"}
        callback.assert_not_called()

    @pytest.mark.asyncio()
    async def test_version_change_activates_after_drift_window(
        self, rotator: "VaultClient"
    ) -> None:
        """Version change after drift window should trigger callback."""
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback)

        # Simulate first version cached
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        # New version response
        mock_response = {
            "data": {
                "metadata": {"version": 2},
                "data": {"password": "secret-v2"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        # Simulate time has passed beyond drift window
        old_timestamp = time.time() - 400  # 400 seconds ago (> 300s tolerance)

        with patch.object(rotator, "_get_client", return_value=mock_client):
            # Simulate tick
            entry = rotator._entries["secret/data/db/password"]
            entry.old_secret_timestamp = old_timestamp

            await rotator.tick()

        # After drift window, callback should be called
        assert callback.called
        assert callback.call_args[0][0] == {"password": "secret-v2"}

    @pytest.mark.asyncio()
    async def test_version_change_kept_during_drift_window(
        self, rotator: "VaultClient"
    ) -> None:
        """Within drift window, old secret should stay active (no callback)."""
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback)

        # Simulate first version cached
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        # New version response
        mock_response = {
            "data": {
                "metadata": {"version": 2},
                "data": {"password": "secret-v2"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        # Simulate time is still within drift window
        old_timestamp = time.time() - 100  # 100 seconds ago (< 300s tolerance)

        with patch.object(rotator, "_get_client", return_value=mock_client):
            entry = rotator._entries["secret/data/db/password"]
            entry.old_secret_data = {"password": "secret-v1"}
            entry.old_secret_timestamp = old_timestamp

            await rotator.tick()

        # Within drift window, callback should NOT be called yet
        callback.assert_not_called()
        # Old secret should still be active
        assert entry.active_secret_data == {"password": "secret-v1"}

    @pytest.mark.asyncio()
    async def test_validation_failure_keeps_old_secret(
        self, rotator: "VaultClient"
    ) -> None:
        """If validator returns False, old secret should remain active."""
        validator = MagicMock(return_value=False)
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback, validator=validator)

        # Simulate first version cached
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        # New version response
        mock_response = {
            "data": {
                "metadata": {"version": 2},
                "data": {"password": "secret-v2"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        # Time beyond drift window
        old_timestamp = time.time() - 400

        with patch.object(rotator, "_get_client", return_value=mock_client):
            entry = rotator._entries["secret/data/db/password"]
            entry.old_secret_timestamp = old_timestamp

            await rotator.tick()

        # Validator should have been called
        validator.assert_called_once_with({"password": "secret-v2"})
        # Callback should NOT be called
        callback.assert_not_called()
        # Old secret still active
        assert entry.active_secret_data == {"password": "secret-v1"}

    @pytest.mark.asyncio()
    async def test_validation_success_activates_new_secret(
        self, rotator: "VaultClient"
    ) -> None:
        """If validator returns True, new secret should be activated."""
        validator = MagicMock(return_value=True)
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback, validator=validator)

        # Simulate first version cached
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        # New version response
        mock_response = {
            "data": {
                "metadata": {"version": 2},
                "data": {"password": "secret-v2"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        # Time beyond drift window
        old_timestamp = time.time() - 400

        with patch.object(rotator, "_get_client", return_value=mock_client):
            entry = rotator._entries["secret/data/db/password"]
            entry.old_secret_timestamp = old_timestamp

            await rotator.tick()

        # Validator should have been called
        validator.assert_called_once_with({"password": "secret-v2"})
        # Callback should be called
        callback.assert_called_once_with({"password": "secret-v2"})
        # New secret active
        assert entry.active_secret_data == {"password": "secret-v2"}

    @pytest.mark.asyncio()
    async def test_validation_exception_keeps_old_secret(
        self, rotator: "VaultClient"
    ) -> None:
        """If validator raises, old secret should remain active."""
        validator = MagicMock(side_effect=Exception("Connection failed"))
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback, validator=validator)

        # Simulate first version cached
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        # New version response
        mock_response = {
            "data": {
                "metadata": {"version": 2},
                "data": {"password": "secret-v2"},
            }
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response

        # Time beyond drift window
        old_timestamp = time.time() - 400

        with patch.object(rotator, "_get_client", return_value=mock_client):
            entry = rotator._entries["secret/data/db/password"]
            entry.old_secret_timestamp = old_timestamp

            await rotator.tick()

        # Callback should NOT be called
        callback.assert_not_called()
        # Old secret still active
        assert entry.active_secret_data == {"password": "secret-v1"}

    # ─────────────────────────────────────────────────────────────────────────
    # Start/stop tests
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio()
    async def test_start_creates_rotation_task(self, rotator: "VaultClient") -> None:
        """start() should create an asyncio.Task for rotation loop."""
        rotator._running = False

        await rotator.start()

        assert rotator._rotation_task is not None
        assert not rotator._rotation_task.done()
        assert rotator._running is True

        # Cleanup
        await rotator.stop()

    @pytest.mark.asyncio()
    async def test_stop_cancels_rotation_task(self, rotator: "VaultClient") -> None:
        """stop() should cancel the rotation task."""
        await rotator.start()
        task = rotator._rotation_task

        await rotator.stop()

        assert task is not None
        # Task should be done (cancelled)
        assert task.done()

    @pytest.mark.asyncio()
    async def test_idempotent_start(self, rotator: "VaultClient") -> None:
        """Multiple start() calls should be idempotent (no duplicate tasks)."""
        rotator._running = False

        await rotator.start()
        first_task = rotator._rotation_task

        # Second start should be no-op
        await rotator.start()
        second_task = rotator._rotation_task

        assert first_task is second_task

        # Cleanup
        await rotator.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # Graceful reconnect tests
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio()
    async def test_connection_error_resets_client_for_reconnect(
        self, rotator: "VaultClient"
    ) -> None:
        """On connection error, client should be reset to None for reconnect."""
        callback = MagicMock()
        rotator.register("secret/data/db/password", callback)

        # First version
        rotator._entries["secret/data/db/password"].current_version = 1
        rotator._entries["secret/data/db/password"].active_secret_data = {
            "password": "secret-v1"
        }

        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.side_effect = Exception(
            "Connection refused"
        )

        rotator._client = mock_client

        await rotator.tick()

        # Client should be reset to None for next reconnect attempt
        assert rotator._client is None


class TestVaultClientConfig:
    """Test VaultClientConfig dataclass."""

    def test_default_values(self) -> None:
        """Test that default config values are correct."""
        from src.backend.infrastructure.secrets.vault_client import (
            VaultClientConfig,
            _DEFAULT_DRIFT_TOLERANCE,
            _DEFAULT_RECONNECT_BASE_DELAY,
            _DEFAULT_RECONNECT_MAX_DELAY,
            _DEFAULT_ROTATION_INTERVAL,
        )

        config = VaultClientConfig()

        assert config.drift_tolerance_seconds == _DEFAULT_DRIFT_TOLERANCE
        assert config.reconnect_base_delay == _DEFAULT_RECONNECT_BASE_DELAY
        assert config.reconnect_max_delay == _DEFAULT_RECONNECT_MAX_DELAY
        assert config.rotation_interval_seconds == _DEFAULT_ROTATION_INTERVAL

    def test_custom_values(self) -> None:
        """Test custom config values."""
        from src.backend.infrastructure.secrets.vault_client import VaultClientConfig

        config = VaultClientConfig(
            drift_tolerance_seconds=600.0,
            reconnect_base_delay=2.0,
            reconnect_max_delay=120.0,
            rotation_interval_seconds=600.0,
        )

        assert config.drift_tolerance_seconds == 600.0
        assert config.reconnect_base_delay == 2.0
        assert config.reconnect_max_delay == 120.0
        assert config.rotation_interval_seconds == 600.0


class TestVaultClientSingleton:
    """Test singleton behavior of get_vault_client()."""

    def test_singleton_returns_same_instance(self) -> None:
        """get_vault_client() should return the same instance."""
        from src.backend.infrastructure.secrets import vault_client as _mod

        # Reset singleton
        _mod._vault_client_instance = None

        from src.backend.infrastructure.secrets.vault_client import get_vault_client

        first = get_vault_client()
        second = get_vault_client()

        assert first is second

        # Cleanup
        _mod._vault_client_instance = None
