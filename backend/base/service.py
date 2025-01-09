import json
import sys
import traceback
from typing import Generic, List, Type, TypeVar

from fastapi import Response
from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.repository import AbstractRepository
from backend.base.schemas import PublicSchema
from backend.core.utils import utilities


ConcreteRepo = TypeVar("ConcreteRepo", bound=AbstractRepository)
ConcreteResponseSchema = TypeVar("ConcreteResponseSchema", bound=PublicSchema)


class BaseService(Generic[ConcreteRepo]):

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None

    async def _transfer(self, instance):
        if instance and isinstance(instance, self.repo.model):
            return await instance.transfer_model_to_schema(schema=self.response_schema)
        return instance

    async def _get_and_transfer(self, key: str, value: int):
        instance = await self.repo.get(key=key, value=value)
        return await self._transfer(instance)

    async def add(self, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.add(data=data)
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    async def update(self, key: str, value: int, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.update(key=key, value=value, data=data)
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    @utilities.caching(schema=response_schema, expire=300)
    async def all(self) -> List[PublicSchema] | None:
        try:
            list_instances = [
                await self._transfer(instance) for instance in await self.repo.all()
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get(self, key: str, value: int) -> PublicSchema | None:
        try:
            return await self._get_and_transfer(key=key, value=value)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get_by_params(self, filter: Filter) -> List[PublicSchema] | None:
        try:
            list_instances = [
                await self._transfer(instance)
                for instance in await self.repo.get_by_params(filter=filter)
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def get_or_add(
        self, key: str, value: int, data: dict = None
    ) -> PublicSchema | None:
        try:
            instance = await self._get_and_transfer(key=key, value=value)
            if not instance:
                await self.repo.add(data=data)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def delete(self, key: str, value: int) -> str:
        try:
            await self.repo.delete(key=key, value=value)
            return f"Object (id = {value}) successfully deleted"
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def healthcheck(self):
        db_check = await utilities.health_check_database()
        redis_check = await utilities.health_check_redis()
        s3_check = await utilities.health_check_s3()
        graylog_check = await utilities.health_check_graylog()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "graylog": graylog_check,
        }

        if all(response_data.values()):
            status_code = 200
            message = "All systems are operational."
            is_all_services_active = True
        else:
            status_code = 500
            message = "One or more components are not functioning properly."
            is_all_services_active = False

        response_body = {
            "message": message,
            "is_all_services_active": is_all_services_active,
            "details": response_data,
        }

        return Response(
            content=json.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )
