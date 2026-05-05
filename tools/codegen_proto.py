# ruff: noqa: S101
"""CLI: генерация ``.proto`` + компиляция ``_pb2.py``/``_pb2_grpc.py`` из ActionMetadata.

Wave 1.3 (Roadmap V10) — компайл-тайм codegen для gRPC-транспорта.

Алгоритм::

    1. bootstrap services + register_action_handlers + v1 routers
    2. action_handler_registry.list_metadata() → метаданные
    3. фильтр: ``"grpc" in transports``
    4. группировка по ``service`` (первая часть ``action_id``)
    5. на каждую группу:
       PydanticToProtoConverter.convert_model(input_model)
       PydanticToProtoConverter.convert_model(output_model)
       ProtoFile + ProtoService с RPC-методами
       render_proto_file → ``src/entrypoints/grpc/protobuf/auto/<service>.proto``
    6. для каждого .proto:
       python -m grpc_tools.protoc → _pb2.py + _pb2_grpc.py

Использование::

    uv run python tools/codegen_proto.py            # написать + скомпилировать
    uv run python tools/codegen_proto.py --dry-run  # только список actions/proto
    uv run python tools/codegen_proto.py --no-compile  # сгенерировать без protoc

Pre-build target: ``make grpc-codegen``.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.interfaces.action_dispatcher import ActionMetadata

# Корень репозитория = parent(parent(__file__)).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUTO_PROTO_DIR = _REPO_ROOT / "src" / "entrypoints" / "grpc" / "protobuf" / "auto"
_PROTO_INCLUDE_DIR = _REPO_ROOT / "src" / "entrypoints" / "grpc" / "protobuf"

logger = logging.getLogger("codegen_proto")


@dataclass(slots=True)
class _ServiceGroup:
    """Группа actions по имени сервиса (``orders.list`` → ``orders``)."""

    service: str
    actions: list[ActionMetadata] = field(default_factory=list)


def _bootstrap_registry() -> None:
    """Инициализация Service-DI + register_action_handlers + v1 routers.

    Повторяет бутстрап из ``manage.py._bootstrap``: без него
    ``action_handler_registry`` будет пуст (CRUD-actions регистрируются
    при импорте v1-роутеров).
    """
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    try:
        from src.backend.entrypoints.api.v1.routers import get_v1_routers

        get_v1_routers()
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_v1_routers пропущен в codegen-bootstrap: %s", exc)


def _filter_grpc_actions() -> tuple[ActionMetadata, ...]:
    """Вернуть actions, у которых в ``transports`` есть ``"grpc"``."""
    from src.backend.dsl.commands.action_registry import action_handler_registry

    return action_handler_registry.list_metadata("grpc")


def _group_by_service(metas: Iterable[ActionMetadata]) -> list[_ServiceGroup]:
    """Сгруппировать actions по первой части ``action_id``.

    ``orders.list`` → service ``orders``;
    ``tech.health`` → service ``tech``;
    actions без точки попадают в группу ``misc``.
    """
    groups: dict[str, _ServiceGroup] = {}
    for meta in metas:
        service = meta.action.split(".", 1)[0] if "." in meta.action else "misc"
        groups.setdefault(service, _ServiceGroup(service=service)).actions.append(meta)

    return [groups[k] for k in sorted(groups)]


def _verb_to_rpc_name(action_id: str) -> str:
    """``orders.list`` → ``List``; ``orders.create_many`` → ``CreateMany``.

    Если в action нет точки — берётся весь action в CamelCase.
    """
    raw = action_id.split(".", 1)[1] if "." in action_id else action_id
    parts = raw.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def _build_proto_file_for_group(group: _ServiceGroup) -> _ProtoBuildResult:
    """Собрать :class:`ProtoFile` для группы actions сервиса."""
    from src.backend.core.actions.proto_adapter import (
        ProtoFile,
        ProtoService,
        ProtoServiceRpc,
        PydanticToProtoConverter,
    )

    converter = PydanticToProtoConverter()
    rpcs: list[ProtoServiceRpc] = []
    skipped: list[str] = []

    # Запасной message: для action без input/output.
    converter_messages_before = set()  # marker — заполним по факту

    for meta in group.actions:
        if meta.input_model is None and meta.output_model is None:
            skipped.append(
                f"{meta.action}: ни input_model, ни output_model — пропуск"
            )
            continue

        request_name = _ensure_message(converter, meta.input_model, suffix="Request")
        response_name = _ensure_message(
            converter, meta.output_model, suffix="Response"
        )
        rpcs.append(
            ProtoServiceRpc(
                name=_verb_to_rpc_name(meta.action),
                request_message=request_name,
                response_message=response_name,
                comment=meta.description or None,
            )
        )

    proto = ProtoFile(
        package=f"{group.service}.auto",
        messages=list(converter.messages),
        services=[
            ProtoService(
                name=f"{group.service.capitalize()}AutoService",
                rpcs=rpcs,
                comment=(
                    f"Авто-сгенерированный сервис для домена '{group.service}' "
                    f"(Wave 1.3 Roadmap V10)."
                ),
            )
        ]
        if rpcs
        else [],
        warnings=list(converter.warnings) + skipped,
    )
    if converter.needs_any_import:
        proto.imports.add("google/protobuf/any.proto")

    _ = converter_messages_before  # silence unused
    return _ProtoBuildResult(proto=proto, skipped=skipped)


@dataclass(slots=True)
class _ProtoBuildResult:
    """Результат билда одного ``.proto`` файла."""

    proto: object  # ProtoFile (опускаем точную типизацию ради lazy-import)
    skipped: list[str] = field(default_factory=list)


def _ensure_message(
    converter: object,  # PydanticToProtoConverter
    model: type | None,
    *,
    suffix: str,
) -> str:
    """Вернуть имя protobuf-message для модели (или Empty-сообщение).

    Если ``model`` — :class:`BaseModel`, вызываем ``converter.convert_model``.
    Если ``None`` — регистрируем (один раз) пустое сообщение ``Empty<suffix>``
    в converter и возвращаем его имя.
    """
    from pydantic import BaseModel

    from src.backend.core.actions.proto_adapter import (
        ProtoMessage,
        PydanticToProtoConverter,
    )

    assert isinstance(converter, PydanticToProtoConverter)
    if isinstance(model, type) and issubclass(model, BaseModel):
        return converter.convert_model(model)

    # Запасное Empty-сообщение.
    empty_name = f"Empty{suffix}"
    if empty_name not in {m.name for m in converter.messages}:
        # Регистрируем «вручную»: PydanticToProtoConverter не имеет публичного
        # API для добавления message без модели, поэтому используем
        # protected-доступ (контракт стабилен — внутренний хелпер).
        converter._messages[empty_name] = ProtoMessage(  # noqa: SLF001
            name=empty_name,
            comment=f"Пустое {suffix.lower()} (action без {suffix.lower()}_model).",
        )
    return empty_name


def _write_proto(group: _ServiceGroup, proto: object) -> Path:
    """Записать ``.proto`` файл на диск, вернуть путь."""
    from src.backend.core.actions.proto_adapter import ProtoFile, render_proto_file

    assert isinstance(proto, ProtoFile)
    _AUTO_PROTO_DIR.mkdir(parents=True, exist_ok=True)
    proto_path = _AUTO_PROTO_DIR / f"{group.service}.proto"
    proto_path.write_text(render_proto_file(proto), encoding="utf-8")
    return proto_path


def _compile_proto(proto_path: Path) -> tuple[Path, Path]:
    """Скомпилировать ``.proto`` через ``python -m grpc_tools.protoc``.

    Returns:
        Кортеж (path к ``_pb2.py``, path к ``_pb2_grpc.py``).
    """
    output_dir = _AUTO_PROTO_DIR

    # ``proto_path.relative_to(_PROTO_INCLUDE_DIR)`` — относительный путь
    # для protoc, чтобы пакет был ``auto.<service>``.
    rel = proto_path.relative_to(_PROTO_INCLUDE_DIR)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{_PROTO_INCLUDE_DIR}",
        f"--python_out={_PROTO_INCLUDE_DIR}",
        f"--grpc_python_out={_PROTO_INCLUDE_DIR}",
        str(rel),
    ]
    logger.info("protoc: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(
            f"protoc failed for {proto_path.name}:\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )

    pb2 = output_dir / f"{proto_path.stem}_pb2.py"
    pb2_grpc = output_dir / f"{proto_path.stem}_pb2_grpc.py"
    return pb2, pb2_grpc


def run_codegen(
    *,
    dry_run: bool = False,
    compile_proto: bool = True,
) -> int:
    """Главная функция CLI.

    Args:
        dry_run: Если True — не пишем файлы и не компилируем,
            только печатаем план.
        compile_proto: Если False — пишем ``.proto``, но не вызываем ``protoc``.

    Returns:
        Количество сгенерированных ``.proto``-файлов.
    """
    _bootstrap_registry()
    metas = _filter_grpc_actions()
    if not metas:
        print("[codegen_proto] нет actions с 'grpc' в transports — нечего генерировать")
        return 0

    groups = _group_by_service(metas)
    print(f"[codegen_proto] найдено {len(metas)} grpc-actions в {len(groups)} сервисах")
    for g in groups:
        print(f"  {g.service}: {len(g.actions)} action(s)")
        for meta in g.actions:
            print(f"    - {meta.action}")

    if dry_run:
        print("[codegen_proto] dry-run — файлы не записаны")
        return 0

    written = 0
    for group in groups:
        result = _build_proto_file_for_group(group)
        proto = result.proto
        # Пропускаем сервисы без RPC.
        from src.backend.core.actions.proto_adapter import ProtoFile

        assert isinstance(proto, ProtoFile)
        if not proto.services or not proto.services[0].rpcs:
            print(f"  [skip] {group.service}: нет валидных RPC")
            continue
        path = _write_proto(group, proto)
        print(f"  [write] {path.relative_to(_REPO_ROOT)}")
        for w in proto.warnings:
            print(f"    [warn] {w}")
        if compile_proto:
            pb2, pb2_grpc = _compile_proto(path)
            print(f"  [compile] {pb2.name}, {pb2_grpc.name}")
        written += 1

    return written


def _build_argparser() -> argparse.ArgumentParser:
    """Построить argparse-парсер CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать план без записи файлов и вызова protoc.",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Сгенерировать .proto, но не вызывать grpc_tools.protoc.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Удалить ранее сгенерированные .proto/_pb2 в auto/ перед запуском.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging."
    )
    return parser


def _maybe_clean() -> None:
    """Убрать содержимое ``auto/``, кроме ``__init__.py``."""
    if not _AUTO_PROTO_DIR.exists():
        return
    for path in _AUTO_PROTO_DIR.iterdir():
        if path.name == "__init__.py":
            continue
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    """Точка входа CLI."""
    args = _build_argparser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.clean:
        _maybe_clean()
    written = run_codegen(dry_run=args.dry_run, compile_proto=not args.no_compile)
    print(f"[codegen_proto] done: {written} .proto файлов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
