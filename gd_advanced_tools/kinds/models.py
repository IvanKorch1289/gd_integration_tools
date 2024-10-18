from sqlalchemy.orm import Mapped, mapped_column

from gd_advanced_tools.core.database import Base


class OrderKind(Base):
    """ORM-класс таблицы учета видов запросов."""

    name: Mapped[str]
    description: Mapped[str]
    skb_uuid: Mapped[str] = mapped_column(unique=True, index=True)
