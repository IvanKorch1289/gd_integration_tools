from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('SKBSchemaIn', )


class SKBSchemaIn(PublicModel):

    Id: str
    OrderId: str
    Number: str
    Priority: int = 80
    RequestType: str
