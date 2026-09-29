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


def test_ci_executes_the_unit_suite() -> None:
    """`make ci` обязан реально выполнять тесты, а не только собирать их.

    Долг закрыт 2026-09-29. До этого `ci` заканчивалась на `pytest --co` и
    выполняла 715 тестов из 20 780 (3.4%) — только подмножество
    `check-ai-safety`. Остальные 96.6% не запускались никогда, и именно там
    лежали неисполняемые дефекты: merge-конфликты в
    `ops/compose/docker-compose.light.yml` и дрейф `runAsUser` в k8s-манифестах.
    """
    recipe = _ci_recipe()
    assert any("unit-tests" in step for step in recipe), (
        f"цель ci не вызывает unit-tests — тесты снова не будут выполняться. "
        f"Текущие шаги: {recipe}"
    )
    assert not any(
        step for step in recipe if re.search(r"pytest\b.*--co", step)
    ), "pytest --co в самой цели ci больше не нужен — шаг вынесен в отдельную цель"


def test_unit_tests_step_precedes_success_echo() -> None:
    """Шаг unit-tests стоит до терминального $(SUCCESS), иначе он не влияет на exit code."""
    recipe = _ci_recipe()
    unit_idx = next(i for i, s in enumerate(recipe) if "unit-tests" in s)
    success_idx = next(
        (i for i, s in enumerate(recipe) if "$(SUCCESS)" in s), len(recipe)
    )
    assert unit_idx < success_idx, (
        f"шаг unit-tests (позиция {unit_idx}) должен идти раньше $(SUCCESS) "
        f"(позиция {success_idx})"
    )


def test_unit_tests_target_actually_runs_pytest_on_unit_suite() -> None:
    """Цель `unit-tests` действительно зовёт pytest по tests/unit, а не заглушку."""
    text = PIPELINES.read_text(encoding="utf-8")
    match = re.search(r"^unit-tests:.*?\n((?:\t.*\n)+)", text, re.MULTILINE)
    assert match, "цель unit-tests не найдена в make/pipelines.mk"
    body = match.group(1)
    pytest_lines = [ln for ln in body.splitlines() if "pytest" in ln]
    assert pytest_lines, "цель unit-tests не запускает pytest — шаг в ci будет декоративным"
    assert any("tests/unit" in ln for ln in pytest_lines), (
        f"pytest вызывается не по tests/unit: {pytest_lines}. Подмена на tests/ "
        "затянет в CI интеграционные тесты, которым нужны PG/Redis/MinIO"
    )
    # --timeout может лежать на строке-продолжении (обратный слэш), поэтому
    # здесь проверяется весь рецепт, а не строка с pytest.
    assert "--timeout=" in body, (
        f"unit-tests обязан передавать --timeout. Рецепт: {body!r}. Без "
        "pytest-timeout зависший тест подвесит пайплайн без верхней границы"
    )


def test_unit_tests_timeout_is_defined_and_not_disabled() -> None:
    """UNIT_TEST_TIMEOUT определён в Makefile и не обнулён.

    Обнуление (0) отключает таймер и возвращает поведение, ради которого
    шаг добавлен, поэтому значение проверяется явно.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^UNIT_TEST_TIMEOUT\s*\??=\s*(\S+)", makefile, re.MULTILINE)
    assert match, "UNIT_TEST_TIMEOUT не определён в Makefile"
    assert int(match.group(1)) > 0, (
        f"UNIT_TEST_TIMEOUT={match.group(1)} отключает таймер pytest-timeout"
    )
