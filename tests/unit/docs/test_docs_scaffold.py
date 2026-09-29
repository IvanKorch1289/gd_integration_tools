"""Smoke-тесты для docs scaffold (К10 Sprint-2 Wave 5).

Docs-конфигурация проекта — **mkdocs**, а не Sphinx: B2 (M10.2) перевёл
сборку на mkdocs-material + mike и удалил sphinx/sphinx-multiversion из
зависимостей (см. комментарий в ``pyproject.toml`` около ``mkdocs``-пинов).
Поэтому тест проверяет ``mkdocs.yml``, а не ``docs/conf.py``: тот файл был
удалён вместе с тулчейном, и его воссоздание означало бы возврат
намеренно удалённого Sphinx.

Diátaxis-проверки ниже не зависят от инструмента и остаются как есть.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Корень проекта: поднимаемся на 4 уровня от tests/unit/docs/
_PROJECT_ROOT = Path(__file__).parents[3]
_DOCS_DIR = _PROJECT_ROOT / "docs"
_MKDOCS_CONFIG = _PROJECT_ROOT / "mkdocs.yml"


def test_mkdocs_config_parses() -> None:
    """mkdocs.yml — канонический конфиг docs: парсится и объявляет проект.

    Заменяет прежний smoke-тест Sphinx ``conf.py``, который падал после
    удаления Sphinx. Проверяется то же свойство scaffold'а — конфиг
    загружается и декларирует проект, — но для реально используемого
    инструмента.
    """
    assert _MKDOCS_CONFIG.exists(), f"mkdocs.yml не найден: {_MKDOCS_CONFIG}"
    assert not (_DOCS_DIR / "conf.py").exists(), (
        "docs/conf.py не должен появляться: Sphinx удалён в пользу mkdocs "
        "(B2 / M10.2). Возврат файла означает возврат удалённого тулчейна."
    )

    config = yaml.safe_load(_MKDOCS_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(config, dict), "mkdocs.yml должен быть YAML-маппингом"
    assert config.get("site_name") == "gd_integration_tools", (
        f"site_name в mkdocs.yml должен быть 'gd_integration_tools', "
        f"получено {config.get('site_name')!r}"
    )
    assert config.get("docs_dir") == "docs", (
        f"docs_dir должен указывать на docs/, получено {config.get('docs_dir')!r}"
    )


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
