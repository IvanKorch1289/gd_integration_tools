"""Тесты для ``tools/generate_current_metrics.py``.

P1 (2026-10-15): audit asks явно разделить static route-пакеты
(на диске) и runtime-зарегистрированные routes (после ``create_app()``).
Эти тесты фиксируют:

* ``_static_route_packages()`` правильно считает директории с
  ``route.toml`` и игнорирует ``__pycache__``/скрытые;
* ``_static_route_packages()`` возвращает 0 если ``routes/`` отсутствует;
* скрипт импортируется без побочных эффектов (важно для CI-гейта).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOL_PATH = PROJECT_ROOT / "tools" / "generate_current_metrics.py"


@pytest.fixture()
def metric_tool_module() -> object:
    """Импортирует tools/generate_current_metrics.py как модуль.

    Скрипт лежит в ``tools/`` без ``__init__.py``; используем
    ``importlib.util.spec_from_file_location``.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_current_metrics", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"Не удалось загрузить spec для {TOOL_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("generate_current_metrics", module)
    spec.loader.exec_module(module)
    return module


def test_static_route_packages_counts_real_routes(metric_tool_module: object) -> None:
    """Реальные route-пакеты в репозитории должны быть посчитаны.

    Реальный минимум — ``hello_route`` (используется во многих тестах).
    Не завязываемся на точное число (рост codebase), но требуем >=1.
    """
    count = metric_tool_module._static_route_packages()  # noqa: SLF001
    assert isinstance(count, int)
    assert count >= 1, (
        f"Ожидаем ≥1 route-пакета на диске, получили {count}; "
        "вероятно, переименована директория routes/<name>"
    )


def test_static_route_packages_ignores_underscore_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metric_tool_module: object
) -> None:
    """Директории с префиксом ``_`` или ``.`` игнорируются (legacy/hidden)."""
    fake_routes = tmp_path / "routes"
    fake_routes.mkdir()
    # Валидный пакет
    (fake_routes / "real_route").mkdir()
    (fake_routes / "real_route" / "route.toml").write_text(
        'name = "real"\n', encoding="utf-8"
    )
    # Поддиректории, которые НЕ должны считаться
    (fake_routes / "_private").mkdir()
    (fake_routes / "_private" / "route.toml").write_text(
        'name = "x"\n', encoding="utf-8"
    )
    (fake_routes / ".hidden").mkdir()
    (fake_routes / ".hidden" / "route.toml").write_text(
        'name = "x"\n', encoding="utf-8"
    )
    # Директория без route.toml НЕ должна считаться
    (fake_routes / "not_a_route").mkdir()
    (fake_routes / "not_a_route" / "main.py").write_text("# nothing\n", encoding="utf-8")
    # Файл на верхнем уровне — игнорируется
    (fake_routes / "stray.txt").write_text("not a dir\n", encoding="utf-8")

    monkeypatch.setattr(metric_tool_module, "PROJECT_ROOT", tmp_path)
    count = metric_tool_module._static_route_packages()  # noqa: SLF001
    assert count == 1, (
        f"Ожидаем 1 (только real_route), получили {count}; "
        "поддиректории без route.toml или с _-/.  префиксом должны игнорироваться"
    )


def test_static_route_packages_returns_zero_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metric_tool_module: object
) -> None:
    """Если директории ``routes/`` нет — возвращаем 0, не бросаем."""
    monkeypatch.setattr(metric_tool_module, "PROJECT_ROOT", tmp_path)
    count = metric_tool_module._static_route_packages()  # noqa: SLF001
    assert count == 0


def test_render_block_includes_static_route_packages(
    metric_tool_module: object,
) -> None:
    """Сгенерированный блок README упоминает static route-пакеты.

    P1 (2026-10-15): audit требует, чтобы metric tool явно отличал
    runtime DSL-маршруты от static route-пакетов на диске. Без этой
    строки пользователь видит ``DSL-маршрутов (runtime) = 0`` и думает,
    что routes нет вообще.
    """
    metrics = {
        "HEAD": "deadbeef" * 5,
        "action_count": 0,
        "dsl_route_count": 0,
        "static_route_packages": 5,
        "protocol_count": 0,
        "protocols": [],
        "middleware_count": 0,
        "openapi_paths": 0,
        "openapi_schemas": 0,
        "test_count": "n/a",
        "coverage_fail_under": "unset",
        "layer_baseline": "unavailable",
    }
    block = metric_tool_module.render_block(metrics)  # noqa: SLF001
    assert "Route-пакетов (static)" in block, (
        "render_block не упоминает static route-пакеты; "
        "audit finding P1 (2026-10-15) не закрыт"
    )
    assert "DSL-маршрутов (runtime)" in block, (
        "render_block должен явно помечать runtime metric как 'runtime', "
        "а не обобщённо 'DSL-маршрутов'"
    )
