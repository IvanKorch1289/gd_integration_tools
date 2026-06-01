"""Тесты Wave [wave:s8/k5-wiki-whoosh-extend] расширения WhooshIndex.

* ``_categorize`` — Diátaxis-классификация по path.
* ``search(category=...)`` — фильтр результатов поиска.
* ``.yaml`` файлы (не только ``.md``) попадают в индекс.
* Pre-existing bug-fix: ``_DEFAULT_DOCS_DIR`` указывает на репо-уровень
  (``parents[4]``), а не на ``src/``.
"""

# ruff: noqa: S101

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.services.wiki.whoosh_index import (
    _DEFAULT_DOCS_DIR,
    WhooshIndex,
)


@pytest.mark.parametrize(
    "rel,expected",
    [
        ("docs/tutorials/00_getting_started.md", "tutorial"),
        ("docs/how-to/build-rest.md", "how-to"),
        ("docs/howto/legacy.md", "how-to"),
        ("docs/reference/api.md", "reference"),
        ("docs/explanation/architecture.md", "explanation"),
        ("docs/explanations/old-style.md", "explanation"),
        ("docs/runbooks/secret-rotation.md", "runbook"),
        ("docs/dsl/rule-engine-example.yaml", "dsl"),
        ("docs/adr/0001-foo.md", "reference"),
        ("docs/random/note.md", "other"),
    ],
)
def test_categorize_classifies_by_path(rel: str, expected: str) -> None:
    """``_categorize`` корректно классифицирует пути."""
    assert WhooshIndex._categorize(rel) == expected


def test_default_docs_dir_points_to_repo_root() -> None:
    """``_DEFAULT_DOCS_DIR`` лежит в репо-руте, а не в ``src/``.

    Pre-existing bug: scaffold Wave 10.2 указывал ``parents[3]`` →
    ``src/docs`` (не существует). [wave:s8/k5-wiki-whoosh-extend] правит
    на ``parents[4]`` → ``<repo>/docs``.
    """
    assert _DEFAULT_DOCS_DIR.is_dir(), (
        f"Expected {_DEFAULT_DOCS_DIR} to be an existing directory; "
        "если упало — _DEFAULT_DOCS_DIR разрешается некорректно (regression)."
    )


def test_search_filters_by_category() -> None:
    """search(category='runbook') возвращает только runbook-страницы."""
    with tempfile.TemporaryDirectory() as d:
        idx = WhooshIndex(index_dir=Path(d))
        idx.build(force=True)

        all_hits = idx.search("vault", top=10)
        runbook_hits = idx.search("vault", top=10, category="runbook")

    assert len(all_hits) >= 1, "smoke: должна быть хоть одна страница про vault"
    assert len(runbook_hits) <= len(all_hits)
    assert all(
        "runbook" in h.path.lower() or "/runbooks/" in h.path.lower()
        for h in runbook_hits
    )


def test_yaml_files_are_indexed() -> None:
    """``docs/dsl/*.yaml`` попадают в индекс через _iter_indexable_files."""
    with tempfile.TemporaryDirectory() as d:
        idx = WhooshIndex(index_dir=Path(d))
        idx.build(force=True)
        dsl_hits = idx.search("rule-engine", top=10, category="dsl")

    # rule-engine-example.yaml должен найтись (создан в commit
    # [wave:s8/k3-rule-engine-finale-tests-docs]).
    assert any(h.path.endswith(".yaml") for h in dsl_hits), (
        "DSL .yaml не индексируется"
    )
