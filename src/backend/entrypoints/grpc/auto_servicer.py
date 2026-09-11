"""Динамическое построение gRPC Servicer'ов для авто-сгенерированных .proto.

Wave 1.3 (Roadmap V10): после ``tools/codegen_proto.py`` в
``src/entrypoints/grpc/protobuf/auto/`` появляются ``<service>_pb2.py``
+ ``<service>_pb2_grpc.py``. Этот модуль:

1. Загружает auto-сгенерированные модули по convention
   (``importlib`` — без жёстких импортов, чтобы не падать,
   когда codegen ещё не запускался).
2. Для каждого сервиса собирает Servicer-класс с RPC-методами,
   которые делегируют в ``ActionHandlerRegistry.dispatch`` через
   :func:`src.entrypoints.base.dispatch_action`.
3. Pydantic↔protobuf маппинг — простой:
   - request → dict через ``MessageToDict``;
   - dict → response message через ``ParseDict`` (по имени message,
     найденного в pb2-модуле).

Регистрация в gRPC-сервере выполняется на этапе старта через
:func:`register_auto_servicers`. Если auto/ пуст — функция тихо
возвращает 0 (не ломает старт).

Servicer-классы НЕ перекрывают существующие hand-written
``OrderGRPCServicer`` / ``InvokerGRPCServicer`` — они живут под именем
``<Service>AutoServicer`` и в отдельном пакете ``orders.auto`` и т.п.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("AutoServicerBundle", "build_auto_servicers", "register_auto_servicers")


_AUTO_PROTO_PACKAGE = "src.backend.entrypoints.grpc.protobuf.auto"

_AUTO_PROTO_DIR = Path(__file__).resolve().parent / "protobuf" / "auto"

# Генерированные pb2_grpc делают ``from auto import orderkinds_pb2`` —
# каталог protobuf должен быть в sys.path, иначе импорт пары падает
# (0 зарегистрированных auto-servicers).
if str(_AUTO_PROTO_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_AUTO_PROTO_DIR.parent))


class AutoServicerBundle:
    """Набор: pb2-модуль, pb2_grpc-модуль и собранный Servicer-класс.

    Хранится для тестов и регистрации в gRPC-сервере.

    Attributes:
        service: Имя сервиса (``orders``).
        pb2: Импортированный модуль ``<service>_pb2``.
        pb2_grpc: Импортированный модуль ``<service>_pb2_grpc``.
        servicer_cls: Динамически собранный Servicer-класс.
        add_to_server: Функция ``add_<Service>AutoServiceServicer_to_server``.

    """

    __slots__ = ("add_to_server", "pb2", "pb2_grpc", "service", "servicer_cls")

    def __init__(
        self,
        service: str,
        pb2: Any,
        pb2_grpc: Any,
        servicer_cls: type,
        add_to_server: Callable[..., Any],
    ) -> None:
        """Инициализирует middleware.

        :param service: значение service.
        :param pb2: значение pb2.
        :param pb2_grpc: значение pb2_grpc.
        :param servicer_cls: значение servicer_cls.
        :param add_to_server: значение add_to_server.
        """
        self.service = service
        self.pb2 = pb2
        self.pb2_grpc = pb2_grpc
        self.servicer_cls = servicer_cls
        self.add_to_server = add_to_server


def _discover_services() -> list[str]:
    """Вернуть имена сервисов, для которых есть скомпилированные pb2-файлы.

    Сервис определяется наличием обоих файлов: ``<name>_pb2.py``
    и ``<name>_pb2_grpc.py`` в ``auto/``.
    """
    if not _AUTO_PROTO_DIR.exists():
        return []
    names: set[str] = set()
    for path in _AUTO_PROTO_DIR.iterdir():
        if path.suffix != ".py" or path.stem == "__init__":
            continue
        if path.stem.endswith("_pb2"):
            names.add(path.stem.removesuffix("_pb2"))
    # Только те, где есть и _pb2_grpc.py.
    return sorted(
        name for name in names if (_AUTO_PROTO_DIR / f"{name}_pb2_grpc.py").exists()
    )


def _import_pair(service: str) -> tuple[Any, Any] | None:
    """Импортировать пару ``<service>_pb2`` и ``<service>_pb2_grpc``."""
    try:
        pb2 = importlib.import_module(f"{_AUTO_PROTO_PACKAGE}.{service}_pb2")
        pb2_grpc = importlib.import_module(f"{_AUTO_PROTO_PACKAGE}.{service}_pb2_grpc")
    except Exception as exc:
        logger.warning("Не удалось импортировать pb2/pb2_grpc для %s: %s", service, exc)
        return None
    return pb2, pb2_grpc


def _find_servicer_class(pb2_grpc: Any, service: str) -> type | None:
    """Найти ``<Service>AutoServiceServicer`` в pb2_grpc-модуле."""
    expected = f"{service.capitalize()}AutoServiceServicer"
    return getattr(pb2_grpc, expected, None)


def _find_add_to_server(pb2_grpc: Any, service: str) -> Callable[..., Any] | None:
    """Найти ``add_<Service>AutoServiceServicer_to_server``."""
    expected = f"add_{service.capitalize()}AutoServiceServicer_to_server"
    return getattr(pb2_grpc, expected, None)


def _build_rpc_method(action_id: str) -> Callable[..., Any]:
    """Собрать async RPC-метод, делегирующий в ``dispatch_action``.

    Контракт: метод принимает ``request`` (protobuf message) и ``context``
    (gRPC ServicerContext), возвращает ``response`` (protobuf message).
    """
    from google.protobuf.json_format import (  # type: ignore[import-untyped]
        MessageToDict,
        ParseDict,
    )

    async def rpc_impl(self: Any, request: Any, context: Any) -> Any:
        from src.backend.entrypoints.base import dispatch_action

        payload = MessageToDict(
            request, preserving_proto_field_name=True, use_integers_for_enums=True
        )
        result = await dispatch_action(action=action_id, payload=payload, source="grpc")

        # Превратить result в dict.
        data: dict[str, Any]
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")
        elif isinstance(result, dict):
            data = result
        elif result is None:
            data = {}
        else:
            data = {"data": str(result)}

        response_cls = self._response_cls_for(action_id)
        if response_cls is None:
            return None
        msg = response_cls()
        try:
            ParseDict(data, msg, ignore_unknown_fields=True)
        except Exception as exc:
            logger.warning("ParseDict %s упал: %s", action_id, exc)
        return msg

    rpc_impl.__name__ = action_id.replace(".", "_")
    rpc_impl.__doc__ = f"Авто-RPC для action '{action_id}' (Wave 1.3)."
    return rpc_impl


def _verb_to_rpc_name(action_id: str) -> str:
    """Совпадает с ``tools/codegen_proto._verb_to_rpc_name``.

    Обязано матчиться с именами RPC-методов в pb2_grpc.
    """
    raw = action_id.split(".", 1)[1] if "." in action_id else action_id
    parts = raw.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def build_auto_servicers() -> tuple[AutoServicerBundle, ...]:
    """Собрать все ``AutoServicerBundle`` по содержимому ``auto/``.

    Делегирует в реестр через ``dispatch_action`` (унифицированно с
    ``OrderGRPCServicer`` / ``InvokerGRPCServicer``).
    """
    bundles: list[AutoServicerBundle] = []
    for service in _discover_services():
        pair = _import_pair(service)
        if pair is None:
            continue
        pb2, pb2_grpc = pair

        base_cls = _find_servicer_class(pb2_grpc, service)
        add_fn = _find_add_to_server(pb2_grpc, service)
        if base_cls is None or add_fn is None:
            logger.warning(
                "В %s_pb2_grpc.py не найден ожидаемый Servicer/add_*; пропуск", service
            )
            continue

        servicer_cls = _build_servicer_class(service, base_cls, pb2)
        bundles.append(
            AutoServicerBundle(
                service=service,
                pb2=pb2,
                pb2_grpc=pb2_grpc,
                servicer_cls=servicer_cls,
                add_to_server=add_fn,
            )
        )
    return tuple(bundles)


def _build_servicer_class(service: str, base_cls: type, pb2: Any) -> type:
    """Динамически собрать Servicer-подкласс с RPC-методами.

    Для каждого RPC-метода в ``base_cls`` (унаследованного от
    ``<Service>AutoServiceServicer``) ищем соответствующий
    ``action_id`` через реестр и подключаем :func:`_build_rpc_method`.
    """
    from src.backend.core.api.extensions import action_handler_registry

    grpc_actions = [
        m
        for m in action_handler_registry.list_metadata("grpc")
        if (m.action.split(".", 1)[0] if "." in m.action else "misc") == service
    ]

    # Собираем словарь rpc_name → action_id.
    action_by_rpc: dict[str, str] = {
        _verb_to_rpc_name(meta.action): meta.action for meta in grpc_actions
    }

    # Собираем словарь action_id → response message-класс (по конвенции
    # имени message в pb2). Если у action нет output_model, использовался
    # ``EmptyResponse`` — он есть в pb2 как ``EmptyResponse``.
    response_cls_by_action: dict[str, type | None] = {}
    for meta in grpc_actions:
        if meta.output_model is not None:
            response_cls_by_action[meta.action] = getattr(
                pb2, meta.output_model.__name__, None
            )
        else:
            response_cls_by_action[meta.action] = getattr(pb2, "EmptyResponse", None)

    # Динамический класс.
    namespace: dict[str, Any] = {
        "_response_cls_for": lambda self, action_id: response_cls_by_action.get(
            action_id
        ),
        "__doc__": (
            f"Авто-сгенерированный Servicer для домена '{service}' (Wave 1.3)."
        ),
    }

    for rpc_name, action_id in action_by_rpc.items():
        namespace[rpc_name] = _build_rpc_method(action_id)

    return type(f"{service.capitalize()}AutoServicer", (base_cls,), namespace)


def _make_dispatch_behavior(
    *,
    bundle: Any,
    service: str,
    rpc_name: str,
    input_type_name: str,
    output_type_name: str,
    servicer_fallback: Any,
) -> Any:
    """Мост RPC → ActionDispatcher (G5, 2026-09-11).

    Раньше behavior брали из сгенерированного абстрактного servicer'а —
    каждый вызов падал UNIMPLEMENTED ``NotImplementedError``. Теперь RPC
    диспетчеризуется в action ``<domain>.<rpc_lower>`` через
    ``dispatch_action`` (единый путь с REST/SOAP/WS).

    Ограничения контракта (proto-стабы lossy — GAPS G5):
        * запрос → payload через ``MessageToDict``;
        * dict-результат → ``ParseDict(ignore_unknown_fields=True)``;
        * не-dict результат (list и т.п.) → пустой response + warning —
          полный маппинг списков требует регенерации proto (v2);
        * незарегистрированный action → UNIMPLEMENTED.
    """
    from google.protobuf.json_format import MessageToDict, ParseDict
    from grpc import StatusCode

    from src.backend.entrypoints.base import dispatch_action

    action = f"{service}.{rpc_name.lower()}"

    async def behavior(request: Any, context: Any) -> Any:
        from src.backend.core.api.extensions import action_handler_registry

        if not action_handler_registry.is_registered(action):
            await context.abort(
                StatusCode.UNIMPLEMENTED,
                f"action '{action}' not registered in ActionHandlerRegistry",
            )

        payload = MessageToDict(request, preserving_proto_field_name=True)
        try:
            result = await dispatch_action(
                action=action, payload=payload, source="grpc"
            )
        except KeyError as exc:
            await context.abort(StatusCode.UNIMPLEMENTED, str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 — gRPC boundary: INTERNAL + details
            await context.abort(StatusCode.INTERNAL, str(exc)[:200])

        output_type = getattr(bundle.pb2, output_type_name)
        if isinstance(result, dict):
            return ParseDict(result, output_type(), ignore_unknown_fields=True)
        if not isinstance(result, output_type):
            logger.warning(
                "gRPC auto-servicer: %s вернул %s — proto-контракт lossy, "
                "возвращён пустой response (GAPS G5)",
                action,
                type(result).__name__,
            )
        return result if isinstance(result, output_type) else output_type()

    if servicer_fallback is None or not callable(servicer_fallback):
        return behavior
    return behavior


def register_auto_servicers(grpc_server: Any) -> int:
    """Зарегистрировать все ``AutoServicerBundle`` в gRPC-сервере.

    Prod-fix 2026-09-09 (M6-#3): генерированный
    ``add_<Service>AutoServiceServicer_to_server`` регистрирует bare-функции
    (``servicer.Method``) — gRPC v1.66+ при dispatch читает
    ``request_streaming`` и падает
    («'function' object has no attribute 'request_streaming'»).
    Вместо generated-add регистрируем через
    ``add_generic_rpc_handlers`` + ``grpc.unary_unary_rpc_method_handler``
    с явными (де)сериализаторами, взятыми из stub-методов.

    Args:
        grpc_server: Экземпляр ``grpc.aio.Server``.

    Returns:
        Количество зарегистрированных сервисов.

    """
    import grpc as grpc_lib

    # G5: standalone grpc-serve не проходит через FastAPI auto-loop, где
    # ActionHandlerRegistry наполняется; регистрируем здесь (idempotent).
    try:
        from src.backend.dsl.commands.setup import register_action_handlers

        register_action_handlers()
    except Exception as exc:  # noqa: BLE001 — startup не блокируем (как в app_factory)
        logger.warning("gRPC auto-servicer: register_action_handlers пропущен: %s", exc)

    bundles = build_auto_servicers()
    registered = 0
    for bundle in bundles:
        servicer = bundle.servicer_cls()
        service_cap = bundle.service.capitalize()
        stub_cls = getattr(bundle.pb2_grpc, f"{service_cap}AutoServiceStub", None)
        if stub_cls is None:
            logger.warning(
                "gRPC auto-servicer: stub %s не найден — домен пропущен", service_cap
            )
            continue

        # M6-#3 prod-fix (2026-09-09): классы сообщений — из дескриптора
        # сервиса (pb2); методы динамического servicer'а = имена RPC.
        service_desc = bundle.pb2.DESCRIPTOR.services_by_name.get(
            f"{service_cap}AutoService"
        )
        if service_desc is None:
            logger.warning(
                "gRPC auto-servicer: дескриптор %s не найден — домен пропущен",
                service_cap,
            )
            continue

        method_handlers: dict[str, Any] = {}
        service_full_name = service_desc.full_name
        for method_desc in service_desc.methods:
            rpc_name = method_desc.name
            behavior = _make_dispatch_behavior(
                bundle=bundle,
                service=bundle.service,
                rpc_name=rpc_name,
                input_type_name=method_desc.input_type.name,
                output_type_name=method_desc.output_type.name,
                servicer_fallback=getattr(servicer, rpc_name, None),
            )
            if behavior is None:
                continue
            request_deserializer = getattr(
                bundle.pb2, method_desc.input_type.name
            ).FromString
            response_serializer = getattr(
                bundle.pb2, method_desc.output_type.name
            ).SerializeToString
            method_handlers[rpc_name] = grpc_lib.unary_unary_rpc_method_handler(
                behavior,
                request_deserializer=request_deserializer,
                response_serializer=response_serializer,
            )

        if not method_handlers:
            logger.warning(
                "gRPC auto-servicer: нет RPC-методов для домена '%s' — пропущен",
                bundle.service,
            )
            continue

        service_full_name = service_desc.full_name

        generic_handler = grpc_lib.method_handlers_generic_handler(
            service_full_name, method_handlers
        )
        grpc_server.add_generic_rpc_handlers((generic_handler,))
        registered += 1
        logger.info(
            "Wave 1.3: gRPC auto-servicer зарегистрирован для домена '%s' "
            "(%d RPC через add_generic_rpc_handlers)",
            bundle.service,
            len(method_handlers),
        )
    return registered
