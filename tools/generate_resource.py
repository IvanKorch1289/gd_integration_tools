import argparse
import sys
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]


def snake_to_camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def write_file(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        print(f"⚠️ Файл уже существует (пропуск): {path.relative_to(ROOT)}")
        return

    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"✅ Создан: {path.relative_to(ROOT)}")


def render_schema(resource: str, class_name: str) -> str:
    return dedent(
        f"""
        from pydantic import ConfigDict, Field

        from app.schemas.base import BaseSchema


        __all__ = (
            "{class_name}SchemaIn",
            "{class_name}SchemaOut",
            "{class_name}VersionSchemaOut",
        )


        class {class_name}SchemaIn(BaseSchema):
            \"\"\"
            Входная схема ресурса {resource}.
            \"\"\"
            name: str = Field(description="Название сущности")


        class {class_name}SchemaOut({class_name}SchemaIn):
            \"\"\"
            Выходная схема ресурса {resource}.
            \"\"\"
            model_config = ConfigDict(from_attributes=True)

            id: int = Field(description="Идентификатор сущности")


        class {class_name}VersionSchemaOut({class_name}SchemaOut):
            \"\"\"
            Схема версии ресурса {resource}.
            \"\"\"
            operation_type: int = Field(description="Тип операции")
            transaction_id: int = Field(description="Идентификатор транзакции")
        """
    )


def render_repository(resource: str, class_name: str) -> str:
    return dedent(
        f"""
        from app.infrastructure.repositories.base import BaseRepository
        from app.models.{resource} import {class_name}
        from app.core.decorators.singleton import singleton


        __all__ = ("get_{resource}_repo",)


        @singleton
        class {class_name}Repository(BaseRepository[{class_name}]):
            \"\"\"
            Репозиторий ресурса {resource}.
            \"\"\"
            pass


        def get_{resource}_repo() -> {class_name}Repository:
            return {class_name}Repository(model={class_name})
        """
    )


def render_service(resource: str, class_name: str) -> str:
    return dedent(
        f"""
        from pydantic import BaseModel

        from app.infrastructure.repositories.{resource} import {class_name}Repository, get_{resource}_repo
        from app.schemas.route_schemas.{resource} import (
            {class_name}SchemaIn,
            {class_name}SchemaOut,
            {class_name}VersionSchemaOut,
        )
        from app.services.base import BaseService
        from app.core.decorators.singleton import singleton


        __all__ = ("get_{resource}_service",)


        @singleton
        class {class_name}Service(
            BaseService[
                {class_name}Repository,
                {class_name}SchemaOut,
                {class_name}SchemaIn,
                {class_name}VersionSchemaOut,
            ]
        ):
            \"\"\"
            Сервис ресурса {resource}.
            \"\"\"

            def __init__(
                self,
                schema_in: type[BaseModel],
                schema_out: type[BaseModel],
                version_schema: type[BaseModel],
                repo: {class_name}Repository,
            ) -> None:
                super().__init__(
                    repo=repo,
                    request_schema=schema_in,
                    response_schema=schema_out,
                    version_schema=version_schema,
                )


        def get_{resource}_service() -> {class_name}Service:
            return {class_name}Service(
                repo=get_{resource}_repo(),
                schema_in={class_name}SchemaIn,
                schema_out={class_name}SchemaOut,
                version_schema={class_name}VersionSchemaOut,
            )
        """
    )


def render_router(resource: str, class_name: str) -> str:
    return dedent(
        f"""
        from fastapi import APIRouter, Depends, status

        from app.entrypoints.api.dependencies.auth import require_api_key
        from app.entrypoints.api.dsl.actions import ActionRouterBuilder, CrudSpec
        from app.schemas.route_schemas.{resource} import (
            {class_name}SchemaIn,
            {class_name}SchemaOut,
            {class_name}VersionSchemaOut,
        )
        from app.services.{resource} import get_{resource}_service
        from app.core.decorators.limiting import route_limiting


        __all__ = ("router",)


        router = APIRouter()
        builder = ActionRouterBuilder(router)

        builder.add_crud_resource(
            CrudSpec(
                name="{resource}",
                service_getter=get_{resource}_service,
                schema_in={class_name}SchemaIn,
                schema_out={class_name}SchemaOut,
                version_schema={class_name}VersionSchemaOut,
                dependencies=[Depends(require_api_key)],
                decorators=[route_limiting],
                tags=("{class_name}",),
            )
        )
        """
    )


def render_model(resource: str, class_name: str) -> str:
    return dedent(
        f"""
        from sqlalchemy import String
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        __all__ = ("{class_name}",)


        class {class_name}(Base):
            \"\"\"
            ORM-модель ресурса {resource}.
            \"\"\"

            __tablename__ = "{resource}"

            id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
            name: Mapped[str] = mapped_column(String(255), nullable=False)
        """
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Генератор заготовок ресурса (Clean Architecture + DSL)."
    )
    parser.add_argument("resource", help="Имя ресурса в snake_case, например order_kinds")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие файлы.")
    args = parser.parse_args()

    resource = args.resource.strip().lower()
    
    if not resource.isidentifier():
        print(f"❌ Ошибка: '{resource}' не является валидным именем для Python (используй snake_case).", file=sys.stderr)
        sys.exit(1)

    class_name = snake_to_camel(resource.rstrip("s"))

    files = {
        ROOT / "app" / "schemas" / "route_schemas" / f"{resource}.py": render_schema(resource, class_name),
        ROOT / "app" / "repositories" / f"{resource}.py": render_repository(resource, class_name),
        ROOT / "app" / "services" / "route_services" / f"{resource}.py": render_service(resource, class_name),
        ROOT / "app" / "api" / "v1" / "endpoints" / f"{resource}.py": render_router(resource, class_name),
        ROOT / "app" / "models" / f"{resource}.py": render_model(resource, class_name),
    }

    print(f"🚀 Генерация ресурса '{resource}' (Модель: {class_name})...")
    for path, content in files.items():
        write_file(path, content, force=args.force)
    print("✨ Готово!")


if __name__ == "__main__":
    main()
