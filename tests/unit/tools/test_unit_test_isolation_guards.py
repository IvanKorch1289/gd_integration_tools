"""Пин-тесты на изоляцию unit-сьютов (tests/unit/conftest.py).

История этих проверок — не «на всякий случай», а конкретный измеренный ущерб
на whole-tree прогоне ``c7a1e9cb2`` (19850 passed / 128 failed / 11 errors):
139 уникальных node-id, из них 129 не воспроизводились изолированно, то есть
это было загрязнение между тестами, а не дефекты продукта.

Два источника, каждый закрыт своей autouse-фикстурой в ``tests/unit/conftest.py``:

1. **Глобальный ``TaskRegistry`` остаётся закрытым.** ``shutdown_all()``
   выставляет ``_closed = True`` навсегда, а ``get_task_registry()`` возвращает
   тот же синглтон. В проде это верно — shutdown зовётся только на выходе
   процесса. В тестах любой прогон lifespan/app-shutdown навсегда портил глобал
   для всего процесса, и каждый последующий ``create_task`` падал с
   «TaskRegistry уже закрыт» — каскадом 31 падения.
   Фикстура: ``_restore_task_registry``.

2. **Подмены ``sys.modules`` не вычищаются на этапе run.** Фронтенд-тесты
   подменяют ``polars``/``streamlit`` голыми ``types.ModuleType``. Хук
   ``pytest_collectstart`` ловит только загрязнение на этапе collection, а pytest
   собирает ВСЕ модули до запуска первого теста — моки, поставленные при
   импорте теста, переживают collection. Хуже того, ``polars`` — опциональный
   extra «dataframes», в дефолтной установке его нет, и подмена делала
   ``pytest.importorskip("polars")`` бесполезным: модуль «находился» в
   ``sys.modules``, поэтому guard срабатывал «успешно» и тест шёл против
   ``MagicMock`` вместо честного skip.
   Фикстура: ``_purge_polluted_modules``.

Тесты ниже пинят И механизм, И его подключение: удаление фикстуры из conftest
ломает проверку ``test_conftest_declares_*``, а поломка самого механизма ломает
функциональные проверки. Зелёный сьют такой дефект сам по себе не показывает —
это ровно тот случай, ради которого фикстуры и пинятся.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from src.backend.core.utils.task_registry import get_task_registry

CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"


async def _noop() -> int:
    """Заглушка фоновой задачи."""
    return 1


# ── Механизм 1: восстановление закрытого глобального TaskRegistry ──


def test_shutdown_all_makes_global_registry_fail_closed() -> None:
    """Продуктовое поведение fail-closed должно ОСТАВАТЬСЯ: closed → RuntimeError.

    Это не баг, а контракт R-V15-11: после ``shutdown_all`` новых задач быть не
    должно. Тест защищает от «лечения» симптома ослаблением этого контракта —
    фикстура обязана восстанавливать реестр явно, а не молча пропускать задачи.
    """

    async def scenario() -> None:
        reg = get_task_registry()
        await reg.shutdown_all(timeout=1.0)
        assert get_task_registry() is reg, "синглтон не должен подменяться"
        coro = _noop()
        try:
            with pytest.raises(RuntimeError, match="уже закрыт"):
                reg.create_task(coro, name="must-not-run")
        finally:
            # create_task отверг корутину до ``loop.create_task``; закрываем
            # явно, иначе pytest ругается «coroutine was never awaited».
            coro.close()

    asyncio.run(scenario())


def test_reset_for_tests_recovers_closed_global_registry() -> None:
    """Восстановление возможно и не требует нового API в продукте.

    ``reset_for_tests()`` присутствовал в ``TaskRegistry`` и до этих правок;
    отсутствовала лишь его вызов из conftest. Проверка фиксирует, что
    фикстура опирается на существующий публичный метод, а не на новый.
    """

    async def scenario() -> int:
        reg = get_task_registry()
        await reg.shutdown_all(timeout=1.0)
        reg.reset_for_tests()
        task = reg.create_task(_noop(), name="after-reset")
        return await task

    assert asyncio.run(scenario()) == 1


# ── Механизм 2: очистка подмен sys.modules на этапе run ──


def test_bare_stub_is_detected_as_polluted() -> None:
    """``_is_polluted_module`` узнаёт ровно ту заглушку, которую ставят тесты.

    Проверяем на настоящем файле теста, чтобы правка фронтенд-теста не могла
    тихо выйти из-под детектора.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import conftest as unit_conftest
    finally:
        sys.path.pop(0)

    from types import ModuleType

    key = "_gd_polluted_probe"
    stub = ModuleType(key)
    sys.modules[key] = stub
    try:
        assert unit_conftest._is_polluted_module(key), (
            "голая заглушка ModuleType обязана опознаваться как polluted"
        )
    finally:
        del sys.modules[key]

    assert not unit_conftest._is_polluted_module("json"), (
        "реальный stdlib-модуль не должен считаться polluted"
    )


