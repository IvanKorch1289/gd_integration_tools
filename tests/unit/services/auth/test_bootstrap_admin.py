"""Focused tests for bootstrap_admin (P0: privileged credentials).

Контракт (P0 внешнего плана, 2026-09-14):
* известные дефолтные пароли запрещены во всех профилях;
* в prod-профиле длина < 12 отклоняется;
* результат: created | password_updated.
"""

from __future__ import annotations

import pytest

from src.backend.services.auth.bootstrap_admin import (
    KNOWN_DEFAULT_PASSWORDS,
    _validate_password_policy,
    read_password,
)


class TestPasswordPolicy:
    def test_known_default_rejected_all_profiles(self) -> None:
        """Известный дефолт отклоняется и в dev, и в prod."""
        for profile in ("dev_light", "prod"):
            with pytest.raises(ValueError, match="известных дефолтных"):
                _validate_password_policy(
                    "admin-default-password-change-me", profile=profile
                )

    def test_short_password_rejected_in_prod(self) -> None:
        """prod: короткий пароль отклоняется."""
        with pytest.raises(ValueError, match="prod-профиле"):
            _validate_password_policy("short", profile="prod")

    def test_strong_password_accepted_in_prod(self) -> None:
        """prod: сильный пароль проходит policy."""
        _validate_password_policy("S3cureBootstrap#2026", profile="prod")

    def test_short_password_ok_in_dev(self) -> None:
        """dev_light: короткий пароль разрешён (не prod)."""
        _validate_password_policy("short", profile="dev_light")


class TestReadPassword:
    def test_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--password-stdin: пароль из stdin (strip)."""
        import io
        import sys

        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"secret\n")))
        assert read_password(password_stdin=True, from_env=None) == "secret"

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--from-env: пароль из переменной окружения."""
        monkeypatch.setenv("BOOTSTRAP_PW", "from-env-secret")
        assert read_password(password_stdin=False, from_env="BOOTSTRAP_PW") == (
            "from-env-secret"
        )

    def test_empty_source_raises(self) -> None:
        """Ни stdin, ни env → ValueError."""
        with pytest.raises(ValueError, match="--password-stdin или --from-env"):
            read_password(password_stdin=False, from_env=None)

    def test_empty_password_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пустое значение env → ValueError."""
        monkeypatch.setenv("EMPTY_PW", "")
        with pytest.raises(ValueError, match="Пароль пуст"):
            read_password(password_stdin=False, from_env="EMPTY_PW")


def test_known_defaults_registry() -> None:
    """Реестр известных дефолтов содержит задокументированные значения."""
    assert "admin-default-password-change-me" in KNOWN_DEFAULT_PASSWORDS


class TestUserModelFromRegistry:
    """ADR-0457: ORM-модель пользователя берётся из core-реестра расширений."""

    def test_user_model_available_from_registry(self) -> None:
        """Расширение отдаёт ту же модель, что использует bootstrap."""
        from extensions.core_entities.users.domain.models import User as ext_user
        from src.backend.core.extension_registry import get_extension_resource

        assert get_extension_resource("users", "model", "user") is ext_user

    def test_bootstrap_resolves_user_model_via_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Модель резолвится лениво, по ключу ``users/model/user``."""
        import src.backend.services.auth.bootstrap_admin as bootstrap_admin

        calls: list[tuple[str, str, str]] = []

        def _fake_get_resource(domain: str, kind: str, name: str) -> object:
            calls.append((domain, kind, name))
            raise RuntimeError("stop-after-resolution")

        monkeypatch.setattr(
            bootstrap_admin, "get_extension_resource", _fake_get_resource
        )
        with pytest.raises(RuntimeError, match="stop-after-resolution"):
            bootstrap_admin.bootstrap_admin_user(
                username="admin", password="Str0ngBootstrap#2026"
            )
        assert calls == [("users", "model", "user")]
