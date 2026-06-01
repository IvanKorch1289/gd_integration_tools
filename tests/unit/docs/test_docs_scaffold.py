"""Smoke-тесты для Sphinx docs scaffold (К10 Sprint-2 Wave 5).

Проверяют минимально необходимое присутствие файлов scaffold,
не запуская sphinx-build (может быть недоступен в CI без доп. deps).
"""

from __future__ import annotations

from pathlib import Path


# Корень проекта: поднимаемся на 4 уровня от tests/unit/docs/
_PROJECT_ROOT = Path(__file__).parents[3]
_DOCS_DIR = _PROJECT_ROOT / "docs"


def test_conf_py_loadable() -> None:
    """conf.py загружается без синтаксических ошибок.

    Выполняет exec() содержимого conf.py в изолированном namespace.
    Проверяет, что переменная project объявлена корректно.
    """
    conf_path = _DOCS_DIR / "conf.py"
    assert conf_path.exists(), f"docs/conf.py не найден: {conf_path}"

    namespace: dict = {}
    exec(conf_path.read_text(encoding="utf-8"), namespace)  # noqa: S102

    assert "project" in namespace, "conf.py не объявляет переменную 'project'"
    assert namespace["project"] == "gd_integration_tools"


def test_index_md_exists() -> None:
    """docs/index.md присутствует и содержит ожидаемый заголовок.

    Проверяет наличие Diátaxis toctree-директив в корневом индексе.
    Проект использует Markdown (index.md), не reStructuredText (index.rst).
    """
    index_path = _DOCS_DIR / "index.md"
    assert index_path.exists(), f"docs/index.md не найден: {index_path}"

    content = index_path.read_text(encoding="utf-8")
    assert "tutorials" in content, "index.md не содержит toctree tutorials"
    assert "how-to" in content, "index.md не содержит toctree how-to"
    assert "reference" in content, "index.md не содержит toctree reference"
    assert "explanation" in content, "index.md не содержит toctree explanation"


def test_diataxis_folders_present() -> None:
    """Все 4 Diátaxis-директории существуют с index.md файлами.

    Проверяет наличие tutorials/, howto/, reference/, explanations/
    и их корневых index.md согласно Diátaxis-структуре.
    """
    quadrants = ["tutorials", "how-to", "reference", "explanation"]
    for quadrant in quadrants:
        folder = _DOCS_DIR / quadrant
        assert folder.is_dir(), f"Diátaxis-директория отсутствует: docs/{quadrant}/"

        index_md = folder / "index.md"
        assert index_md.exists(), f"index.md отсутствует в docs/{quadrant}/"
