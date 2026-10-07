"""Точный разбор блокеров каждого DSL-роута — до конкретного шага.

Зачем
----
V11-подсистема роутов выключена по умолчанию
(``V11_ROUTE_LOADER_ENABLED=false``), поэтому её reference-роуты в
``routes/`` никогда не проходили регистрацию и **молча устарели**: часть
шагов ссылается на процессоры и параметры, которых больше нет в API.

`GET /api/v1/admin/routes` уже отдаёт причину отказа (см. раздел 2.14
аудита), но она обрезается до одного сообщения на роут. Этот инструмент
идёт глубже: для каждого pipeline-файла находит **первый** невалидный шаг
и печатает, что именно не так и какой контракт ожидается.

Запуск (сервер не нужен)::

    .venv/bin/python tools/route_blockers_report.py

Ничего не изменяет: только читает и печатает.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _manifest_capabilities(manifest: Any) -> list[str]:
    """Capability, объявленные манифестом, в виде ``name(scope)``."""
    out: list[str] = []
    for ref in getattr(manifest, "capabilities", ()) or ():
        name = getattr(ref, "name", str(ref))
        scope = getattr(ref, "scope", None)
        out.append(f"{name}({scope})" if scope else f"{name}(None)")
    return out


def _allowed_processors() -> set[str]:
    """Имена процессоров, доступных DSL-бандлеру."""
    from src.backend.dsl.builder import RouteBuilder

    names: set[str] = set()
    for cls in RouteBuilder.__mro__:
        if cls in (object, type):
            continue
        for attr, value in cls.__dict__.items():
            if attr.startswith("_") or not isinstance(attr, str):
                continue
            if not attr.isidentifier():
                continue
            if callable(value) or isinstance(
                value, (property, classmethod, staticmethod)
            ):
                names.add(attr)
    return names


def _check_steps(route_name: str, yaml_text: str, allowed: set[str]) -> list[str]:
    """Возвращает список проблем по шагам pipeline."""
    import yaml

    problems: list[str] = []
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        return [f"YAML не разбирается: {exc}"]

    # В V11-пути route_id приходит из route.toml (default_route_id), поэтому
    # его отсутствие в pipeline-YAML дефектом маршрута НЕ является.
    # ``from:`` поддерживается загрузчиком как алиас ``source`` с 2026-10-06.
    if "from" in data and "source" in data:
        problems.append("объявлены и from:, и source: — они алиасы, нужен один")

    steps = data.get("processors") or data.get("steps") or []
    if not isinstance(steps, list):
        return problems + ["processors/steps не список"]

    real_steps = [s for s in steps if s is not None]
    for index, step in enumerate(real_steps):
        if isinstance(step, str):
            name, params = step, {}
        elif isinstance(step, dict) and len(step) == 1:
            name, params = next(iter(step.items()))
            params = params if isinstance(params, dict) else {}
        else:
            problems.append(f"шаг[{index}]: неверная форма {step!r}")
            continue
        if name not in allowed:
            problems.append(f"шаг[{index}] `{name}`: процессора нет в RouteBuilder")
            continue
        problems.extend(_check_params(route_name, name, params, index))
    return problems


def _check_params(
    route_name: str, name: str, params: dict[str, Any], index: int
) -> list[str]:
    """Сверяет переданные параметры с сигнатурой процессора."""
    import inspect

    from src.backend.dsl.builder import RouteBuilder

    method = getattr(RouteBuilder, name, None)
    if method is None or not params:
        return []
    try:
        sig = inspect.signature(method)
    except TypeError, ValueError:
        return []

    has_var_kw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if has_var_kw:
        return []
    allowed = {
        n
        for n, p in sig.parameters.items()
        if p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and n != "self"
    }
    unknown = [k for k in params if k not in allowed]
    if not unknown:
        return []
    return [
        f"шаг[{index}] `{name}`: неизвестные параметры {sorted(unknown)}; "
        f"сигнатура принимает {sorted(allowed)[:8]}"
    ]


def main() -> int:
    """Напечатать блокеры по каждому роуту."""
    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )
    from src.backend.services.routes.manifest_toml import load_route_manifest

    allowed = _allowed_processors()
    vocabulary = build_default_vocabulary()
    public = {d.name for d in vocabulary.public_capabilities()}

    routes_dir = REPO_ROOT / "routes"
    route_dirs = sorted(p for p in routes_dir.iterdir() if p.is_dir())
    print(f"роутов: {len(route_dirs)} | процессоров в бандлере: {len(allowed)}")
    print(f"public capability: {sorted(public)}")
    print()

    total_problems = 0
    for route_dir in route_dirs:
        manifest_path = route_dir / "route.toml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_route_manifest(manifest_path)
        except Exception as exc:  # noqa: BLE001 — отчёт, а не валидация
            print(f"[{route_dir.name}] манифест не разобран: {exc}")
            continue

        print(f"── {route_dir.name} " + "─" * max(0, 46 - len(route_dir.name)))

        caps = _manifest_capabilities(manifest)
        missing_vocab = []
        for cap in caps:
            name = cap.split("(", 1)[0]
            if not vocabulary.has(name):
                missing_vocab.append(name)
        if missing_vocab:
            print(f"   capability: НЕТ в vocabulary → {sorted(set(missing_vocab))}")
        non_public = [
            c.split("(", 1)[0] for c in caps if c.split("(", 1)[0] not in public
        ]
        if non_public:
            print(f"   capability: не public → {sorted(set(non_public))}")
        flag = getattr(manifest, "feature_flag", None)
        if isinstance(flag, dict) and flag.get("name"):
            print(f"   feature_flag: {flag['name']} (резолвится из ENV)")

        problems: list[str] = []
        for rel in getattr(manifest, "pipelines", ()) or ():
            pipeline = route_dir / rel
            if not pipeline.is_file():
                problems.append(f"{rel}: файл не найден")
                continue
            for problem in _check_steps(
                manifest.name, pipeline.read_text(encoding="utf-8"), allowed
            ):
                problems.append(f"{rel}: {problem}")

        if problems:
            total_problems += len(problems)
            for problem in problems:
                print(f"   ✗ {problem}")
        else:
            print("   ✓ шаги валидны по текущему API")
        print()

    print(f"всего проблем: {total_problems}")
    print()
    print("Порядок разблокировки: capability-гит → feature_flag (ENV) →")
    print("шаги pipeline. Каждая починка вскрывает следующую — это не")
    print("редкость, а признак того, что подсистема была выключена и её")
    print("reference-роуты никогда не проверялись на прочность.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