def test_cleanup_removes_polars_stub_so_importorskip_honours_absence() -> None:
    """После очистки подменённый ``polars`` вычищается из ``sys.modules``.

    Это и есть исходный дефект: подмена в ``sys.modules`` делала guard
    «успешным», и тест падал вместо skip. Проверка воспроизводит ровно ту
    последовательность, что ломала прогон.

    Исходная формулировка требовала, чтобы после очистки
    ``importorskip('polars')`` поднял Skip. Это верно только пока polars не
    установлен: polars 1.44.2 присутствует в окружении, поэтому после
    очистки ``importorskip`` успешно импортирует настоящий пакет. Поэтому
    проверка разбита на две независимые части: очистка подмены (всегда) и
    поведение importorskip (только когда пакет действительно отсутствует).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import conftest as unit_conftest
    finally:
        sys.path.pop(0)

    from types import ModuleType
    from unittest.mock import MagicMock

    stub = ModuleType("polars")
    stub.DataFrame = MagicMock()

    original = sys.modules.get("polars")
    had_real_polars = original is not None
    sys.modules["polars"] = stub
    try:
        # Пока подмена стоит, polars «есть» — guard не срабатывает.
        pytest.importorskip("polars")  # noqa: B018 - проверяем сам факт импорта
        unit_conftest._cleanup_polluted_modules()
        if not had_real_polars:
            assert "polars" not in sys.modules, "cleanup must purge the stub"
            if importlib.util.find_spec("polars") is not None:
                pytest.skip("polars установлен — importorskip поднимет настоящий пакет")
            with pytest.raises(pytest.skip.Exception):
                pytest.importorskip("polars")
    finally:
        if original is None:
            sys.modules.pop("polars", None)
        else:
            sys.modules["polars"] = original


# ── Подключение: обе фикстуры объявлены autouse в conftest ──


def _autouse_fixture_names() -> set[str]:
    """Имена autouse-фикстур, объявленных в ``tests/unit/conftest.py``."""
    tree = ast.parse(CONFTEST_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            is_fixture = (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "fixture"
            ) or (isinstance(dec, ast.Attribute) and dec.attr == "fixture")
            if not is_fixture:
                continue
            if isinstance(dec, ast.Call):
                autouse = next(
                    (
                        kw
                        for kw in dec.keywords
                        if kw.arg == "autouse"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ),
                    None,
                )
                if autouse is not None:
                    names.add(node.name)
    return names


def test_conftest_declares_task_registry_guard() -> None:
    """Фикстура восстановления TaskRegistry должна существовать и быть autouse.

    Без неё каскад из 31 падения вернётся, а зелёный сьют этого не покажет.
    """
    assert "_restore_task_registry" in _autouse_fixture_names(), (
        "tests/unit/conftest.py потерял autouse-фикстуру _restore_task_registry: "
        "закрытый глобальный TaskRegistry снова утечёт в следующие сьюты"
    )


def test_conftest_declares_polluted_module_runtime_guard() -> None:
    """Runtime-очистка подмен должна быть autouse, а не только collectstart-хук.

    Хук ``pytest_collectstart`` ловит только этап collection. Моки, которые
    фронтенд-тесты ставят при импорте, к моменту выполнения уже собраны и
    должны быть вычищены вокруг каждого теста.
    """
    assert "_purge_polluted_modules" in _autouse_fixture_names(), (
        "tests/unit/conftest.py потерял autouse-фикстуру _purge_polluted_modules: "
        "подмены sys.modules снова переживут collection"
    )


def test_polars_and_streamlit_are_known_polluted_keys() -> None:
    """``polars`` и ``streamlit`` обязаны быть в ``_POLLUTED_MODULE_KEYS``.

    Проверено на реальном поведении: ``test_converters.py``::
    ``TestConversionStrategies::test_dict_to_csv`` сам по себе даёт SKIPPED, но
    сразу после ``test_91_operational_costs_imports`` — FAILED, потому что тот
    подставляет ``sys.modules['polars'] = ModuleType('polars')`` и
    ``importorskip`` видит мок вместо отсутствующего пакета.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import conftest as unit_conftest
    finally:
        sys.path.pop(0)

    assert "polars" in unit_conftest._POLLUTED_MODULE_KEYS
    assert "streamlit" in unit_conftest._POLLUTED_MODULE_KEYS


def test_conftest_keeps_pre_existing_isolation_guards() -> None:
    """Новые фикстуры не должны вытеснить уже принятые guard'ы того же conftest.

    ``_restore_di_overrides`` и ``_restore_workflow_registry`` закрывали свои
    собственные утечки; молчаливое удаление любого из них — регресс.
    """
    names = _autouse_fixture_names()
    for guard in ("_restore_di_overrides", "_restore_workflow_registry"):
        assert guard in names, f"tests/unit/conftest.py потерял {guard}"
