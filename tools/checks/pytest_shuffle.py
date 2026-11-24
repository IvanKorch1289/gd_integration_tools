"""Pytest-плагин: случайный порядок тестов (эквивалент pytest-randomly).

Зачем
----
``pytest-randomly`` в проекте нет (нет ни в ``pyproject.toml``, ни в
``uv.lock`` — устанавливать новые зависимости без согласования с владельцем
нельзя). Порядок выполнения тестов при этом — известный источник
скрытых зависимостей: тест, проходящий только «по счастливому» порядку,
ломается при перестановке.

Плагин решает эту задачу без новых зависимостей: при заданном
``PYTEST_SHUFFLE_SEED`` коллекция тестов переставляется детерминированно
(seed → одна и та же перестановка), а ``PYTHONHASHSEED`` выравнивается с
тем же seed, чтобы порядок обхода dict'ов тоже был воспроизводим.

Использование::

    PYTHONHASHSEED=101 PYTEST_SHUFFLE_SEED=101 \
        python -m pytest tests/unit -n 4 -p tools.checks.pytest_shuffle

Без ``PYTEST_SHUFFLE_SEED`` плагин — no-op и ничего не меняет.

Аудит 2026-11-23, ЭТАП 2.4.
"""

from __future__ import annotations

import os
import random

#: Переменная окружения с seed'ом перестановки.
SEED_ENV = "PYTEST_SHUFFLE_SEED"


def pytest_collection_modifyitems(items: list[object]) -> None:
    """Переставить собранные тесты детерминированно по seed'у.

    Args:
        items: Список собранных тестов (модифицируется на месте).
    """
    raw_seed = os.environ.get(SEED_ENV)
    if not raw_seed:
        return
    try:
        seed = int(raw_seed)
    except ValueError:
        return
    random.Random(seed).shuffle(items)  # type: ignore[arg-type]
