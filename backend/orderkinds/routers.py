from typing import Any, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.errors import handle_routes_errors
from backend.core.limiter import route_limiter
from backend.core.routers_factory import add_route_to_cbv, create_cbv_class
from backend.orderkinds.filters import OrderKindFilter
from backend.orderkinds.schemas import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from backend.orderkinds.service import get_order_kind_service


__all__ = ("router",)

router = APIRouter()

# Создаем CBV-класс
OrderKindCBV = create_cbv_class(
    router=router,
    schema_in=OrderKindSchemaIn,
    schema_out=OrderKindSchemaOut,
    version_schema_out=OrderKindVersionSchemaOut,
    service=get_order_kind_service(),
    filter_class=OrderKindFilter,
)


# Функция-обработчик для роута с фильтрацией
async def get_by_filter(
    self: Any,  # Используем Any вместо OrderKindCBV
    request: Request,
    order_filter: OrderKindFilter = Depends(FilterDepends(OrderKindFilter)),
    x_api_key: str = Header(...),
):
    """
    Получить запросы по фильтру.

    :param request: Объект запроса FastAPI.
    :param order_filter: Фильтр для поиска запросов.
    :param x_api_key: API-ключ для аутентификации.
    :return: Список запросов, соответствующих фильтру.
    """
    return await self.service.get(filter=order_filter)


# Добавляем роут в CBV-класс
add_route_to_cbv(
    cbv_class=OrderKindCBV,
    router=router,
    path="/get-by-filter",
    http_method="get",
    endpoint=get_by_filter,  # Передаем саму функцию, а не строку
    response_model=None,
    summary="Получить объекты по фильтру",
)

# @cbv(router)
# class OrderKindCBV:
#     """
#     CBV-класс для работы со справочником видов запросов.

#     Предоставляет методы для получения, добавления, обновления и удаления видов запросов.
#     """

#     service = get_order_kind_service()

