"""CI-гейт свежести capability-каталога (ADR-0370, cycle 172).

``docs/reference/capabilities.md`` — генерируемый артефакт
(``make capability-catalog`` → ``tools/export_v11_artefacts.py``).
До cycle 172 файл отставал на 57 строк (51 capability из 108), и
расхождение ловил только pre-commit hook, которого нет в CI-гейтах.

Тест регенерирует каталог во временный каталог и сравнивает с
committed-версией байт-в-байт. Расхождение → падение CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _ROOT / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from export_v11_artefacts import (  # noqa: E402
    CAPABILITIES_MD,
    export_capability_catalog,
)


def test_capability_catalog_is_fresh() -> None:
    """Committed-каталог совпадает с регенерированным из vocabulary."""
    import tempfile

    assert CAPABILITIES_MD.is_file(), f"нет файла {CAPABILITIES_MD}"
    with tempfile.TemporaryDirectory() as tmpdir:
        fresh = export_capability_catalog(Path(tmpdir) / "capabilities.md")
        assert fresh.read_bytes() == CAPABILITIES_MD.read_bytes(), (
            "docs/reference/capabilities.md устарел — "
            "обновить: python tools/export_v11_artefacts.py capability-catalog"
        )


def test_capability_catalog_covers_full_vocabulary() -> None:
    """В каталоге — строки для каждой capability из vocabulary."""
    from src.backend.core.security.capabilities import build_default_vocabulary

    vocabulary = {definition.name for definition in build_default_vocabulary().all()}
    rows = {
        line.split("|")[1].strip().strip("`")
        for line in CAPABILITIES_MD.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    }
    assert rows == vocabulary, (
        f"каталог не совпадает с vocabulary: "
        f"лишние={sorted(rows - vocabulary)}, отсутствуют={sorted(vocabulary - rows)}"
    )
