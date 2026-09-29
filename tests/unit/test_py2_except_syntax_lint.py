"""Regression test: семантика ``except X, Y:`` на Python 3.14 (PEP 758).

История. Тест на запрет «Py2-синтаксиса» утверждал, что ``except X, Y:``
в Python 3.14 парсится как ``except X as Y:`` — «ловит только первый тип,
остальные игнорируются», то есть семантически сломан. Это ложное
утверждение, проверенное фактически, а не по документации:

* ``ast.parse`` даёт ``ast.ExceptHandler.type`` типа ``ast.Tuple`` —
  то есть ровно ``except (X, Y):``;
* поведенчески ``except ValueError, TypeError:`` ловит ОБА типа
  (подброшенный ``TypeError`` перехватывается).

Это официальный синтаксис Python 3.14 — PEP 758 «Allow except and
except* expressions without parentheses». До 3.14 такая запись была
``SyntaxError``, а не «молчаливым» поведением.

Следствие: запрет был основан на неверной посылке, сам тест нарушал его
собственное правило (``except UnicodeDecodeError, OSError:`` в
``_scan_for_py2_except``), и он блокировал CI на валидном коде — более 20
вхождений по src/ и tests/.

Вместо запрета здесь закреплена фактическая семантика: если будущая версия
Python изменит разбор ``except X, Y:``, тест это покажет, а не промолчит.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _handlers(src: str) -> list[ast.ExceptHandler]:
    """Все ExceptHandler в исходнике."""
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ExceptHandler)]


def test_unparenthesized_except_parses_as_tuple() -> None:
    """PEP 758: ``except X, Y:`` разбирается в кортеж, а не в ``as``-связывание."""
    handler = _handlers("try:\n    pass\nexcept ValueError, TypeError:\n    pass\n")[0]
    assert isinstance(handler.type, ast.Tuple), (
        "PEP 758 ожидает ast.Tuple для `except X, Y:`; получено "
        f"{type(handler.type).__name__}. Значит, семантика разбора изменилась — "
        "пересмотрите запрет/миграцию."
    )
    assert handler.name is None, (
        "PEP 758 не создаёт as-связывание; handler.name должен быть None"
    )


def test_unparenthesized_except_catches_every_listed_type() -> None:
    """Поведенческая проверка: ловятся ВСЕ перечисленные типы, а не только первый.

    Это опровергает исходную посылку запрета («ловит только первый тип,
    остальные игнорируются»). Если бы это было так, ``TypeError`` проскочил бы
    мимо ``except ValueError, TypeError:``.
    """
    caught: list[str] = []
    for exc_name in ("ValueError", "TypeError"):
        src = (
            "try:\n"
            f"    raise {exc_name}()\n"
            "except ValueError, TypeError:\n"
            "    caught.append('both')\n"
        )
        exec(compile(src, "<pep758-check>", "exec"), {"caught": caught})  # noqa: S102
    assert caught == ["both", "both"], (
        f"ожидался перехват обоих типов, получено {caught} — семантика "
        "``except X, Y:`` изменилась, пересмотрите миграцию"
    )


def test_pep758_syntax_is_widely_used_and_intentional() -> None:
    """Фиксирует, что PEP 758 синтаксис — норма проекта, а не остаток мусора.

    Считается по src/backend и tests. Порог намеренно низкий: он защищает от
    «случайно вернули запрет и массово переписали код в tuple-форму», а не
    фиксирует точное число (которое законно меняется).
    """
    pattern = "except"
    count = 0
    for root in (REPO_ROOT / "src" / "backend", REPO_ROOT / "tests"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.lstrip()
                if not stripped.startswith(pattern):
                    continue
                segment = stripped[len(pattern) :]
                if ":" in segment and "," in segment.split(":", 1)[0]:
                    if "(" not in segment.split(":", 1)[0]:
                        count += 1
    assert count >= 10, (
        f"найдено всего {count} непустых `except X, Y:`. Если запрет всё же "
        "вернулся и код переписан — обновите этот тест и миграционную "
        "документацию явно, а не молча."
    )


@pytest.mark.unit
def test_src_backend_parses_under_project_interpreter() -> None:
    """Все файлы src/backend парсятся тем интерпретатором, на котором идёт CI.

    Это полезная часть старого запрета: ловит реально сломанный синтаксис,
    но без ложных срабатываний на валидном PEP 758.
    """
    src_backend = REPO_ROOT / "src" / "backend"
    if not src_backend.exists():
        pytest.skip("src/backend/ not present")
    broken: list[str] = []
    for path in sorted(src_backend.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            broken.append(f"{path.relative_to(REPO_ROOT)}:{exc.lineno}: {exc.msg}")
    assert not broken, "файлы не парсятся:\n" + "\n".join(broken[:20])
