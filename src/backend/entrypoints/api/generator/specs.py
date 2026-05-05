from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Sequence

from fastapi import status
from pydantic import BaseModel

from src.backend.entrypoints.api.generator.invocation import InvocationSpec

__all__ = (
    "HttpMethod",
    "ServiceFactory",
    "RouteDecorator",
    "ResponseHandler",
    "ActionSpec",
    "CrudSpec",
    "iter_registered_action_specs",
    "audit_action_specs",
)


# Wave B: глобальный реестр созданных ActionSpec для аудита
# explicit/inferred ``action_id``. Заполняется из ``__post_init__``;
# используется ``manage.py actions --strict`` и аналитикой в Streamlit.
_REGISTERED_ACTION_SPECS: list["ActionSpec"] = []


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ServiceFactory = Callable[[], Any]
RouteDecorator = Callable[
    [Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]
]
ResponseHandler = Callable[[Any, dict[str, Any]], Any | Awaitable[Any]]


@dataclass(slots=True)
class ActionSpec:
    """Декларативное описание action-роута.

    Wave 14.1 (post-sprint-2 техдолг #6): расширение полями
    Gateway-метаданных. ``ActionSpec`` остаётся декларативным
    описанием HTTP-роута; адаптер ``core/actions/spec_to_metadata.py``
    переносит расширения в :class:`ActionMetadata` для регистрации
    в ``ActionGatewayDispatcher``. Поля ``use_dispatcher`` /
    ``transports`` / ``side_effect`` / ``idempotent`` /
    ``permissions`` / ``rate_limit`` / ``timeout_ms`` / ``deprecated`` /
    ``since_version`` опциональны — у существующих 119 ActionSpec
    значения остаются дефолтными до явной декларации.

    Wave F.8 (Roadmap V10 — 3-tier model):

    * ``tier=1`` — CRUD-actions (GET/POST/PUT/DELETE с payload-model);
      будут авторегистрироваться во всех 6 протоколах (REST/gRPC/GraphQL/
      SOAP/MCP/MQTT) на этапе Wave 1.
    * ``tier=2`` — custom actions; авто только REST+gRPC+GraphQL.
    * ``tier=3`` — manual через DSL invoke (e.g. RPA-цепочки, человекочные).

    При ``tier=1`` и пустом ``action_id`` :py:meth:`__post_init__`
    автоматически инферрит идентификатор по конвенции
    ``"<resource>.<verb>"`` (resource — последнее имя в path
    после ``/api/v1/``; verb — `list`/`get`/`create`/`update`/`delete`
    по HTTP method и path-suffix).
    """

    name: str
    method: HttpMethod
    path: str
    summary: str
    service_getter: ServiceFactory
    service_method: str

    description: str | None = None
    status_code: int = status.HTTP_200_OK

    path_model: type[BaseModel] | None = None
    query_model: type[BaseModel] | None = None
    body_model: type[BaseModel] | None = None
    body_argument_name: str | None = None

    response_model: type[BaseModel] | None = None
    dependencies: Sequence[Any] = field(default_factory=tuple)
    decorators: Sequence[RouteDecorator] = field(default_factory=tuple)
    responses: dict[int, Any] | None = None
    tags: Sequence[str] = field(default_factory=tuple)

    argument_aliases: dict[str, str] = field(default_factory=dict)
    response_handler: ResponseHandler | None = None
    request_argument_name: str | None = None
    invocation: InvocationSpec | None = None

    # Wave 14.1 Gateway-метаданные (опциональные расширения).
    # ``action_id``: явная связь HTTP-роута с handler в
    # ``action_handler_registry`` (например, HTTP-роут с
    # ``name="healthcheck_database"`` делегирует в handler с
    # ``action="tech.check_database"``). По умолчанию — ``None``,
    # тогда используется ``spec.name`` (исторический случай, когда
    # spec.name совпадает с именем handler'а).
    action_id: str | None = None
    # ``use_dispatcher``: per-action override env-флага
    # ``USE_ACTION_DISPATCHER_FOR_HTTP``. ``True`` — всегда через Gateway
    # (middleware: audit/idempotency/rate_limit), ``False`` — всегда
    # прямой путь, ``None`` — следовать env-флагу (default OFF).
    use_dispatcher: bool | None = None
    transports: Sequence[str] = field(default_factory=lambda: ("http",))
    # ``None`` — адаптер выведет ``side_effect`` из HTTP method
    # (GET → "read"; POST/PUT/PATCH/DELETE → "write").
    side_effect: str | None = None
    # ``None`` — адаптер выведет ``idempotent`` из HTTP method
    # (GET/PUT/DELETE — True; POST/PATCH — False по REST-конвенции).
    idempotent: bool | None = None
    permissions: Sequence[str] = field(default_factory=tuple)
    rate_limit: int | None = None
    timeout_ms: int | None = None
    deprecated: bool = False
    since_version: str | None = None
    # Wave F.8: 3-tier модель. Default — 2 (custom action).
    tier: Literal[1, 2, 3] = 2

    # Wave B: ``True`` если caller передал ``action_id`` в конструктор;
    # ``False`` если значение получилось через tier-1 inference или
    # фолбэк на ``self.name``. ``manage.py actions --strict`` валит
    # exit 1 при наличии хотя бы одной spec с ``False``.
    _action_id_explicit: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        """Гарантирует, что ``action_id`` не ``None`` после инициализации.

        Порядок:

        1. Если caller передал ``action_id`` явно — фиксируем
           ``_action_id_explicit=True``.
        2. Иначе для ``tier=1`` пытаемся вывести по REST-конвенции через
           :func:`_infer_tier1_action_id`.
        3. Если значение всё ещё ``None`` (любой tier без явной декларации) —
           фолбэк на ``self.name`` (исторический случай, когда
           ``spec.name`` совпадает с handler-key).

        Инвариант: ``self.action_id is not None`` после ``__post_init__``.
        """
        if self.action_id is not None:
            self._action_id_explicit = True
        else:
            if self.tier == 1:
                self.action_id = _infer_tier1_action_id(self.path, self.method)
            if self.action_id is None:
                self.action_id = self.name
            self._action_id_explicit = False
        _REGISTERED_ACTION_SPECS.append(self)


