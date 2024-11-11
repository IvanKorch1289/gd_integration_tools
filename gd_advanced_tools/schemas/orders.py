from datetime import datetime
from uuid import UUID

from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('OrderSchemaIn', 'OrderSchemaOut', )


class OrderSchemaIn(PublicModel):

    pledge_gd_id: int = None
    pledge_cadastral_number: str = None
    order_kind_id: str = None


class OrderSchemaOut(OrderSchemaIn):

    id: int
    order_kind_id: int
    is_active: bool
    is_send_to_gd: bool
    errors: str | None
    object_uuid: UUID
    created_at: datetime
    updated_at: datetime
