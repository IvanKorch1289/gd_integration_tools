import httpx
from fastapi import APIRouter

from gd_advanced_tools.core.settings import settings


router = APIRouter()


@router.get('/get-kinds', summary='Получить экземпляры справочника видов запросов из СКБ Техно')
async def get_skb_kinds():
    params = {'api-key': settings.api_settings.api_key}
    endpoint = settings.api_settings.skb_url + 'Kinds'
    try:
        request = httpx.get(endpoint, params=params)
    # for el in request.json().get('Data'):
    #     order_kind = {}
    #     order_kind['name'] = el['Name']
    #     order_kind['skb_uuid'] = el['Id']
        return request.json().get('Data')
    except Exception as ex:
        return {'error': str(ex)}
