"""Bootstrap для unit-тестов DSL EIP (Wave 18.U3).

Решает pre-existing блокеры тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``;
   ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень репозитория.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog через ``graypy``. Через env ``LOG_HOST=""``
   отключаем graylog handler.
3. В ряде модулей ``src/dsl`` присутствует Python-2 синтаксис
   (``except A, B:``), который ломает import. Патчим строкой/AST до
   импорта и регистрируем модули в ``sys.modules`` напрямую, не модифицируя
   исходники.

Патчатся:
    * ``src.dsl.engine.processors.ai`` — line 197
    * ``src.dsl.engine.processors.eip.windowed_dedup`` — line 61
    * ``src.dsl.builder`` — line 2341

После этого можно безопасно импортировать ``RouteBuilder`` и
``load_pipeline_from_yaml`` для round-trip-тестов.
"""

from __future__ import annotations

import os
import re
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# (1) ROOT_DIR -> корень репозитория
# ---------------------------------------------------------------------------
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[4]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

# ---------------------------------------------------------------------------
# (2) Отключаем graylog (LoggerManager) до импорта settings
# ---------------------------------------------------------------------------
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")


# ---------------------------------------------------------------------------
# (3) Патчим pre-existing python-2 syntax в исходниках через runtime-load
# ---------------------------------------------------------------------------

_PY2_EXCEPT_RE = re.compile(
    r"except\s+([A-Za-z_][A-Za-z0-9_.]*)\s*,\s*([A-Za-z_][A-Za-z0-9_.]*)\s*:"
)


def _load_patched(qualname: str, source_path: Path) -> types.ModuleType:
    """Загружает Python-модуль с runtime-патчем py2-except синтаксиса."""
    src = source_path.read_text(encoding="utf-8")
    fixed = _PY2_EXCEPT_RE.sub(r"except (\1, \2):", src)
    mod = types.ModuleType(qualname)
    mod.__file__ = str(source_path)
    sys.modules[qualname] = mod
    exec(compile(fixed, str(source_path), "exec"), mod.__dict__)  # noqa: S102
    return mod


def _bootstrap_dsl_imports() -> None:
    """Регистрирует исправленные модули перед прочими импортами DSL."""
    if "src.dsl.builder" in sys.modules and not sys.modules["src.dsl.builder"].__dict__.get(
        "_TEST_PATCHED"
    ):
        # Already imported by some other test path — skip; нет смысла re-patch'ить.
        return

    proc_path = _REPO_ROOT / "src" / "dsl" / "engine" / "processors"

    # Стаб для пакета processors — чтобы submodule-импорты не триггерили
    # broken __init__.py до того, как мы пропатчим ai.py.
    if "src.dsl.engine.processors" not in sys.modules:
        pkg = types.ModuleType("src.dsl.engine.processors")
        pkg.__path__ = [str(proc_path)]
        sys.modules["src.dsl.engine.processors"] = pkg
    else:
        pkg = sys.modules["src.dsl.engine.processors"]

    # Патчим broken submodule (ai.py).
    _load_patched("src.dsl.engine.processors.ai", proc_path / "ai.py")

    # Патчим broken submodule (windowed_dedup.py).
    _load_patched(
        "src.dsl.engine.processors.eip.windowed_dedup",
        proc_path / "eip" / "windowed_dedup.py",
    )

    # Теперь можно выполнить настоящий __init__.py пакета processors —
    # все его импорты теперь либо clean, либо стаб'нуты.
    init_path = proc_path / "__init__.py"
    init_src = init_path.read_text(encoding="utf-8")
    exec(  # noqa: S102
        compile(init_src, str(init_path), "exec"),
        pkg.__dict__,
    )

    # Патчим builder.py.
    _load_patched("src.dsl.builder", _REPO_ROOT / "src" / "dsl" / "builder.py")
    setattr(sys.modules["src.dsl.builder"], "_TEST_PATCHED", True)


_bootstrap_dsl_imports()
