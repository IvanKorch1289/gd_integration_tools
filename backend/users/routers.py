from typing import List

from fastapi import APIRouter, Header, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.errors import handle_routes_errors
from backend.core.limiter import route_limiter
from backend.users.filters import UserFilter
from backend.users.schemas import (
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)
from backend.users.service import UserService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class UserCBV:
    """CBV-класс для работы со справочником видов запросов."""

    service = UserService()

    @router.get(
        "/all/",
        status_code=status.HTTP_200_OK,
        summary="Получить всех пользователей",
        response_model=List[UserSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def get_users(self, request: Request, x_api_key: str = Header(...)):
        return await self.service.all()

    @router.get(
        "/id/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить пользователя по ID",
        response_model=UserSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def get_user(self, user_id: int, x_api_key: str = Header(...)):
        return await self.service.get(key="id", value=user_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить пользователей по полю",
        response_model=List[UserSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def get_by_filter(
        self,
        user_filter: UserFilter = FilterDepends(UserFilter),
        x_api_key: str = Header(...),
    ):
        return await self.service.get_by_params(filter=user_filter)

    @router.post(
        "/create/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить пользователя",
        response_model=UserSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def add_user(
        self,
        request_schema: UserSchemaIn,
        request: Request,
        x_api_key: str = Header(...),
    ):
        return await self.service.add(data=request_schema.model_dump())

    @router.post(
        "/create_many/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить несколько пользователей",
        response_model=List[UserSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def add_many_users(
        self,
        request_schema: List[UserSchemaIn],
        request: Request,
        x_api_key: str = Header(...),
    ):
        data_list = [schema.model_dump() for schema in request_schema]
        return await self.service.add_many(data_list=data_list)

    @router.put(
        "/update/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
        response_model=UserSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def update_user(
        self,
        request_schema: UserSchemaIn,
        user_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ):
        return await self.service.update(
            key="id", value=user_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить вид запроса по ID",
    )
    @route_limiter
    @handle_routes_errors
    async def delete_user(
        self, user_id: int, request: Request, x_api_key: str = Header(...)
    ):
        return await self.service.delete(key="id", value=user_id)

    @router.get(
        "/all_versions/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить версии объекта пользователя по ID",
        response_model=List[UserVersionSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def get_all_user_versions(
        self, user_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить все версии объекта пользователя по его ID.

        :param user_id: ID пользователя.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех версий объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_all_object_versions(object_id=user_id)

    @router.get(
        "/latest_version/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить последнюю версию объекта пользователя по ID",
        response_model=UserVersionSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def get_user_latest_version(
        self, user_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить последнюю версию объекта пользователя по его ID.

        :param user_id: ID пользователя.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Последняя версия объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_latest_object_version(object_id=user_id)

    @router.post(
        "/restore_to_version/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Восстановить объект пользователя до указанной версии",
        response_model=UserSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def restore_user_to_version(
        self,
        user_id: int,
        transaction_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Восстановить объект пользователя до указанной версии.

        :param user_id: ID пользователя.
        :param transaction_id: ID транзакции (версии) для восстановления.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Восстановленный объект.
        :raises HTTPException: Если произошла ошибка при восстановлении.
        """
        return await self.service.restore_object_to_version(
            object_id=user_id, transaction_id=transaction_id
        )

    @router.get(
        "/changes/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить изменения объекта пользователя по ID",
    )
    @route_limiter
    @handle_routes_errors
    async def get_user_changes(
        self, user_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить список изменений объекта пользователя по его ID.

        :param file_id: ID дпользователя.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список изменений объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_object_changes(object_id=user_id)
