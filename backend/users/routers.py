from fastapi import APIRouter, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.users.filters import UserFilter, UserLogin
from backend.users.schemas import UserSchemaIn
from backend.users.service import UserService


__all__ = ("router", "auth_router")


router = APIRouter()


@cbv(router)
class UserCBV:
    """CBV-класс для работы со справочником видов запросов."""

    service = UserService()

    @router.get(
        "/all/", status_code=status.HTTP_200_OK, summary="Получить всех пользователей"
    )
    async def get_users(self):
        return await self.service.all()

    @router.get(
        "/id/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить пользователя по ID",
    )
    async def get_user(self, user_id: int):
        return await self.service.get(key="id", value=user_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить пользователя по полю",
    )
    async def get_by_filter(self, user_filter: UserFilter = FilterDepends(UserFilter)):
        return await self.service.get_by_params(filter=user_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить пользователя"
    )
    async def add_user(self, request_schema: UserSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
    )
    async def update_user(self, request_schema: UserSchemaIn, user_id: int):
        return await self.service.update(
            key="id", value=user_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Удалить вид запроса по ID",
    )
    async def delete_user(self, user_id: int):
        return await self.service.delete(key="id", value=user_id)


auth_router = APIRouter()


@cbv(auth_router)
class AuthCBV:
    """CBV-класс для аутентификации пользователя."""

    service = UserService()

    @auth_router.post(
        "/login",
        status_code=status.HTTP_200_OK,
        summary="Аутентифицироваться в приложении",
    )
    async def login(self, credentials: UserLogin = FilterDepends(UserLogin)):
        return await self.service.login(filter=credentials)
