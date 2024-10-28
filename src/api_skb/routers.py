import httpx
from fastapi import APIRouter

from src.config.settings import api_settings


router = APIRouter()


@router.get('/get-kinds', summary='Получить экземпляры справочника видов запросов из СКБ Техно')
async def get_skb_kinds():
    params = {'api-key': api_settings.API_KEY}
    endpoint = api_settings.SKB_URL + 'Kinds'
    try:
        request = httpx.get(endpoint, params=params)
        for el in request.json().get('Data'):
            order_kind = {}
            order_kind['name'] = el['Name']
            order_kind['skb_uuid'] = el['Id']
    except Exception as ex:
        return {'error': str(ex)}