#     @router.get(
#         "/all/",
#         status_code=status.HTTP_200_OK,
#         summary="Получить все виды запросов",
#         response_model=List[OrderKindSchemaOut],
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_kinds(
#         self, request: Request, x_api_key: str = Header(...)
#     ) -> List[OrderKindSchemaOut]:
#         """
#         Получить все виды запросов из базы данных.

#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Список всех видов запросов.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         return await self.service.get()

#     @router.get(
#         "/id/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Получить вид запроса по ID",
#         response_model=OrderKindSchemaOut,
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_kind(
#         self, kind_id: int, request: Request, x_api_key: str = Header(...)
#     ) -> OrderKindSchemaOut:
#         """
#         Получить вид запроса по его ID.

#         :param kind_id: ID вида запроса.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Вид запроса с указанным ID.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         result = await self.service.get(key="id", value=kind_id)

#         if not result:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Not found",
#             )

#         return result

#     @router.get(
#         "/get-by-filter",
#         status_code=status.HTTP_200_OK,
#         summary="Получить вид запроса по фильтру",
#         response_model=List[OrderKindSchemaOut],
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_by_filter(
#         self,
#         request: Request,
#         order_kind_filter: OrderKindFilter = FilterDepends(OrderKindFilter),
#         x_api_key: str = Header(...),
#     ) -> List[OrderKindSchemaOut]:
#         """
#         Получить виды запросов, соответствующие указанному фильтру.

#         :param order_kind_filter: Фильтр для поиска видов запросов.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Список видов запросов, соответствующих фильтру.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         return await self.service.get(filter=order_kind_filter)

#     @router.post(
#         "/create/",
#         status_code=status.HTTP_201_CREATED,
#         summary="Добавить вид запроса",
#         response_model=OrderKindSchemaIn,
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def add_kind(
#         self,
#         request_schema: OrderKindSchemaIn,
#         request: Request,
#         x_api_key: str = Header(...),
#     ) -> OrderKindSchemaIn:
#         """
#         Добавить новый вид запроса в базу данных.

#         :param request_schema: Данные для создания вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Созданный вид запроса.
#         :raises HTTPException: Если произошла ошибка при создании записи.
#         """
#         return await self.service.add(data=request_schema.model_dump())

#     @router.post(
#         "/create_many/",
#         status_code=status.HTTP_201_CREATED,
#         summary="Добавить несколько видов запроса",
#         response_model=List[OrderKindSchemaOut],
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def add_many_kinds(
#         self,
#         request_schema: List[OrderKindSchemaIn],
#         request: Request,
#         x_api_key: str = Header(...),
#     ) -> List[OrderKindSchemaOut]:
#         """
#         Добавить несколько видов запросов в базу данных.

#         :param request_schema: Список данных для создания видов запросов.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Список созданных видов запросов.
#         :raises HTTPException: Если произошла ошибка при создании записей.
#         """
#         data_list = [schema.model_dump() for schema in request_schema]
#         return await self.service.add_many(data_list=data_list)

#     @router.put(
#         "/update/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Изменить вид запроса по ID",
#         response_model=OrderKindSchemaOut,
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def update_kind(
#         self,
#         request_schema: OrderKindSchemaIn,
#         kind_id: int,
#         request: Request,
#         x_api_key: str = Header(...),
#     ) -> OrderKindSchemaOut:
#         """
#         Обновить вид запроса по его ID.

#         :param request_schema: Данные для обновления вида запроса.
#         :param kind_id: ID вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Обновленный вид запроса.
#         :raises HTTPException: Если произошла ошибка при обновлении записи.
#         """
#         return await self.service.update(
#             key="id", value=kind_id, data=request_schema.model_dump()
#         )

#     @router.delete(
#         "/delete/{kind_id}",
#         status_code=status.HTTP_204_NO_CONTENT,
#         summary="Удалить вид запроса по ID",
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def delete_kind(
#         self, kind_id: int, request: Request, x_api_key: str = Header(...)
#     ) -> None:
#         """
#         Удалить вид запроса по его ID.

#         :param kind_id: ID вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :raises HTTPException: Если произошла ошибка при удалении записи.
#         """
#         await self.service.delete(key="id", value=kind_id)

#     @router.get(
#         "/all_versions/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Получить версии объекта вида запроса по ID",
#         response_model=List[OrderKindVersionSchemaOut],
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_all_kind_versions(
#         self, kind_id: int, request: Request, x_api_key: str = Header(...)
#     ):
#         """
#         Получить все версии объекта вида запроса по его ID.

#         :param kind_id: ID вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Список всех версий объекта.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         return await self.service.get_all_object_versions(object_id=kind_id)

#     @router.get(
#         "/latest_version/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Получить последнюю версию объекта вида запроса по ID",
#         response_model=OrderKindVersionSchemaOut,
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_kind_latest_version(
#         self, kind_id: int, request: Request, x_api_key: str = Header(...)
#     ):
#         """
#         Получить последнюю версию объекта вида запроса по его ID.

#         :param kind_id: ID вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Последняя версия объекта.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         return await self.service.get_latest_object_version(object_id=kind_id)

#     @router.post(
#         "/restore_to_version/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Восстановить объект вида запроса до указанной версии",
#         response_model=OrderKindSchemaOut,
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def restore_kind_to_version(
#         self,
#         kind_id: int,
#         transaction_id: int,
#         request: Request,
#         x_api_key: str = Header(...),
#     ):
#         """
#         Восстановить объект вида запроса до указанной версии.

#         :param kind_id: ID вида запроса.
#         :param transaction_id: ID транзакции (версии) для восстановления.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Восстановленный объект.
#         :raises HTTPException: Если произошла ошибка при восстановлении.
#         """
#         return await self.service.restore_object_to_version(
#             object_id=kind_id, transaction_id=transaction_id
#         )

#     @router.get(
#         "/changes/{kind_id}",
#         status_code=status.HTTP_200_OK,
#         summary="Получить изменения объекта вида запроса по ID",
#     )
#     @route_limiter
#     @handle_routes_errors
#     async def get_kind_changes(
#         self, kind_id: int, request: Request, x_api_key: str = Header(...)
#     ):
#         """
#         Получить список изменений объекта вида запроса по его ID.

#         :param kind_id: ID вида запроса.
#         :param request: Объект запроса FastAPI.
#         :param x_api_key: API-ключ для аутентификации.
#         :return: Список изменений объекта.
#         :raises HTTPException: Если произошла ошибка при получении данных.
#         """
#         return await self.service.get_object_changes(object_id=kind_id)
