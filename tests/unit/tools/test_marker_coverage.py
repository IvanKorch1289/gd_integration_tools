"""F-X: ни один обязательный маркер не должен выбирать 0 тестов.

Контракт аудита: ``pytest -m <marker>`` с EXIT=5 (0 тестов) — это
**отсутствие вердикта**, а не PASS. Раньше ``property`` и ``security``
выбирали 0 из 20 961 теста: ``security`` не был зарегистрирован при
включённом ``--strict-markers``, а явной разметки не существовало ни у
одного теста. Из-за этого обязательные прогоны молча ничего не проверяли.

Тест закрывает класс дефекта, а не единичный случай: если новый
обязательный маркер снова окажется пустым, гейт упадёт здесь, а не
через месяц на CI с «зелёным» пустым прогоном.

Два механизма разметки учтены явно:

* ``unit`` / ``integration`` назначаются автоматически по пути в
  ``tests/conftest.py`` (авто-разметка);
* ``e2e`` / ``property`` / ``security`` — явной разметкой тестов.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_TESTS = _ROOT / "tests"

# Обязательные маркеры: каждый должен выбирать хотя бы один тест.
REQUIRED_EXPLICIT = ("e2e", "property", "security")
# Маркеры, навешиваемые автоматически по пути внутри tests/conftest.py.
REQUIRED_AUTO = ("unit", "integration")


def _referenced_markers() -> set[str]:
    """Собрать все маркеры, на которые есть явная ссылка в тестах.

    Returns:
        Множество имён маркеров, встречающихся в тестах явно.

    """
    return set(_marker_files())


def _marker_files() -> dict[str, list[str]]:
    """Сопоставить маркер → список тестовых файлов, которые его используют.

    Returns:
        Словарь ``маркер -> [пути]``; пути относительны корню репозитория.

    """
    found: dict[str, list[str]] = {}
    pattern = re.compile(r"pytest\.mark\.([A-Za-z_][A-Za-z0-9_]*)")
    for path in _TESTS.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - защита от гонки с удалением
            continue
        for marker in set(pattern.findall(text)):
            found.setdefault(marker, []).append(str(path.relative_to(_ROOT)))
    return found


# Минимальное число РАЗНЫХ файлов на обязательный маркер. Проверка «маркер
# используется» не ловит потерю одного файла из набора: маркер остаётся
# непустым, а обязательный прогон тихо теряет покрытие. Порог ловит
# массовую потерю, но остаётся ниже фактического числа файлов, чтобы не
# превращаться в хрупкий пересчёт. Для `e2e` набор намеренно мал
# (end-to-end сценарии дорогие), поэтому его порог — 1.
MIN_FILES_PER_MARKER = {"e2e": 1, "property": 3, "security": 3}


class TestRequiredMarkersSelectTests:
    """F-X: обязательные маркеры обязаны что-то выбирать."""

    def test_explicit_markers_are_used_in_test_tree(self) -> None:
        """Каждый явный обязательный маркер упомянут хотя бы в одном тесте."""
        referenced = _referenced_markers()
        missing = [m for m in REQUIRED_EXPLICIT if m not in referenced]
        assert not missing, (
            f"Маркеры {missing} не используются ни в одном тесте: "
            f"`pytest -m <marker>` вернёт EXIT=5 (0 тестов), что по контракту "
            f"аудита означает «вердикта нет», а не PASS. "
            f"Пометьте релевантные тесты `pytestmark = pytest.mark.<marker>`."
        )

    def test_auto_markers_are_applied_by_conftest(self) -> None:
        """Авто-маркеры ``unit``/``integration`` навешиваются conftest'ом.

        Путь в контексте: иначе удаление хука сделает маркер пустым
        бесшумно — ровно тот класс отказа, который чинит F-X.

        """
        conftest = (_TESTS / "conftest.py").read_text(encoding="utf-8")
        for marker in REQUIRED_AUTO:
            assert f"item.add_marker(pytest.mark.{marker})" in conftest, (
                f"tests/conftest.py больше не навешивает маркер `{marker}` "
                f"по пути — `pytest -m {marker}` станет пустым (EXIT=5)"
            )

    @pytest.mark.parametrize("marker", REQUIRED_EXPLICIT)
    def test_marker_is_registered_in_pyproject(self, marker: str) -> None:
        """Явный маркер зарегистрирован — иначе ``--strict-markers`` бьёт по collection."""
        pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert f'"{marker}:' in pyproject or f'"{marker}: ' in pyproject, (
            f"Маркер `{marker}` не зарегистрирован в [tool.pytest.ini_options].markers. "
            f"При --strict-markers это ошибка collection, а без регистрации маркер "
            f"нельзя выбрать вовсе."
        )

    @pytest.mark.parametrize("marker", REQUIRED_EXPLICIT)
    def test_marker_covers_several_files(self, marker: str) -> None:
        """Маркер держится на достаточном числе файлов, а не на одном.

        Проверка «маркер вообще используется» проходит, даже если из
        набора выпали все файлы, кроме последнего: маркер остаётся
        непустым, но обязательный прогон тихо теряет покрытие.

        """
        files = _marker_files().get(marker, [])
        floor = MIN_FILES_PER_MARKER[marker]
        assert len(files) >= floor, (
            f"Маркер `{marker}` помечен только в {len(files)} файл(ах) "
            f"{files}; минимум {floor}. "
            f"Возможно, разметка потеряна при правках — "
            f"`pytest -m {marker}` продолжает проходить, но покрытие упало."
        )
