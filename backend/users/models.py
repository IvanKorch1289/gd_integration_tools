from passlib.context import CryptContext
from pydantic import SecretStr
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_utils.types import PasswordType

from backend.base.models import BaseModel


__all__ = ("User",)


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(BaseModel):
    """ORM-класс таблицы учета пользователей."""

    __table_args__ = {"comment": "Пользователи"}

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
        if isinstance(password, SecretStr):
            password = password.get_secret_value()
        return pwd_context.verify(password, self.password)
