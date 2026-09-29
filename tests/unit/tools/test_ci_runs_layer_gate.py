"""Регрессия: `make ci` обязан запускать гейт слоёв (ADR-001).

`make ci` долгое время не вызывал `check_layers.py` вообще: цепочка заканчивалась
на `test-collection-check` (`pytest --co`). Из-за этого регрессия слоёв
проходила незамеченной — коммит с двумя новыми нарушениями `services → dsl`
был закоммичен с зелёным `make ci`, и нашлась только чтением самого гейта.

Проверка намеренно читает определение цели, а не запускает всю пайплайн-линию:
`make ci` занимает минуты, а достаточно убедиться, что шаг присутствует.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINES = REPO_ROOT / "make" / "pipelines.mk"


def _ci_recipe() -> list[str]:
    """Шаги цели `ci` (строки с $(MAKE)/$(UV_RUN) до следующей цели)."""
    lines = PIPELINES.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("ci:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("##", "#")):
            break
        if line.strip() and not line.strip().startswith("#"):
            body.append(line.strip())
    return body


def test_ci_target_exists() -> None:
    """Цель ci объявлена в pipelines.mk."""
    assert PIPELINES.exists()
    assert any(ln.startswith("ci:") for ln in PIPELINES.read_text().splitlines())


def test_ci_runs_the_layer_gate() -> None:
    """`make ci` обязан вызывать шаг слоёв.

    Именно этот шаг ловит новые нарушения импортов между слоями; без него
    зелёный `make ci` ничего не говорит об архитектуре.
    """
    recipe = _ci_recipe()
    assert any("layers" in step for step in recipe), (
        "цель ci не вызывает шаг слоёв — регрессия services→dsl пройдёт "
        f"незамеченной. Текущие шаги: {recipe}"
    )


def test_ci_layer_step_is_ordered_before_success_echo() -> None:
    """Шаг слоёв стоит до терминального $(SUCCESS), иначе он не влияет на exit code."""
    recipe = _ci_recipe()
    layers_idx = next(i for i, s in enumerate(recipe) if "layers" in s)
    success_idx = next(
        (i for i, s in enumerate(recipe) if "$(SUCCESS)" in s), len(recipe)
    )
    assert layers_idx < success_idx, (
        f"шаг слоёв (позиция {layers_idx}) должен идти раньше $(SUCCESS) "
        f"(позиция {success_idx})"
    )


def test_layer_target_invoke_script_is_the_real_gate() -> None:
    """Цель `layers` действительно зовёт check_layers.py, а не заглушку."""
    runtime_mk = (REPO_ROOT / "make" / "runtime.mk").read_text(encoding="utf-8")
    match = re.search(r"^layers:.*?\n((?:\t.*\n)+)", runtime_mk, re.MULTILINE)
    assert match, "цель layers не найдена в make/runtime.mk"
    assert "tools/check_layers.py" in match.group(1), (
        "цель layers не запускает tools/check_layers.py — шаг в ci будет декоративным"
    )


def test_ci_still_does_not_execute_tests() -> None:
    """Фиксирует известный долг: ci проверяет коллекцию, а не выполнение.

    Тест назван явно «долг», потому что это не PASS: `pytest --co` доказывает,
    что тесты импортируются, но не что они проходят. Когда цепочка начнёт
    реально выполнять тесты, этот тест упадёт — и это правильно, его нужно будет
    удалить осознанно.
    """
    recipe = _ci_recipe()
    assert any("test-collection-check" in step for step in recipe)
    assert not any(re.search(r"\bpytest\b(?!.*--co)", step) for step in recipe), (
        "если make ci начал выполнять тесты, обновите статус CI в "
        "PRODUCTION_READINESS_CURRENT.md и удалите этот тест"
    )
