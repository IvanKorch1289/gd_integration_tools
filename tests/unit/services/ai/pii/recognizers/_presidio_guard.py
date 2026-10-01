"""Гвард импорта Presidio-распознавателей для окружений без рабочего torch.

Зачем
----
``presidio_analyzer.nlp_engine.device_detector`` на уровне модуля определяет
устройство и **импортирует ``torch``** (``device_detector.py:62 -> _detect``).
В venv может стоять CUDA-сборка torch, а системных библиотек
``libnvrtc.so.*`` / ``libcudart.so.*`` нет. Тогда импорт падает **не**
``ImportError``, а:

    ValueError: libnvrtc.so.*[0-9] not found in the system path [...]

Из-за этого не срабатывает ``pytest.importorskip`` (он ловит только
``ImportError``), и модуль падает на этапе **collection**. А collection-ошибка
блокирует весь прогон pytest целиком (``Interrupted: N errors during collection``),
а не только эти тесты. Именно это наблюдалось в аудите 2026-10-01
(F-W): 3 ошибки сбора блокировали 20643 собранных теста.

Что делает этот модуль
---------------------
``skip_if_presidio_unavailable()`` — импортирует целевой модуль и, если падает
**исключительно** из-за отсутствующих системных библиотек ML-стека, превращает
это в честный ``pytest.skip`` с указанием причины. Любая другая ошибка
(в частности, дефект самого проекта) **пробрасывается дальше** — гвард не должен
прятать настоящие баги.

Замечание: это НЕ маскировка проблемы. Наличие распознавателей по-прежнему
не проверено в этом окружении — честный статус такой среды ``SKIPPED``,
а не ``PASS``.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

#: Подстроки в тексте ошибки, по которым однозначно видно, что дело
#: в отсутствующих системных библиотеках ML-стека, а не в коде проекта.
_ENV_ERROR_MARKERS: tuple[str, ...] = (
    "libnvrtc",
    "libcudart",
    "libcudnn",
    "cudnn",
    "no CUDA GPUs are available",
    "CUDA error",
)


def skip_if_presidio_unavailable(module_path: str) -> ModuleType:
    """Импортировать модуль распознавателей или честно skip'нуть окружение.

    Args:
        module_path: полный путь импорта, например
            ``src.backend.services.ai.pii.recognizers.inn_recognizer``.

    Returns:
        Импортированный модуль.

    Raises:
        pytest.skip: если недоступны системные библиотеки ML-стека
            (libnvrtc/libcudart/CUDA) — окружение, а не дефект проекта.
        Exception: любая другая ошибка импорта пробрасывается без изменений.

    """
    try:
        return importlib.import_module(module_path)
    except (ImportError, OSError, ValueError) as exc:
        text = str(exc)
        lowered = text.lower()
        env_like = any(marker.lower() in lowered for marker in _ENV_ERROR_MARKERS)
        # Признак проблемы окружения: в цепочке участвует torch/ML-стек.
        touches_ml_stack = any(token in text for token in ("torch", "onnx", "nvidia"))
        if env_like or touches_ml_stack:
            pytest.skip(
                f"Presidio ML-стек недоступен в этом окружении "
                f"({type(exc).__name__}: {text[:160]}); "
                f"требуется torch без CUDA либо системные libnvrtc/libcudart. "
                f"Статус окружения — SKIPPED, не PASS.",
                allow_module_level=True,
            )
        raise
