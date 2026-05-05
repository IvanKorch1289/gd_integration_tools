"""ORM-модель пользователя.

Пароли хешируются через ``argon2-cffi`` (A2 / ADR-003). Старая схема
``passlib + PasswordType(pbkdf2_sha512)`` удалена:
* ``passlib`` — упрощённо поддерживается и помечен deprecated.
* ``PasswordType`` из ``sqlalchemy_utils`` вводил неявную конверсию
  при чтении/записи и скрывал алгоритм.

Argon2id выбран как победитель Password Hashing Competition 2015 и
рекомендуемая схема OWASP. Параметры берутся из пресета low-latency.
"""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from pydantic import SecretStr
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.infrastructure.database.models.base import BaseModel

__all__ = ("User",)


@lru_cache(maxsize=1)
def _get_password_hasher() -> PasswordHasher:
    """Lazy singleton ``argon2.PasswordHasher`` (Wave 6.1).

    OWASP-рекомендованные параметры для интерактивных сервисов:
    ``time_cost=3, memory_cost=64 MiB, parallelism=4, hash_len=32``.
    Для более чувствительных кейсов (корпоративный SSO) — tune через
    settings.
    """
    return PasswordHasher(
        time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32, salt_len=16
    )


class User(BaseModel):
    """ORM-класс таблицы учёта пользователей."""

    __table_args__ = {"comment": "Пользователи"}

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    # Храним готовый argon2-hash как строку PHC-format (начинается с '$argon2id$').
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    def set_password(self, password: str | SecretStr) -> None:
        """Хеширует пароль и сохраняет в поле ``password``."""
        raw = (
            password.get_secret_value() if isinstance(password, SecretStr) else password
        )
        self.password = _get_password_hasher().hash(raw)

    def verify_password(self, password: SecretStr | str) -> bool:
        """Проверяет пароль; ``True``, если совпадает с хранимым хешем."""
        raw = (
            password.get_secret_value() if isinstance(password, SecretStr) else password
        )
        hasher = _get_password_hasher()
        try:
            hasher.verify(self.password, raw)
        except (
            argon2_exceptions.VerifyMismatchError,
            argon2_exceptions.InvalidHashError,
        ):
            return False
        # Опционально: если параметры argon2 устарели (политика компании
        # усилена), пере-хешируем и запишем обратно — caller должен закоммитить.
        if hasher.check_needs_rehash(self.password):
            self.password = hasher.hash(raw)
        return True
