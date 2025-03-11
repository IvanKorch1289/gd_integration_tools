from typing import List, Optional, Type, TypeVar

from fastapi import APIRouter, Header, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv
from pydantic import BaseModel

from app.utils.decorators.limiting import route_limiting
from app.utils.enums.ordering import OrderingTypeChoices


SchemaIn = TypeVar("SchemaIn", bound=BaseModel)
SchemaOut = TypeVar("SchemaOut", bound=BaseModel)
VersionSchemaOut = TypeVar("VersionSchemaOut", bound=BaseModel)


__all__ = ("create_router_class",)


def create_router_class(
    router: APIRouter,
    schema_in: Type[SchemaIn],
    service,
    filter_class: Optional[Type] = None,
):

    @cbv(router)
    class GenericCBV:
        def __init__(self):
            self.service = service

        @router.get(
            "/all/",
            status_code=status.HTTP_200_OK,
            summary="Получить все объекты",
        )
        @route_limiting
        async def get_all(
            self, request: Request, x_api_key: str = Header(...)
        ):
            return await self.service.get()

        @router.get(
            "/id/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить объект по ID",
        )
        @route_limiting
        async def get_by_id(
            self,
            request: Request,
            object_id: int,
            x_api_key: str = Header(...),
        ):
            return await self.service.get(key="id", value=object_id)

        @router.get(
            "/first-or-last/",
            status_code=status.HTTP_200_OK,
            summary="Получить первые или последние объекты",
        )
        @route_limiting
        async def get_first_or_last_objests_with_limit(
            self,
            request: Request,
            limit: int = 1,
            by: str = "id",
            order: OrderingTypeChoices = OrderingTypeChoices.ascending,
            x_api_key: str = Header(...),
        ):
            return await self.service.get_first_or_last_with_limit(
                limit=limit,
                by=by,
                order=order.value,
            )

        @router.post(
            "/create/",
            status_code=status.HTTP_201_CREATED,
            summary="Добавить объект",
        )
        @route_limiting
        async def add_object(
            self,
            request_schema: schema_in,  # type: ignore
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.add(data=request_schema.model_dump())  # type: ignore

        @router.post(
            "/create_many/",
            status_code=status.HTTP_201_CREATED,
            summary="Добавить несколько объектов",
        )
        @route_limiting
        async def add_many_objects(
            self,
            request_schemas: List[schema_in],  # type: ignore
            request: Request,
            x_api_key: str = Header(...),
        ):
            data_list = [schema.model_dump() for schema in request_schemas]  # type: ignore
            return await self.service.add_many(data_list=data_list)

        @router.put(
            "/update/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Изменить объект по ID",
        )
        @route_limiting
        async def update_object(
            self,
            request_schema: schema_in,  # type: ignore
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.update(
                key="id", value=object_id, data=request_schema.model_dump()  # type: ignore
            )

        @router.delete(
            "/delete/{object_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Удалить объект по ID",
        )
        @route_limiting
        async def delete_object(
            self,
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.delete(key="id", value=object_id)

        @router.get(
            "/all_versions/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить версии объекта по ID",
        )
        @route_limiting
        async def get_all_object_versions(
            self,
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.get_all_object_versions(
                object_id=object_id
            )

        @router.get(
            "/latest_version/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить последнюю версию объекта по ID",
        )
        @route_limiting
        async def get_latest_object_version(
            self,
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.get_latest_object_version(
                object_id=object_id
            )

        @router.post(
            "/restore_to_version/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Восстановить объект до указанной версии",
        )
        @route_limiting
        async def restore_object_to_version(
            self,
            object_id: int,
            transaction_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.restore_object_to_version(
                object_id=object_id, transaction_id=transaction_id
            )

        @router.get(
            "/changes/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить изменения объекта по ID",
        )
        @route_limiting
        async def get_object_changes(
            self,
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.get_object_changes(object_id=object_id)

        if filter_class:

            @router.get(
                "/filter/",
                status_code=status.HTTP_200_OK,
                summary="Получить объекты по фильтру",
            )
            @route_limiting
            async def get_by_filter(
                self,
                request: Request,
                filter: filter_class = FilterDepends(filter_class),  # type: ignore
                x_api_key: str = Header(...),
            ):
                """
                Получить объекты по фильтру.

                :param request: Объект запроса FastAPI.
                :param filter: Фильтр для поиска объектов.
                :param x_api_key: API-ключ для аутентификации.
                :return: Список объектов, соответствующих фильтру.
                """
                return await self.service.get(filter=filter)

    return GenericCBV
