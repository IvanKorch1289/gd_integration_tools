from fastapi import APIRouter
from fastapi_utils.cbv import cbv

from gd_advanced_tools.services import APISKBService


__all__ = ('router', )


router = APIRouter()


@cbv(router)
class SKBCBV:
    """CBV-класс для создания запросов в СКБ-Техно."""
    service = APISKBService()

    @router.get('/get-kinds', summary='Получить справочник видов из СКБ Техно')
    async def get_skb_kinds(self):
        return await self.service.get_request_kinds()

    @router.post('/create-request', summary='Создать запрос на получение данных по залогу в СКБ Техно')
    async def add_request(self):
        return await self.service.add_request()
