"""Tests for src.backend.core.config.transport."""

from __future__ import annotations

from src.backend.core.config.transport import TransportSettings


class TestTransportSettings:
    def test_defaults(self) -> None:
        s = TransportSettings()
        assert s.sftp_known_hosts_path is None

    def test_custom(self) -> None:
        s = TransportSettings(sftp_known_hosts_path="/etc/hosts")
        assert s.sftp_known_hosts_path == "/etc/hosts"
