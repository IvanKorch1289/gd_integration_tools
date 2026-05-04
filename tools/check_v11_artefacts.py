"""Wave R1.2 — pre-push gate: проверка свежести committed V11-артефактов.

Скрипт регенерирует артефакты во временную директорию и сравнивает их
байт-в-байт с committed-версиями из ``docs/reference/``. Если кто-то
изменил pydantic-модели (``PluginManifestV11``/``RouteManifestV11``) или
capability vocabulary, не обновив артефакты через ``make v11-artefacts``,
скрипт завершится с кодом 1 и подскажет, какую команду запустить.

Запуск::

    uv run python tools/check_v11_artefacts.py

Используется как pre-push hook (см. ``.pre-commit-config.yaml``) и из
``make v11-artefacts-check``.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

# Гарантируем доступ к sibling-модулю ``export_v11_artefacts`` независимо
# от способа запуска (CLI / pytest / pre-commit hook).
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from export_v11_artefacts import (  # noqa: E402
    CAPABILITIES_MD as _DEFAULT_CAPABILITIES_MD,  # noqa: E402
)
from export_v11_artefacts import SCHEMAS_DIR as _DEFAULT_SCHEMAS_DIR  # noqa: E402
from export_v11_artefacts import (  # noqa: E402
    export_capability_catalog,
    export_plugin_schema,
    export_route_schema,
)

__all__ = ("CAPABILITIES_MD", "PLUGIN_SCHEMA", "ROUTE_SCHEMA", "main")

# Committed-пути, за свежесть которых отвечает этот gate.
# Эти переменные намеренно сделаны module-level, чтобы тесты могли
# их подменять через ``monkeypatch.setattr``.
PLUGIN_SCHEMA: Path = _DEFAULT_SCHEMAS_DIR / "plugin.toml.schema.json"
ROUTE_SCHEMA: Path = _DEFAULT_SCHEMAS_DIR / "route.toml.schema.json"
CAPABILITIES_MD: Path = _DEFAULT_CAPABILITIES_MD

# Каждое описание: (committed-файл, фабрика-экспортёр, имя для tmp).
_Exporter = Callable[[Path], Path]
_Spec = tuple[Path, _Exporter, str]


def _specs() -> Iterable[_Spec]:
    """Список (committed_path, exporter, tmp_filename).

    Читается на момент вызова, чтобы поддерживать monkeypatch
    модульных констант в тестах.
    """
    return (
        (PLUGIN_SCHEMA, export_plugin_schema, "plugin.toml.schema.json"),
        (ROUTE_SCHEMA, export_route_schema, "route.toml.schema.json"),
        (CAPABILITIES_MD, export_capability_catalog, "capabilities.md"),
    )


def _check_one(committed: Path, exporter: _Exporter, tmp_name: str) -> bool:
    """Проверить один артефакт. Возвращает True при совпадении."""
    if not committed.is_file():
        print(
            f"[FAIL] {committed}: committed-файл отсутствует "
            "(run `make v11-artefacts` to refresh)"
        )
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        fresh = exporter(Path(tmpdir) / tmp_name)
        if fresh.read_bytes() != committed.read_bytes():
            print(f"[FAIL] {committed}: stale (run `make v11-artefacts` to refresh)")
            return False
    print(f"[OK] {committed}")
    return True


def main() -> int:
    """CLI entry point — exit 0 при синке, exit 1 при расхождении."""
    ok = True
    for committed, exporter, tmp_name in _specs():
        if not _check_one(committed, exporter, tmp_name):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
