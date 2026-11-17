"""Гейт: обязательные capability-декларации у роутов и плагинов (ADR-0430).

Правило
-------
* **Роут** (``routes/*/route.toml``) обязан объявлять ``net.inbound`` —
  каждый DSL-роут является HTTP-entrypoint (публичный scope соответствует
  его маршруту). Это минимальный контракт, который проверяем автоматически.
* **Плагин** (``extensions/*/plugin.toml``) обязан объявлять хотя бы одну
  capability. Легаси-плагины (до ADR-0430) вынесены в baseline-файл
  ``.security/route-capabilities-baseline.txt`` — это рэтчет: новые плагины
  обязаны декларировать, старые мигрируются постепенно.

Отчёт (не блокирует)
--------------------
Ресурсные capability (``storage.*`` / ``db.*`` / ``cache.*`` / ``net.outbound``)
собираются из атрибута ``capabilities`` процессоров, которые роут
использует в своих DSL-спеках. Несовпадения печатаются как WARN-отчёт:
строгая проверка требует стабилизации формата scope у процессоров.

Использование::

    python tools/check_route_capabilities.py            # проверка (exit 1 при новых нарушениях)
    python tools/check_route_capabilities.py --report    # только отчёт
    python tools/check_route_capabilities.py --update-baseline
"""

from __future__ import annotations

import argparse
import logging
import sys
import tomllib
from pathlib import Path

import yaml

_LOGGER = logging.getLogger("check_route_capabilities")

_BASELINE_PATH = Path(".security/route-capabilities-baseline.txt")
_ROUTE_DIR = Path("routes")
_PLUGIN_DIR = Path("extensions")

#: Capability, обязательная для любого DSL-роута (HTTP-entrypoint).
_ROUTE_REQUIRED = ("net.inbound",)

#: Ресурсные семейства — для WARN-отчёта (строгая проверка отключена).
_RESOURCE_PREFIXES = ("storage.", "db.", "cache.", "net.outbound")

#: Capability, которые **обязаны** быть объявлены роутом, если их требует
#: шаг: все scope-required capability из vocabulary (ADR-0454). Префиксы
#: выше — частный случай (в них scope обязателен), список получается из
#: vocabulary, чтобы новые ресурсные capability не проходили мимо гейта.
_SCOPE_REQUIRED_FALLBACK_PREFIXES = _RESOURCE_PREFIXES


def _scope_required_capabilities() -> frozenset[str]:
    """Имена capability, для которых в vocabulary обязателен scope.

    Returns:
        Множество имён (``scope_required=True``). При недоступности
        vocabulary — пустое множество (гейт не блокирует).

    """
    try:
        from src.backend.core.security.capabilities.vocabulary.defaults import (
            build_default_vocabulary,
        )

        return frozenset(
            definition.name
            for definition in build_default_vocabulary().all()
            if getattr(definition, "scope_required", False)
        )
    except Exception:  # noqa: BLE001 — vocabulary недоступна → не блокируем
        return frozenset()


def _is_scope_required(capability: str) -> bool:
    """Требует ли capability явного scope (и, значит, декларации в роуте).

    Args:
        capability: Имя capability.

    Returns:
        ``True`` — capability ресурсная (scope обязателен).

    """
    required = _scope_required_capabilities()
    if required:
        return capability in required
    return capability.startswith(_SCOPE_REQUIRED_FALLBACK_PREFIXES)


def _load_manifests(directory: Path, section: str) -> list[tuple[str, Path, dict]]:
    """Собрать ``(name, path, manifest)`` по TOML-манифестам каталога.

    ``route.toml`` хранит манифест в секции ``[route]``, ``plugin.toml`` —
    в плоском виде (ADR-0343: верхний уровень TOML).
    """
    result: list[tuple[str, Path, dict]] = []
    if not directory.exists():
        return result
    for path in sorted(directory.rglob("*.toml")):
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"ERROR: не удалось разобрать {path}: {exc}", file=sys.stderr)
            continue
        manifest = raw.get(section)
        if not isinstance(manifest, dict):
            if section == "plugin" and "name" in raw:
                manifest = raw
            else:
                continue
        name = str(manifest.get("name") or path.parent.name)
        result.append((name, path, manifest))
    return result


def _declared_capabilities(manifest: dict) -> set[str]:
    """Имена объявленных capability (без scope)."""
    names: set[str] = set()
    for ref in manifest.get("capabilities") or []:
        if isinstance(ref, dict):
            name = str(ref.get("name") or "").strip()
            if name:
                names.add(name)
        elif isinstance(ref, str) and ref.strip():
            names.add(ref.split(":", 1)[0].strip())
    return names


def _pipeline_files(manifest: dict, manifest_path: Path) -> list[Path]:
    """DSL-спеки, на которые ссылается манифест."""
    files: list[Path] = []
    base = manifest_path.parent
    for key in ("pipelines", "workflows", "specs"):
        for entry in manifest.get(key) or []:
            if isinstance(entry, str):
                candidate = base / entry
                if candidate.exists():
                    files.append(candidate)
    return files


