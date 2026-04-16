from enum import Enum
from typing import Any, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = (
    "ExternalDBObjectTypeChoices",
    "ExternalDBParameterModeChoices",
    "ExternalDBParameterMeta",
    "ExternalDBObjectMeta",
    "ExternalDBObjectChoices",
)


class ExternalDBObjectTypeChoices(str, Enum):
    """
    Типы разрешённых объектов внешних БД.
    """

    view = "view"
    function = "function"
    procedure = "procedure"
    query = "query"


class ExternalDBParameterModeChoices(str, Enum):
    """
    Режим передачи аргументов в вызов БД.

    named:
        Используется именованная нотация, например:
        - PostgreSQL: func(arg_name => :bind_name)
        - Oracle PL/SQL: proc(arg_name => :bind_name)

    positional:
        Используется позиционная нотация:
        - func(:p0, :p1)
    """

    named = "named"
    positional = "positional"


class ExternalDBParameterMeta(BaseModel):
    """
    Метаданные одного аргумента внешнего DB-вызова.

    body_field:
        Имя поля во входном payload/body.

    db_name:
        Имя аргумента в БД.
        Если не задано, используется body_field.

    bind_name:
        Имя bind-параметра в SQLAlchemy text(...).
        Если не задано, генерируется автоматически.

    required:
        Является ли аргумент обязательным.

    default:
        Значение по умолчанию, если поле не пришло.

    exclude_if_none:
        Если True и итоговое значение None, параметр не будет
        передан в SQL-вызов вообще.
    """

    model_config = ConfigDict(frozen=True)

    body_field: str = Field(
        ...,
        title="Поле body",
        min_length=1,
        description="Имя поля во входном body/payload",
        examples=["employee_id", "report_date"],
    )

    db_name: str | None = Field(
        default=None,
        title="Имя аргумента БД",
        min_length=1,
        description="Имя аргумента в функции/процедуре БД",
        examples=["p_employee_id"],
    )

    bind_name: str | None = Field(
        default=None,
        title="Имя bind-параметра",
        min_length=1,
        description="Имя bind-параметра в SQLAlchemy text(...)",
        examples=["employee_id"],
    )

    required: bool = Field(
        default=True,
        title="Параметр обязателен",
        description="Признак обязательности параметра",
        examples=[True],
    )

    default: Any = Field(
        default=None,
        title="Значение по умолчанию",
        description="Значение по умолчанию, если поле отсутствует",
    )

    exclude_if_none: bool = Field(
        default=False,
        title="Исключать None",
        description="Если True, параметр не передаётся в вызов при значении None",
        examples=[False],
    )


