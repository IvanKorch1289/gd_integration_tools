from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.limiter import route_limiter
from backend.orderkinds.filters import OrderKindFilter
from backend.orderkinds.schemas import OrderKindSchemaIn, OrderKindSchemaOut
from backend.orderkinds.service import OrderKindService, get_order_kind_service


__all__ = ("router",)

router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """
    CBV-класс для работы со справочником видов запросов.

    Предоставляет методы для получения, добавления, обновления и удаления видов запросов.
    """

    # Внедряем зависимость через конструктор
    def __init__(self, service: OrderKindService = Depends(get_order_kind_service)):
        self.service = service

    @router.get(
        "/all/",
        status_code=status.HTTP_200_OK,
        summary="Получить все виды запросов",
        response_model=List[OrderKindSchemaOut],
    )
    @route_limiter
    async def get_kinds(
        self, request: Request, x_api_key: str = Header(...)
    ) -> List[OrderKindSchemaOut]:
        """
        Получить все виды запросов из базы данных.

        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех видов запросов.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.all()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.get(
        "/id/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по ID",
        response_model=OrderKindSchemaOut,
    )
    async def get_kind(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ) -> OrderKindSchemaOut:
        """
        Получить вид запроса по его ID.

        :param kind_id: ID вида запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Вид запроса с указанным ID.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.get(key="id", value=kind_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по фильтру",
        response_model=List[OrderKindSchemaOut],
    )
    async def get_by_filter(
        self,
        request: Request,
        order_kind_filter: OrderKindFilter = FilterDepends(OrderKindFilter),
        x_api_key: str = Header(...),
    ) -> List[OrderKindSchemaOut]:
        """
        Получить виды запросов, соответствующие указанному фильтру.

        :param order_kind_filter: Фильтр для поиска видов запросов.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список видов запросов, соответствующих фильтру.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.get_by_params(filter=order_kind_filter)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.post(
        "/create/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить вид запроса",
        response_model=OrderKindSchemaIn,
    )
    @route_limiter
    async def add_kind(
        self,
        request_schema: OrderKindSchemaIn,
        request: Request,
        x_api_key: str = Header(...),
    ) -> OrderKindSchemaIn:
        """
        Добавить новый вид запроса в базу данных.

        :param request_schema: Данные для создания вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Созданный вид запроса.
        :raises HTTPException: Если произошла ошибка при создании записи.
        """
        try:
            return await self.service.add(data=request_schema.model_dump())
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.post(
        "/create_many/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить несколько видов запроса",
        response_model=List[OrderKindSchemaOut],
    )
    async def add_many_kinds(
        self,
        request_schema: List[OrderKindSchemaIn],
        request: Request,
        x_api_key: str = Header(...),
    ) -> List[OrderKindSchemaOut]:
        """
        Добавить несколько видов запросов в базу данных.

        :param request_schema: Список данных для создания видов запросов.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список созданных видов запросов.
        :raises HTTPException: Если произошла ошибка при создании записей.
        """
        try:
            data_list = [schema.model_dump() for schema in request_schema]
            return await self.service.add_many(data_list=data_list)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.put(
        "/update/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
        response_model=OrderKindSchemaOut,
    )
    @route_limiter
    async def update_kind(
        self,
        request_schema: OrderKindSchemaIn,
        kind_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ) -> OrderKindSchemaOut:
        """
        Обновить вид запроса по его ID.

        :param request_schema: Данные для обновления вида запроса.
        :param kind_id: ID вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Обновленный вид запроса.
        :raises HTTPException: Если произошла ошибка при обновлении записи.
        """
        try:
            return await self.service.update(
                key="id", value=kind_id, data=request_schema.model_dump()
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.delete(
        "/delete/{kind_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить вид запроса по ID",
    )
    @route_limiter
    async def delete_kind(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ) -> None:
        """
        Удалить вид запроса по его ID.

        :param kind_id: ID вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :raises HTTPException: Если произошла ошибка при удалении записи.
        """
        try:
            await self.service.delete(key="id", value=kind_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.get(
        "/all_versions/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить версии объекта вида запроса по ID",
    )
    @route_limiter
    async def get_all_kind_versions(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить все версии объекта вида запроса по его ID.

        :param kind_id: ID вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех версий объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.get_all_object_versions(object_id=kind_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.get(
        "/latest_version/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить последнюю версию объекта вида запроса по ID",
    )
    @route_limiter
    async def get_kind_latest_version(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить последнюю версию объекта вида запроса по его ID.

        :param kind_id: ID вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Последняя версия объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.get_latest_object_version(object_id=kind_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.post(
        "/restore_to_version/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Восстановить объект вида запроса до указанной версии",
    )
    @route_limiter
    async def restore_kind_to_version(
        self,
        kind_id: int,
        transaction_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Восстановить объект вида запроса до указанной версии.

        :param kind_id: ID вида запроса.
        :param transaction_id: ID транзакции (версии) для восстановления.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Восстановленный объект.
        :raises HTTPException: Если произошла ошибка при восстановлении.
        """
        try:
            return await self.service.restore_object_to_version(
                object_id=kind_id, transaction_id=transaction_id
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )

    @router.get(
        "/changes/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить изменения объекта вида запроса по ID",
    )
    @route_limiter
    async def get_kind_changes(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить список изменений объекта вида запроса по его ID.

        :param kind_id: ID вида запроса.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список изменений объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        try:
            return await self.service.get_object_changes(object_id=kind_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            )
