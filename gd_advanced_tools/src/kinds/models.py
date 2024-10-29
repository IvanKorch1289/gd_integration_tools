from sqlalchemy.orm import Mapped, mapped_column

from gd_advanced_tools.src.core.database import Base


class OrderKind(Base):
    """ORM-класс таблицы учета видов запросов."""

    __tableargs__ = {'сomment': 'Виды запросов в СКБ-Техно'}

    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str]
    skb_uuid: Mapped[str] = mapped_column(unique=True, index=True)
