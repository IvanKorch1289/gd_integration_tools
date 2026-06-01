"""Batch-утилита для очистки sys.path imports из pages."""

from __future__ import annotations

import re
from pathlib import Path

PAGES = Path("src/frontend/streamlit_app/pages")

# Паттерн для _root варианта
_RE_ROOT = re.compile(
    r"\nimport sys\n(?=\nimport streamlit)",
    re.MULTILINE,
)
_RE_ROOT_PATH = re.compile(
    r"\nfrom pathlib import Path\n",
    re.MULTILINE,
)
_RE_ROOT_BLOCK = re.compile(
    r"\n_root = Path\(__file__\)\.resolve\(\)\.parents\[4\]\n"
    r"if str\(_root\) not in sys\.path:\n"
    r"    sys\.path\.insert\(0, str\(_root\)\)\n",
    re.MULTILINE,
)

# Паттерн для _project_root варианта
_RE_PROJ_BLOCK = re.compile(
    r"\n_project_root = Path\(__file__\)\.resolve\(\)\.parents\[4\]\n"
    r"if str\(_project_root\) not in sys\.path:\n"
    r"    sys\.path\.insert\(0, str\(_project_root\)\)\n",
    re.MULTILINE,
)


def clean_file(path: Path) -> bool:
    """Удалить sys.path блок и неиспользуемые imports."""
    text = path.read_text()
    original = text

    text = _RE_ROOT_BLOCK.sub("\n", text)
    text = _RE_PROJ_BLOCK.sub("\n", text)
    # Удалить "import sys" если теперь не используется
    text = _RE_ROOT.sub("\n", text)
    # Удалить "from pathlib import Path" если теперь не используется
    text = _RE_ROOT_PATH.sub("\n", text)

    if text != original:
        path.write_text(text)
        return True
    return False


def main() -> None:
    modified = []
    for path in sorted(PAGES.glob("*.py")):
        if path.name in ("00_Home.py", "31_DSL_Visual_Editor.py"):
            continue
        if clean_file(path):
            modified.append(path.name)

    print(f"Cleaned {len(modified)} files:")
    for f in modified:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
