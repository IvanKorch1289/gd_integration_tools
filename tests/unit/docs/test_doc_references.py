"""TDD: DocPathValidator (S171 M26-P0-2, D288).

Pattern (D288, Ponytail): AST-based regex validator.
Validates src/backend/ + extensions/ paths cited in docs/.

Рэтчет по долгу документации: текущие недокументированные пути заморожены в
``.baselines/doc-references.baseline.json``; гейт падает только на НОВЫХ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BASELINE_FILE = _PROJECT_ROOT / ".baselines" / "doc-references.baseline.json"


def _load_baseline() -> tuple[set[str], set[str]]:
    """Прочитать замороженный долг: (src_backend, extensions)."""
    assert _BASELINE_FILE.exists(), (
        f"Baseline документации не найден: {_BASELINE_FILE}. "
        "Создайте его осознанно, зафиксировав текущее состояние."
    )
    data = json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
    return set(data["src_backend"]), set(data["extensions"])


KNOWN_UNDOCUMENTED_BACKEND, KNOWN_UNDOCUMENTED_EXTENSIONS = _load_baseline()


@pytest.fixture(scope="module")
def doc_validator():
    from src.backend.core.utils.doc_path_validator import DocPathValidator

    return DocPathValidator(_PROJECT_ROOT)


class TestDocReferences:
    def test_validator_instantiable(self, doc_validator) -> None:
        assert doc_validator is not None

    def test_collect_referenced_paths(self, doc_validator) -> None:
        result = doc_validator.collect_referenced_paths()
        assert "src_backend" in result
        assert "extensions" in result
        assert len(result["src_backend"]) > 0
        assert isinstance(result["src_backend"], set)

    def test_find_missing_returns_dict(self, doc_validator) -> None:
        result = doc_validator.find_missing()
        assert isinstance(result, dict)

    def test_no_unexpected_missing_src_backend(self, doc_validator) -> None:
        """Нет НОВЫх недокументированных модулей (рэтчет по baseline).

        Раньше здесь стоял ``assert all(m.startswith(<13 префиксов>))`` при
        пустом ``adr_planned``, а список префиксов не содержал ``core/`` —
        поэтому падал на легитимных ссылках вроде
        ``core/di/composition_root.py``. Рядом лежал мёртвый
        list-comprehension, результат которого отбрасывался.

        ``find_missing`` возвращает пути, **упомянутые в документации**, но
        отсутствующие на диске — висячие ссылки, а не «недокументированные
        модули»: документация указывает на код, который переехал, был
        переименован или удалён, и читатель получает по ссылке 404.

        Текущий долг заморожен в ``.baselines/doc-references.baseline.json``;
        гейт падает только на НОВЫХ ссылках. Набор может уменьшаться (ссылка
        исправлена), но не должен расти — тот же принцип, что у layer-baseline.
        """
        missing = set(doc_validator.find_missing().get("src_backend", []))
        unexpected = sorted(missing - KNOWN_UNDOCUMENTED_BACKEND)
        assert not unexpected, (
            "Новые битые ссылки из docs на несуществующие модули src/backend — "
            "исправьте или удалите ссылку, либо осознанно обновите baseline: "
            f"{unexpected} "
            f"(всего в baseline: {len(KNOWN_UNDOCUMENTED_BACKEND)})"
        )

    def test_no_unexpected_missing_extensions(self, doc_validator) -> None:
        """Нет НОВЫх недокументированных расширений (рэтчет по baseline)."""
        missing = set(doc_validator.find_missing().get("extensions", []))
        unexpected = sorted(missing - KNOWN_UNDOCUMENTED_EXTENSIONS)
        assert not unexpected, (
            "Новые битые ссылки из docs на несуществующие расширения — исправьте "
            f"или удалите ссылку, либо обновите baseline: {unexpected}"
        )

    def test_validator_class_is_importable(self) -> None:
        from src.backend.core.utils.doc_path_validator import DocPathValidator

        assert hasattr(DocPathValidator, "collect_referenced_paths")
        assert hasattr(DocPathValidator, "find_missing")