def _step_types(spec_paths: list[Path]) -> set[str]:
    """Типы шагов, встречающихся в DSL-спеках."""
    types: set[str] = set()
    for path in spec_paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError, yaml.YAMLError:
            continue
        steps = data.get("steps") or []
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict):
                types.update(str(key) for key in step)
    return types


def _processor_capabilities(step_types: set[str]) -> set[str]:
    """Capability, требуемые процессорами указанных типов.

    Два источника (ADR-0454):

    1. :func:`src.backend.dsl.builders.step_catalog.step_capability_requirements`
       — динамическая карта «шаг → все capability процессора»
       (``required_capability`` + декларации ``@processor(capabilities=...)``).
       Тот же источник истины, что и рантайм-проверка шага;
    2. :data:`src.backend.dsl.cli.lint.PROCESSOR_CAPABILITIES` — историческая
       статическая карта для шагов, класс процессора которых не разрешается
       статически (``http_call`` → ``net.outbound`` и т.п.).

    ADR-0435: проверка **строгая** — раньше несовпадение только печаталось
    как WARN.
    """
    if not step_types:
        return set()
    from src.backend.dsl.builders.step_catalog import step_capability_requirements
    from src.backend.dsl.cli.lint import PROCESSOR_CAPABILITIES

    dynamic = step_capability_requirements()
    required: set[str] = set()
    for step_type in step_types:
        required.update(dynamic.get(step_type, ()))
        required.update(PROCESSOR_CAPABILITIES.get(step_type, ()))
    return required


def _baseline_entries() -> set[str]:
    """Имена легаси-плагинов из baseline-файла."""
    if not _BASELINE_PATH.exists():
        return set()
    return {
        line.strip()
        for line in _BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _write_baseline(names: set[str]) -> None:
    """Перезаписать baseline-файл отсортированным списком."""
    _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Легаси-манифесты без обязательных capability-деклараций (ADR-0430, рэтчет).\n"
        "# Формат: <kind>:<name> (kind = route | plugin).\n"
        "# Новые роуты/плагины обязаны декларировать — гейт блокирует.\n"
        "# Файл уменьшается по мере миграции; обновление: --update-baseline\n"
    )
    _BASELINE_PATH.write_text(
        header + "\n".join(sorted(names)) + ("\n" if names else ""), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="только отчёт")
    parser.add_argument(
        "--update-baseline", action="store_true", help="перезаписать baseline-файл"
    )
    args = parser.parse_args(argv)

    routes = _load_manifests(_ROUTE_DIR, "route")
    plugins = _load_manifests(_PLUGIN_DIR, "plugin")

    baseline = _baseline_entries()
    legacy_routes = {
        f"route:{name}"
        for name, _, manifest in routes
        if "net.inbound" not in _declared_capabilities(manifest)
    }
    legacy_plugins = {
        f"plugin:{name}"
        for name, _, manifest in plugins
        if not _declared_capabilities(manifest)
    }
    if args.update_baseline:
        entries = legacy_routes | legacy_plugins
        _write_baseline(entries)
        print(f"baseline обновлён: {len(entries)} записей → {_BASELINE_PATH}")
        return 0

    violations: list[str] = []
    for name, path, manifest in routes:
        declared = _declared_capabilities(manifest)
        missing = [cap for cap in _ROUTE_REQUIRED if cap not in declared]
        if missing and f"route:{name}" not in baseline:
            violations.append(f"роут {name} ({path}): не объявлено {missing}")
        elif missing:
            print(f"WARN: роут {name} ({path}): нет {missing} (baseline — легаси)")
        specs = _pipeline_files(manifest, path)
        required = _processor_capabilities(_step_types(specs))
        for cap in sorted(required):
            if _is_scope_required(cap) and cap not in declared:
                if f"route:{name}" in baseline:
                    print(
                        f"WARN: роут {name} ({path}): использует {cap}, но не "
                        f"декларирует (baseline — легаси)"
                    )
                    continue
                violations.append(
                    f"роут {name} ({path}): использует {cap}, но не декларирует "
                    f"capability"
                )

    for name, path, manifest in plugins:
        if _declared_capabilities(manifest):
            continue
        if f"plugin:{name}" in baseline:
            continue
        violations.append(f"плагин {name} ({path}): нет ни одной capability-декларации")

    if violations:
        print("НОВЫЕ нарушения capability-деклараций:", file=sys.stderr)
        for violation in sorted(violations):
            print(f"  {violation}", file=sys.stderr)
        return 1

    print(
        f"Capability-декларации: OK (роутов {len(routes)}, плагинов {len(plugins)}, "
        f"легаси в baseline {len(baseline & (legacy_routes | legacy_plugins))})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
