from passlib.context import CryptContext
from pydantic import SecretStr
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_utils.types import PasswordType

from app.db.models import BaseModel


__all__ = ("User",)

# Контекст для хэширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(BaseModel):
    """
    ORM-класс таблицы учета пользователей.

    Атрибуты:
        username (str): Имя пользователя (уникальное, до 50 символов).
        email (str): Электронная почта пользователя (уникальная, до 255 символов).
        password (str): Хэшированный пароль пользователя.
        is_active (bool): Флаг активности пользователя.
        is_superuser (bool): Флаг суперпользователя.
    """

    __table_args__ = {"comment": "Пользователи"}

    # Поля таблицы
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    password: Mapped[str] = mapped_column(
        PasswordType(
            schemes=[
                "pbkdf2_sha512",
            ]
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    def verify_password(self, password: SecretStr) -> bool:
        """
        Проверяет, соответствует ли переданный пароль хэшированному паролю пользователя.

        Аргументы:
            password (SecretStr): Пароль для проверки.

        Возвращает:
            bool: True, если пароль верный, иначе False.
        """
        if isinstance(password, SecretStr):
            password = password.get_secret_value()
        return pwd_context.verify(password, self.password)
