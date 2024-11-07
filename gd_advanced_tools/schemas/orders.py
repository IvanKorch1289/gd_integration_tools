from datetime import datetime

from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('OrderSchemaIn', 'OrderSchemaOut', )


class OrderSchemaIn(PublicModel):

    pledge_gd_id: int
    pledge_cadastral_number: str
    order_kind_id: str


class OrderSchemaOut(OrderSchemaIn):

    id: int
    created_at: datetime
    updated_at: datetime
