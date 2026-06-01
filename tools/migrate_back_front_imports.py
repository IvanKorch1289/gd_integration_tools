"""One-shot скрипт миграции импортов после R3.10a (back/front split).

Перепишет:
переписать импорты с прежнего плоского ``src.<pkg>`` неймспейса на
двухуровневый ``src.backend.<pkg>`` / ``src.frontend.streamlit_app``.

Идемпотентен: уже-`backend`/`frontend` пути не трогаем.

Применяется ко всем ``*.py`` под ``src/``, ``tests/``, ``tools/``, ``scripts/``
плюс ``pyproject.toml``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Все backend-пакеты + entrypoints + static + main
BACKEND_PACKAGES: tuple[str, ...] = (
    "core",
    "dsl",
    "infrastructure",
    "plugins",
    "schemas",
    "services",
    "tools",
    "utilities",
    "workflows",
    "entrypoints",
    "static",
    "main",
)

# Целевые директории для sweep'а
TARGET_DIRS: tuple[str, ...] = ("src", "tests", "tools", "scripts")

# Дополнительные файлы (не *.py + root-level Python файлы вне TARGET_DIRS)
EXTRA_FILES: tuple[str, ...] = ("pyproject.toml", "manage.py", "alembic.ini")


def build_substitutions() -> list[tuple[re.Pattern[str], str]]:
    """Сборка списка подстановок в правильном порядке (specific → generic)."""
    subs: list[tuple[re.Pattern[str], str]] = []

    # 1. Streamlit (специальный — уходит в frontend)
    subs.append(
        (
            re.compile(r"\bfrom src\.entrypoints\.streamlit_app(?=[\s.])"),
            "from src.frontend.streamlit_app",
        )
    )
    subs.append(
        (
            re.compile(r"\bimport src\.entrypoints\.streamlit_app(?=[\s.,])"),
            "import src.frontend.streamlit_app",
        )
    )
    # 1b. Streamlit string-literals (dot)
    subs.append(
        (
            re.compile(r"""(['"])src\.entrypoints\.streamlit_app(?=[\s.:'"])"""),
            r"\1src.frontend.streamlit_app",
        )
    )
    # 1c. Streamlit path-literals (slash)
    subs.append(
        (
            re.compile(r"""(['"])src/entrypoints/streamlit_app(?=[/'"])"""),
            r"\1src/frontend/streamlit_app",
        )
    )

    # 2. Backend-пакеты — `from`/`import` formы
    for pkg in BACKEND_PACKAGES:
        subs.append(
            (
                re.compile(rf"\bfrom src\.{pkg}(?=[\s.])"),
                f"from src.backend.{pkg}",
            )
        )
        subs.append(
            (
                re.compile(rf"\bimport src\.{pkg}(?=[\s.,])"),
                f"import src.backend.{pkg}",
            )
        )

    # 3. Backend-пакеты — string-literals (dot, для importlib.import_module)
    for pkg in BACKEND_PACKAGES:
        subs.append(
            (
                re.compile(rf"""(['"])src\.{pkg}(?=[\s.:'"])"""),
                rf"\1src.backend.{pkg}",
            )
        )

    # 4. Backend-пакеты — path-literals (slash, для путей файлов)
    for pkg in BACKEND_PACKAGES:
        subs.append(
            (
                re.compile(rf"""(['"])src/{pkg}(?=[/'"])"""),
                rf"\1src/backend/{pkg}",
            )
        )

    return subs


def iter_target_files() -> list[Path]:
    """Сборка списка файлов для обхода."""
    files: list[Path] = []
    for d in TARGET_DIRS:
        root = ROOT / d
        if not root.exists():
            continue
        files.extend(root.rglob("*.py"))
    for f in EXTRA_FILES:
        path = ROOT / f
        if path.exists():
            files.append(path)
    return files


def rewrite_file(path: Path, subs: list[tuple[re.Pattern[str], str]]) -> int:
    """Переписать файл; вернуть число подстановок."""
    text = path.read_text(encoding="utf-8")
    new_text = text
    total = 0
    for pattern, replacement in subs:
        new_text, n = pattern.subn(replacement, new_text)
        total += n
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return total


def main() -> int:
    """Точка входа."""
    subs = build_substitutions()
    files = iter_target_files()
    changed_files = 0
    total_replacements = 0
    for path in files:
        n = rewrite_file(path, subs)
        if n > 0:
            changed_files += 1
            total_replacements += n
    print(
        f"replaced={total_replacements} files={changed_files} "
        f"scanned={len(files)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
