"""Bootstrap администратора — явная привилегированная операция (P0).

Вызывается только через ``manage.py bootstrap-admin``. Пароль принимается
исключительно через stdin (``--password-stdin``) или переменную окружения
(``--from-env``) — никогда не через argv/config.

Политики:
* известные дефолтные пароли запрещены во ВСЕХ профилях;
* в prod-профиле дополнительно требуется длина >= 12;
* пользователь существует → пароль обновляется (reset) с warning;
* не существует → создаётся суперпользователь.
"""

from __future__ import annotations

import asyncio
import os
import sys

from src.backend.core.logging import get_logger

__all__ = ("KNOWN_DEFAULT_PASSWORDS", "bootstrap_admin_user", "read_password")

_logger = get_logger("auth.bootstrap_admin")

#: Пароли, запрещённые во всех профилях (публично известные дефолты).
KNOWN_DEFAULT_PASSWORDS = frozenset(
    {"admin", "admin-default-password-change-me", "password", "changeme"}
)

_MIN_PROD_PASSWORD_LENGTH = 12


def read_password(*, password_stdin: bool, from_env: str | None) -> str:
    """Прочитать пароль из stdin или переменной окружения.

    Args:
        password_stdin: читать пароль из stdin (до EOF).
        from_env: имя переменной окружения с паролем.

    Returns:
        Пароль как строка.

    Raises:
        ValueError: если источник не задан или пароль пуст.

    """
    if password_stdin:
        password = sys.stdin.read().strip()
    elif from_env:
        password = os.environ.get(from_env, "").strip()
    else:
        raise ValueError("Укажите источник пароля: --password-stdin или --from-env VAR")
    if not password:
        raise ValueError("Пароль пуст")
    return password


def _validate_password_policy(password: str, *, profile: str) -> None:
    """Отклонить известные дефолты везде и слабые пароли в prod."""
    if password in KNOWN_DEFAULT_PASSWORDS:
        raise ValueError(
            "Отклонено: пароль входит в список известных дефолтных "
            "(разрешено только через интерактивную смену при первом входе)"
        )
    if profile == "prod" and len(password) < _MIN_PROD_PASSWORD_LENGTH:
        raise ValueError(
            f"Отклонено: в prod-профиле пароль должен быть >= "
            f"{_MIN_PROD_PASSWORD_LENGTH} символов"
        )


def bootstrap_admin_user(
    *, username: str, password: str, email: str | None = None
) -> str:
    """Создать или сбросить пароль суперпользователя (идемпотентно).

    Args:
        username: логин администратора.
        password: новый пароль (проходит policy-проверку).
        email: опциональный email (по умолчанию ``{username}@example.com``).

    Returns:
        ``"created"`` или ``"password_updated"``.

    Raises:
        ValueError: нарушение password-policy или пустой username.

    """
    if not username:
        raise ValueError("username обязателен")

    from src.backend.core.config.profile import get_active_profile

    profile = get_active_profile().value
    _validate_password_policy(password, profile=profile)

    async def _run() -> str:
        import sqlalchemy as sa

        from extensions.core_entities.users.domain.models import User
        from src.backend.infrastructure.database.session_manager import (  # noqa: F401 — re-export
            main_session_manager,
        )

        async with main_session_manager.create_session() as session:
            user = (
                await session.execute(sa.select(User).where(User.username == username))
            ).scalar_one_or_none()
            if user is not None:
                user.set_password(password)
                user.is_active = True
                outcome = "password_updated"
                _logger.warning(
                    "bootstrap_admin: пароль существующего пользователя %r обновлён",
                    username,
                )
            else:
                user = User(username=username)
                user.set_password(password)  # type: ignore[arg-type]
                user.is_active = True
                user.is_superuser = True
                user.tenant_id = "default"
                if email:
                    user.email = email
                from datetime import UTC, datetime

                now = datetime.now(UTC)
                if getattr(user, "created_at", None) is None:
                    user.created_at = now
                user.updated_at = now
                session.add(user)
                outcome = "created"
            await session.commit()
            return outcome

    return asyncio.run(_run())
