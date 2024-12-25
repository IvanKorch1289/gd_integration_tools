from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv
from settings import settings

from backend.core.auth import security
from backend.users.filters import UserFilter, UserLogin
from backend.users.schemas import UserSchemaIn
from backend.users.service import UserService


__all__ = ("router", "auth_router", "tech_router")


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
        "/create/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить пользователя",
        dependencies=[Depends(security.access_token_required)],
    )
    async def add_user(self, request_schema: UserSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
        dependencies=[Depends(security.access_token_required)],
    )
    async def update_user(self, request_schema: UserSchemaIn, user_id: int):
        return await self.service.update(
            key="id", value=user_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{user_id}",
        status_code=status.HTTP_200_OK,
        summary="Удалить вид запроса по ID",
        dependencies=[Depends(security.access_token_required)],
    )
    async def delete_user(self, user_id: int):
        return await self.service.delete(key="id", value=user_id)


auth_router = APIRouter()


@cbv(auth_router)
class AuthCBV:
    """CBV-класс для аутентификации пользователя."""

    service = UserService()

    @auth_router.get(
        "/login",
        status_code=status.HTTP_200_OK,
        summary="Аутентифицироваться в приложении",
    )
    async def login(
        self, response: Response, credentials: UserLogin = FilterDepends(UserLogin)
    ):
        check_user = await self.service.login(filter=credentials)
        if check_user:
            token = security.create_access_token(
                uid="kk2418",
            )
            response.set_cookie(
                settings.auth_settings.auth_token_name,
                token,
                max_age=settings.auth_settings.auth_token_lifetime_seconds,
            )
            return {"access_token": token}
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    @auth_router.get(
        "/logout", status_code=status.HTTP_200_OK, summary="Выйти из приложения"
    )
    async def logout(
        self,
        response: Response,
    ):
        response.delete_cookie(key=settings.auth_settings.auth_token_name)
        return {"message": "You have been logged out."}


tech_router = APIRouter()


@cbv(auth_router)
class TechBV:
    """CBV-класс для переадресаций на интерфейсы технических приложений."""

    @tech_router.get(
        "/log-storage",
        summary="Перейти в хранилище логов",
        dependencies=[Depends(security.access_token_required)],
    )
    async def redirest_to_log_storage():
        new_url = (
            f"{settings.logging_settings.log_host}:{settings.logging_settings.log_port}"
        )
        return RedirectResponse(url=new_url, status_code=301)

    @tech_router.get(
        "/file-storage",
        summary="Перейти в файловое хранилище",
        dependencies=[Depends(security.access_token_required)],
    )
    async def redirest_to_file_storage():
        new_url = f"{settings.storage_settings.fs_interfase_url}"
        return RedirectResponse(url=new_url, status_code=301)

    @tech_router.get(
        "/tasks-monitor",
        summary="Перейти в интерфейс мониторинга фоновых задач",
        dependencies=[Depends(security.access_token_required)],
    )
    async def redirest_to_tasks_monitor():
        new_url = f"{settings.bts_settings.bts_interface_url}"
        return RedirectResponse(url=new_url, status_code=301)