def iter_registered_action_specs() -> tuple["ActionSpec", ...]:
    """Снимок реестра созданных ActionSpec (Wave B).

    Возвращает копию, чтобы внешний код не мог мутировать внутренний список.
    """
    return tuple(_REGISTERED_ACTION_SPECS)


def audit_action_specs() -> tuple[tuple["ActionSpec", ...], tuple["ActionSpec", ...]]:
    """Раскладывает зарегистрированные ActionSpec на (explicit, inferred).

    Используется командой ``manage.py actions --strict``.
    """
    explicit: list[ActionSpec] = []
    inferred: list[ActionSpec] = []
    for spec in _REGISTERED_ACTION_SPECS:
        (explicit if spec._action_id_explicit else inferred).append(spec)
    return tuple(explicit), tuple(inferred)


def _infer_tier1_action_id(path: str, method: HttpMethod) -> str:
    """Инференция ``action_id`` для Tier 1 actions по REST-конвенции.

    Алгоритм::

        /api/v1/orders/all/                   GET    → "orders.list"
        /api/v1/orders/id/{object_id}         GET    → "orders.get"
        /api/v1/orders/create/                POST   → "orders.create"
        /api/v1/orders/update/{object_id}     PUT    → "orders.update"
        /api/v1/orders/delete/{object_id}     DELETE → "orders.delete"

    Если path не вписывается в шаблон — берётся последний значимый сегмент
    как resource + verb по HTTP method.
    """
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    resource = segments[-1] if segments else "unknown"
    if "api" in segments and "v1" in segments:
        # Берём первый сегмент после api/v1 как resource.
        idx = segments.index("v1")
        if idx + 1 < len(segments):
            resource = segments[idx + 1]

    suffix = path.rstrip("/").rsplit("/", 1)[-1].lower()
    method_upper = method.upper()
    verb: str
    if method_upper == "GET":
        verb = "list" if suffix in {"all", "filter"} else "get"
    elif method_upper == "POST":
        if suffix in {"create_many"}:
            verb = "create_many"
        else:
            verb = "create"
    elif method_upper in {"PUT", "PATCH"}:
        verb = "update"
    elif method_upper == "DELETE":
        verb = "delete"
    else:
        verb = method_upper.lower()
    return f"{resource}.{verb}"


@dataclass(slots=True)
class CrudSpec:
    """DSL-описание CRUD-ресурса."""

    name: str
    service_getter: ServiceFactory
    schema_in: type[BaseModel]
    schema_out: type[BaseModel] | None = None
    version_schema: type[BaseModel] | None = None

    filter_class: type | None = None
    dependencies: Sequence[Any] = field(default_factory=tuple)
    decorators: Sequence[RouteDecorator] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)

    id_param_name: str = "object_id"
    id_param_type: type = int
    id_field_name: str = "id"
    default_order_by: str = "id"

    include_get_all: bool = True
    include_get_by_id: bool = True
    include_get_first_or_last: bool = True
    include_create: bool = True
    include_create_many: bool = True
    include_update: bool = True
    include_delete: bool = True
    include_filter: bool = True
    include_versions: bool = True
    include_restore: bool = True
    include_changes: bool = True

    list_path: str = "/all/"
    by_id_path: str = "/id/{object_id}"
    first_or_last_path: str = "/first-or-last/"
    create_path: str = "/create/"
    create_many_path: str = "/create_many/"
    update_path: str = "/update/{object_id}"
    delete_path: str = "/delete/{object_id}"
    filter_path: str = "/filter/"
    all_versions_path: str = "/all_versions/{object_id}"
    latest_version_path: str = "/latest_version/{object_id}"
    restore_path: str = "/restore_to_version/{object_id}"
    changes_path: str = "/changes/{object_id}"
