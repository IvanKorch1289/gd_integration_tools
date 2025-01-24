from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv
from pydantic import BaseModel

from backend.core.errors import handle_routes_errors
from backend.core.limiter import route_limiter


SchemaIn = TypeVar("SchemaIn", bound=BaseModel)
SchemaOut = TypeVar("SchemaOut", bound=BaseModel)
VersionSchemaOut = TypeVar("VersionSchemaOut", bound=BaseModel)


def create_cbv_class(
    router: APIRouter,
    schema_in: Type[SchemaIn],
    schema_out: Type[SchemaOut],
    version_schema_out: Type[VersionSchemaOut],
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
            response_model=List[schema_out],
        )
        @route_limiter
        @handle_routes_errors
        async def get_all(self, request: Request, x_api_key: str = Header(...)):
            result = await self.service.get()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Объекты не найдены",
                )
            return result

        @router.get(
            "/id/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить объект по ID",
            response_model=schema_out,
        )
        @route_limiter
        @handle_routes_errors
        async def get_by_id(self, object_id: int, x_api_key: str = Header(...)):
            result = await self.service.get(key="id", value=object_id)
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Объект не найден",
                )
            return result

        @router.post(
            "/create/",
            status_code=status.HTTP_201_CREATED,
            summary="Добавить объект",
            response_model=schema_out,
        )
        @route_limiter
        @handle_routes_errors
        async def add_object(
            self,
            request_schema: schema_in,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.add(data=request_schema.model_dump())

        @router.post(
            "/create_many/",
            status_code=status.HTTP_201_CREATED,
            summary="Добавить несколько объектов",
            response_model=List[schema_out],
        )
        @route_limiter
        @handle_routes_errors
        async def add_many_objects(
            self,
            request_schema: List[schema_in],
            request: Request,
            x_api_key: str = Header(...),
        ):
            data_list = [schema.model_dump() for schema in request_schema]
            return await self.service.add_many(data_list=data_list)

        @router.put(
            "/update/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Изменить объект по ID",
            response_model=schema_out,
        )
        @route_limiter
        @handle_routes_errors
        async def update_object(
            self,
            request_schema: schema_in,
            object_id: int,
            request: Request,
            x_api_key: str = Header(...),
        ):
            return await self.service.update(
                key="id", value=object_id, data=request_schema.model_dump()
            )

        @router.delete(
            "/delete/{object_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Удалить объект по ID",
        )
        @route_limiter
        @handle_routes_errors
        async def delete_object(
            self, object_id: int, request: Request, x_api_key: str = Header(...)
        ):
            return await self.service.delete(key="id", value=object_id)

        @router.get(
            "/all_versions/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить версии объекта по ID",
            response_model=List[version_schema_out],
        )
        @route_limiter
        @handle_routes_errors
        async def get_all_object_versions(
            self, object_id: int, request: Request, x_api_key: str = Header(...)
        ):
            return await self.service.get_all_object_versions(object_id=object_id)

        @router.get(
            "/latest_version/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Получить последнюю версию объекта по ID",
            response_model=version_schema_out,
        )
        @route_limiter
        @handle_routes_errors
        async def get_latest_object_version(
            self, object_id: int, request: Request, x_api_key: str = Header(...)
        ):
            return await self.service.get_latest_object_version(object_id=object_id)

        @router.post(
            "/restore_to_version/{object_id}",
            status_code=status.HTTP_200_OK,
            summary="Восстановить объект до указанной версии",
            response_model=schema_out,
        )
        @route_limiter
        @handle_routes_errors
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
        @route_limiter
        @handle_routes_errors
        async def get_object_changes(
            self, object_id: int, request: Request, x_api_key: str = Header(...)
        ):
            return await self.service.get_object_changes(object_id=object_id)

    return GenericCBV


# Универсальный метод для добавления роутов в CBV-класс
def add_route_to_cbv(
    cbv_class: Type,
    router: APIRouter,
    path: str,
    http_method: str,
    endpoint: Callable,
    response_model: Optional[Type] = None,
    status_code: int = status.HTTP_200_OK,
    dependencies: Optional[List[Depends]] = None,
    summary: Optional[str] = None,
    **kwargs: Dict[str, Any]
):
    """
    Добавляет новый роут в CBV-класс.

    :param cbv_class: Класс CBV, в который добавляется роут.
    :param router: Роутер FastAPI.
    :param path: Путь роута (например, "/get-by-filter").
    :param http_method: HTTP-метод (например, "get", "post").
    :param endpoint: Функция-обработчик роута.
    :param response_model: Модель ответа (опционально).
    :param status_code: HTTP-статус код (по умолчанию 200).
    :param dependencies: Список зависимостей (опционально).
    :param summary: Краткое описание роута (опционально).
    :param kwargs: Дополнительные параметры для передачи в декоратор роута.
    """
    # Создаем декоратор для роута
    route_decorator = getattr(router, http_method.lower())

    # Добавляем декораторы для обработки ошибок и лимитера
    @route_decorator(
        path,
        response_model=response_model,
        status_code=status_code,
        dependencies=dependencies,
        summary=summary,
        **kwargs
    )
    @route_limiter
    @handle_routes_errors
    async def route_handler(self: cbv_class, *args, **kwargs):
        # Вызываем переданный endpoint с аргументами
        return await endpoint(self, *args, **kwargs)

    # Добавляем метод в CBV-класс
    setattr(cbv_class, endpoint.__name__, route_handler)
