"""Измерение эффекта вариантов public-набора (ADR-предложение, без правок в src).

Зачем
----
``public_capabilities()`` пуст (0 из 49), поэтому ``check_capabilities_subset``
отклоняет capability каждого роута и ``route_registry`` остаётся пустым —
заявленная headline-фича DSL на рантайме не поднята. Это security-контракт,
поэтому менять его молча нельзя; нужен замер, чтобы решение принял владелец.

Что здесь измеряется
--------------------
1. Сколько роутов загружается при разных public-наборах (статическая проверка).
2. Остаётся ли рантайм-контроль после снятия declaration-time проверки.

Пункт 2 — решающий. ``public`` читается только в
``check_capabilities_subset`` (gate/__init__.py). Рантайм-``CapabilityGate.check``
его не смотрит: доступ к данным проходит через ``external_database_facade``
(``db.read``/``db.write``), egress — через ``OutboundHttpClient``
(``net.outbound``). То есть public снимает требование назвать плагин в манифесте,
но не выдаёт доступ сам по себе.

Запуск (сервер не нужен — только импорт и загрузка манифестов)::

    .venv/bin/python tools/public_capabilities_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_route_manifests() -> list:
    """Читает route.toml всех маршрутов через штатный загрузчик манифестов."""
    from src.backend.services.routes.manifest_toml import load_route_manifest

    routes_dir = REPO_ROOT / "routes"
    manifests = []
    for route_dir in sorted(routes_dir.iterdir()):
        manifest_path = route_dir / "route.toml"
        if manifest_path.is_file():
            try:
                manifests.append(load_route_manifest(manifest_path))
            except Exception as exc:  # noqa: BLE001 — замер, а не валидация
                print(f"  ! {route_dir.name}: манифест не разобран: {exc}")
    return manifests


def _plugin_capabilities() -> tuple[dict[str, tuple], list[str]]:
    """Собирает capability, объявленные плагинами.

    Возвращает ``(caps, unreadable)``. Неразобранные манифесты **не**
    проглатываются: иначе плагин молча выпал бы из замера и результат
    выглядел бы точнее, чем он есть.
    """
    import tomllib

    plugins_dir = REPO_ROOT / "extensions"
    caps: dict[str, tuple] = {}
    unreadable: list[str] = []
    for plugin_dir in sorted(plugins_dir.iterdir()):
        manifest_path = plugin_dir / "plugin.toml"
        if not manifest_path.is_file():
            continue
        try:
            data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            unreadable.append(f"{plugin_dir.name} ({type(exc).__name__}: {exc})")
            continue
        caps[plugin_dir.name] = tuple(data.get("capabilities", ()))
    return caps, unreadable


def _simulate(manifests, plugin_caps, public_names) -> tuple[int, list[str]]:
    """Считает роуты, прошедшие subset-проверку при заданном public-наборе.

    Повторяет логику ``gate.check_capabilities_subset``, но без мутации
    vocabulary — нам нужно измерить, а не внедрить.
    """
    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )

    vocabulary = build_default_vocabulary()

    ok: list[str] = []
    blocked: list[str] = []
    for manifest in manifests:
        route_name = getattr(manifest, "name", "?")
        requires_raw = getattr(manifest, "requires_plugins", {}) or {}
        if isinstance(requires_raw, dict):
            requires = tuple(requires_raw.keys())
        else:
            requires = tuple(requires_raw)
        available: list = []
        for plugin_name in requires:
            available.extend(plugin_caps.get(plugin_name, ()))

        offending: list[str] = []
        for ref in getattr(manifest, "capabilities", ()) or ():
            ref_name = getattr(ref, "name", None) or (
                ref.get("name") if isinstance(ref, dict) else str(ref)
            )
            if ref_name in public_names:
                continue
            declared = [
                c for c in available if (getattr(c, "name", None) or str(c)) == ref_name
            ]
            if not declared:
                offending.append(ref_name)
            elif not vocabulary.has(ref_name):
                offending.append(ref_name)

        (blocked if offending else ok).append(route_name)
    return len(ok), blocked


def main() -> int:
    """Прогнать замер и напечатать таблицу."""
    manifests = _load_route_manifests()
    plugin_caps, unreadable = _plugin_capabilities()

    print(f"манифестов роутов найдено: {len(manifests)}")
    print(f"плагинов с capability:    {len(plugin_caps)}")
    if unreadable:
        print("  ! манифесты не разобраны (исключены из замера):")
        for item in unreadable:
            print(f"      {item}")
    print()

    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )

    real_vocab = build_default_vocabulary()
    real_public = frozenset(d.name for d in real_vocab.public_capabilities())

    variants = [
        ("ФАКТ — текущая vocabulary (решение владельца)", real_public),
        ("(было) public пуст", frozenset()),
        (
            "(было) net.inbound + net.outbound",
            frozenset({"net.inbound", "net.outbound"}),
        ),
        ("(гипотеза) + db.write", real_public | {"db.write"}),
        ("(гипотеза) + db.read + ai.invoke", real_public | {"db.read", "ai.invoke"}),
    ]

    print(f"всего capability:       {len(real_vocab.all())}")
    print(f"public по факту:        {sorted(real_public)}")
    print()
    print(f"{'вариант':44} {'прошло':>7}  оставшиеся блокеры")
    print("-" * 100)
    for label, public_names in variants:
        passed, blocked = _simulate(manifests, plugin_caps, public_names)
        blockers = ", ".join(sorted(blocked)) or "—"
        print(f"{label:44} {passed:>4}/{len(manifests)}  {blockers[:44]}")

    print()
    print("Рантайм-контроль после снятия declaration-time проверки:")
    print("  db.read/db.write → external_database_facade._check → CapabilityGate.check")
    print("  net.outbound    → OutboundHttpClient._capability_check")
    print("  оба используют check(), который НЕ читает public.")
    print("  Следствие: public снимает требование назвать плагина в route.toml,")
    print("  но не выдаёт доступ — без декларации в плагине будет отказ на рантайме.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
