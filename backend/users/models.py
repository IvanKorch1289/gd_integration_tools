from passlib.context import CryptContext
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.base.models import BaseModel


__all__ = ("User",)


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(BaseModel):
    """ORM-класс таблицы учета пользователей."""

    __table_args__ = {"comment": "Пользователи"}

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    def verify_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.password)

    def get_password_hash(password):
        return pwd_context.hash(password)

    def change_password(self, password: str) -> None:
        self.hashed_password = pwd_context.hash(password)
