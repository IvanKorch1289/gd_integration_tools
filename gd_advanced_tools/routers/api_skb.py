from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

from gd_advanced_tools.dependencies.api_skb import skb_kinds_service
from gd_advanced_tools.services.api_skb import APISKBKindService


router = APIRouter()

@cbv(router)
class SKBCBV:
    """CBV-класс для создания запросов в СКБ-Техно."""

    @router.get('/get-kinds', summary='Получить экземпляры справочника видов запросов из СКБ Техно')
    async def get_skb_kinds(
        self,
        service: Annotated[APISKBKindService, Depends(skb_kinds_service)]
    ):
        return await service.get_request_kinds()