class ExternalDBObjectMeta(BaseModel):
    """
    Метаданные разрешённого объекта внешней БД.

    Используется как value для enum-элемента в ExternalDBObjectChoices.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    profile_name: str = Field(
        ...,
        title="Профиль БД",
        min_length=1,
        description="Профиль внешней БД для выбора подключения",
        examples=["oracle_1", "pg_1"],
    )

    schema: str | None = Field(
        default=None,
        title="Схема",
        min_length=1,
        description="Схема БД, в которой расположен объект",
        examples=["REPORTING", "public"],
    )

    object_name: str = Field(
        ...,
        title="Имя объекта",
        min_length=1,
        description="Имя view, function, procedure или техническое имя query",
        examples=["V_EMPLOYEES", "get_sales_report", "daily_report_query"],
    )

    object_type: ExternalDBObjectTypeChoices = Field(
        ...,
        title="Тип объекта",
        description="Тип разрешённого объекта внешней БД",
        examples=["view", "function", "procedure", "query"],
    )

    request_schema: Type[BaseModel] | None = Field(
        default=None,
        title="Схема запроса",
        description="Pydantic-схема для входной валидации payload/body",
    )

    response_schema: Type[BaseModel] | None = Field(
        default=None,
        title="Схема ответа",
        description="Pydantic-схема для валидации результата",
    )

    oracle_package: str | None = Field(
        default=None,
        title="Oracle package",
        min_length=1,
        description="Имя Oracle package, если объект находится внутри package",
        examples=["PKG_EMPLOYEES"],
    )

    sql_text: str | None = Field(
        default=None,
        title="SQL-текст",
        description="Текст SQL-запроса для object_type='query'",
        examples=[
            (
                "SELECT report_date, total_amount "
                "FROM public.daily_report "
                "WHERE report_date = :report_date"
            )
        ],
    )

    cache_enabled: bool = Field(
        default=False,
        title="Кэширование включено",
        description="Разрешено ли кэширование результата на сервисном уровне",
        examples=[True],
    )

    returns_rows: bool = Field(
        default=False,
        title="Возвращает строки",
        description="Признак того, что вызов возвращает набор строк",
        examples=[True],
    )

    parameter_mode: ExternalDBParameterModeChoices = Field(
        default=ExternalDBParameterModeChoices.named,
        title="Режим передачи аргументов",
        description="Способ передачи аргументов в функцию/процедуру БД",
        examples=["named", "positional"],
    )

    parameters: list[ExternalDBParameterMeta] = Field(
        default_factory=list,
        title="Параметры вызова",
        description="Явное описание аргументов вызова функции/процедуры",
    )

    body_root_field: str | None = Field(
        default=None,
        title="Корневое поле body",
        min_length=1,
        description=(
            "Если задано, параметры вызова берутся не из всего body, "
            "а из вложенного body[body_root_field]"
        ),
        examples=["data"],
    )

    @model_validator(mode="after")
    def validate_meta(self) -> "ExternalDBObjectMeta":
        """
        Проверяет согласованность описания объекта.
        """
        if self.object_type == ExternalDBObjectTypeChoices.query and not self.sql_text:
            raise ValueError("Для object_type='query' обязательно поле sql_text")

        if (
            self.object_type != ExternalDBObjectTypeChoices.query
            and self.sql_text is not None
        ):
            raise ValueError("Поле sql_text допустимо только для object_type='query'")

        if self.object_type == ExternalDBObjectTypeChoices.view and self.parameters:
            raise ValueError("Для view не нужно описывать parameters")

        if (
            self.object_type
            in {
                ExternalDBObjectTypeChoices.function,
                ExternalDBObjectTypeChoices.procedure,
            }
            and not self.parameters
        ):
            raise ValueError(
                "Для function/procedure необходимо явно описать parameters"
            )

        if (
            self.object_type == ExternalDBObjectTypeChoices.procedure
            and self.cache_enabled
        ):
            raise ValueError("Кэширование procedure запрещено")

        if (
            self.object_type == ExternalDBObjectTypeChoices.procedure
            and self.returns_rows
        ):
            raise ValueError("Procedure не должна быть помечена как returns_rows=True")

        return self

    @property
    def qualified_name(self) -> str:
        """
        Возвращает полное имя объекта.

        Форматы:
        - schema.object_name
        - schema.package.object_name
        - package.object_name
        - object_name
        """
        parts: list[str] = []

        if self.schema:
            parts.append(self.schema)

        if self.oracle_package:
            parts.append(self.oracle_package)

        parts.append(self.object_name)

        return ".".join(parts)

    @property
    def is_read_operation(self) -> bool:
        """
        Возвращает True для read-only операций.
        """
        return self.object_type in {
            ExternalDBObjectTypeChoices.view,
            ExternalDBObjectTypeChoices.function,
            ExternalDBObjectTypeChoices.query,
        }


class ExternalDBObjectChoices(Enum):
    """
    Реестр разрешённых объектов внешних БД.

    Важно:
    - сюда попадают только whitelist-объекты;
    - произвольный SQL из запроса пользователя не допускается;
    - request_schema/response_schema можно постепенно заменять
      на реальные модели проекта.
    """

    # ------------------------------------------------------------------
    # Примеры. Замени на свои реальные объекты по мере внедрения.
    # ------------------------------------------------------------------

    ORACLE_EMPLOYEES_VIEW = ExternalDBObjectMeta(
        profile_name="oracle_1",
        schema="REPORTING",
        object_name="V_EMPLOYEES",
        object_type=ExternalDBObjectTypeChoices.view,
        request_schema=None,
        response_schema=None,
        cache_enabled=True,
        returns_rows=True,
    )

    ORACLE_REFRESH_EMPLOYEE_CACHE = ExternalDBObjectMeta(
        profile_name="oracle_1",
        schema="REPORTING",
        object_name="REFRESH_EMPLOYEE_CACHE",
        object_type=ExternalDBObjectTypeChoices.procedure,
        oracle_package="PKG_EMPLOYEES",
        request_schema=None,
        response_schema=None,
        parameter_mode=ExternalDBParameterModeChoices.named,
        parameters=[
            ExternalDBParameterMeta(
                body_field="employee_id",
                db_name="p_employee_id",
                bind_name="employee_id",
            ),
            ExternalDBParameterMeta(
                body_field="force",
                db_name="p_force",
                bind_name="force",
                required=False,
                default=False,
            ),
            ExternalDBParameterMeta(
                body_field="requested_by",
                db_name="p_requested_by",
                bind_name="requested_by",
            ),
        ],
    )

    PG_ANALYTICS_REPORT_FUNCTION = ExternalDBObjectMeta(
        profile_name="pg_1",
        schema="public",
        object_name="get_sales_report",
        object_type=ExternalDBObjectTypeChoices.function,
        request_schema=None,
        response_schema=None,
        parameter_mode=ExternalDBParameterModeChoices.named,
        parameters=[
            ExternalDBParameterMeta(
                body_field="report_date", db_name="report_date", bind_name="report_date"
            ),
            ExternalDBParameterMeta(
                body_field="limit",
                db_name="limit_rows",
                bind_name="limit_rows",
                required=False,
                default=100,
            ),
        ],
        cache_enabled=True,
        returns_rows=True,
    )

    PG_DAILY_REPORT_QUERY = ExternalDBObjectMeta(
        profile_name="pg_1",
        schema="public",
        object_name="daily_report_query",
        object_type=ExternalDBObjectTypeChoices.query,
        request_schema=None,
        response_schema=None,
        sql_text=(
            "SELECT report_date, total_amount, total_count "
            "FROM public.daily_report "
            "WHERE report_date = :report_date"
        ),
        cache_enabled=True,
        returns_rows=True,
    )

    @property
    def meta(self) -> ExternalDBObjectMeta:
        """
        Возвращает метаданные enum-элемента.
        """
        return self.value

    @classmethod
    def get(cls, name: str) -> "ExternalDBObjectChoices":
        """
        Возвращает enum-элемент по имени.
        """
        return cls[name]

    @classmethod
    def list_by_profile(cls, profile_name: str) -> list["ExternalDBObjectChoices"]:
        """
        Возвращает все разрешённые объекты для конкретного профиля БД.
        """
        return [item for item in cls if item.meta.profile_name == profile_name]
