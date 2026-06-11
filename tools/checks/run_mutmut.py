#!/usr/bin/env python3
"""Wrapper для запуска mutmut в gd_integration_tools.

Проблемы, которые решает wrapper:
1. mutmut 3.x жёстко кодирует отбрасывание префикса ``src.`` из имён модулей
   (get_mutant_name) и падает с AssertionError при trampoline-hit для модулей,
   начинающихся с ``src.``. В проекте ``src`` — это реальное имя пакета.
2. mutmut копирует в ``mutants/`` только мутируемые файлы; ``mutants/src/``
   получается неполной копией, и импорты из ``mutants/`` ломаются.
3. _resolve_repo_root() находит ``mutants/pyproject.toml`` и считает repo root
   ``mutants/`` вместо проектного корня — config loader не находит YAML-профили.

Решение:
- Патчим установленный mutmut в venv (idempotent).
- Делаем ``mutants/src/`` полной копией ``src/`` (rsync).
- Выставляем ``GD_REPO_ROOT`` (поддержка добавлена в config_loader.py).
- Запускаем ``mutmut run`` с переданными аргументами.

Использование::

    uv run python tools/checks/run_mutmut.py [-- mutmut-args]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _patch_mutmut() -> None:
    """Idempotent patch mutmut в venv для поддержки пакета ``src``."""
    venv = Path(sys.executable).parent.parent
    main_py = (
        venv
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "mutmut"
        / "__main__.py"
    )
    format_utils_py = (
        venv
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "mutmut"
        / "utils"
        / "format_utils.py"
    )

    # Patch 1: убрать assert на src. в record_trampoline_hit
    if main_py.exists():
        content = main_py.read_text()
        old = 'assert not name.startswith("src."), "Failed trampoline hit. Module name starts with `src.`, which is invalid"'
        new = "pass  # src. assertion removed for gd_integration_tools (src is real package name)"
        if old in content:
            main_py.write_text(content.replace(old, new))
            print("[run_mutmut] Patched mutmut/__main__.py (src. assertion)")

    # Patch 2: не отбрасывать src. из module_name в get_mutant_name
    if format_utils_py.exists():
        content = format_utils_py.read_text()
        old = '    module_name = strip_prefix(module_name, prefix="src.")\n'
        new = '    # gd_integration_tools: src. is the actual package name, not a directory prefix.\n    # module_name = strip_prefix(module_name, prefix="src.")\n'
        if old in content:
            format_utils_py.write_text(content.replace(old, new))
            print("[run_mutmut] Patched mutmut/utils/format_utils.py (src. strip)")


def _sync_mutants_src() -> None:
    """Синхронизировать ``mutants/src/`` с полным деревом ``src/``."""
    repo_root = Path(__file__).resolve().parents[2]
    mutants_src = repo_root / "mutants" / "src"
    src_dir = repo_root / "src"
    if not src_dir.exists():
        raise RuntimeError(f"Source dir not found: {src_dir}")
    mutants_src.mkdir(parents=True, exist_ok=True)
    # rsync с сохранением прав и удалением лишнего
    subprocess.run(  # noqa: S603  # dev-tool wrapper: фиксированная команда
        ["rsync", "-a", "--delete", f"{src_dir}/", f"{mutants_src}/"],  # noqa: S607  # dev-tool: rsync — PATH binary
        check=True,
    )
    print("[run_mutmut] Synced mutants/src/ from src/")


def main() -> int:
    _patch_mutmut()
    _sync_mutants_src()

    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["GD_REPO_ROOT"] = str(repo_root)

    mutmut_args = ["mutmut", "run"] + sys.argv[1:]
    print(f"[run_mutmut] Executing: {' '.join(mutmut_args)}")
    return subprocess.run(  # noqa: S603  # dev-tool wrapper: args от пользователя CLI
        mutmut_args, cwd=repo_root, env=env
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
