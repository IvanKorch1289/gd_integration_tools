from sqlalchemy import UUID, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from gd_advanced_tools.models.base import BaseModel

__all__ = ("File",)


class File(BaseModel):
    """ORM-класс таблицы учета файлов."""

    __tableargs__ = {"сomment": "Данные файлов"}

    name: Mapped[str] = mapped_column(String, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUID, nullable=False, server_default=func.gen_random_uuid(), index=True
    )
    linked_object_id: Mapped[int] = mapped_column(Integer, nullable=True)
