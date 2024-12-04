from sqlalchemy.orm import Mapped, mapped_column

from gd_advanced_tools.models.base import BaseModel


__all__ = ("User",)


class User(BaseModel):
    """ORM-класс таблицы учета пользователей."""

    __table_args__ = {"comment": "Пользователи"}

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)

    def check_password(self, password: str) -> bool:
        return self.hashed_password == password

    def change_password(self, password: str) -> None:
        self.hashed_password = password
