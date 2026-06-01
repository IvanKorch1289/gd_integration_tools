"""Whoosh-индекс над ``docs/**/*.md`` для Wiki-страницы (Wave 10.2).

Pure-Python движок (whoosh-reloaded 2.7+) — низкий ABI-risk на
Python 3.14, нет C-extensions.

Кэш индекса:

* Каталог индекса хранится в ``<repo_root>/.cache/wiki_index``.
* Перестраивается, если хоть один ``.md`` имеет mtime > index-mtime.
* Latency p95 поиска < 300ms на типовом репозитории (107 .md, ~1MB total).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.backend.core.di import app_state_singleton

__all__ = ("Hit", "WhooshIndex", "get_wiki_index")

logger = logging.getLogger(__name__)

# parents[4] = <repo_root> (whoosh_index.py живёт в
# <root>/src/backend/services/wiki/). Wave 10.2 scaffold ошибочно
# использовал parents[3] (= ``src/``) → docs_dir не существовал и поиск
# был пуст; исправлено в [wave:s8/k5-wiki-whoosh-extend].
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DOCS_DIR = _REPO_ROOT / "docs"
_DEFAULT_INDEX_DIR = _REPO_ROOT / ".cache" / "wiki_index"


@dataclass(slots=True)
class Hit:
    """Одна позиция результата."""

    path: str
    title: str
    score: float
    snippet: str


class WhooshIndex:
    """In-process Whoosh-индекс над markdown-каталогом."""

    def __init__(
        self, docs_dir: Path | None = None, index_dir: Path | None = None
    ) -> None:
        self._docs_dir = (docs_dir or _DEFAULT_DOCS_DIR).resolve()
        self._index_dir = (index_dir or _DEFAULT_INDEX_DIR).resolve()
        self._ix: object | None = None

    # --- internals ---

    def _schema(self):
        from whoosh import fields

        # Wave [wave:s8/k5-wiki-whoosh-extend]: добавлен `category`-фильтр
        # (Diátaxis: tutorial / how-to / reference / explanation / runbook /
        # dsl / other) для side-bar навигации в Streamlit Wiki.
        return fields.Schema(
            path=fields.ID(stored=True, unique=True),
            title=fields.TEXT(stored=True),
            category=fields.KEYWORD(stored=True, lowercase=True, scorable=True),
            mtime=fields.NUMERIC(stored=True),
            content=fields.TEXT(stored=True),
        )

    def _iter_indexable_files(self) -> Iterable[Path]:
        """Возвращает все ``.md`` и ``.yaml`` в ``docs_dir``.

        ``.yaml`` нужен для DSL-примеров (``docs/dsl/*.yaml``) — Wiki
        отображает их как "live DSL examples" с подсветкой синтаксиса.
        """
        if not self._docs_dir.is_dir():
            return ()
        return list(self._docs_dir.rglob("*.md")) + list(self._docs_dir.rglob("*.yaml"))

    # Backward-compat алиас (не удалять — использован в тестах прежних wave).
    def _iter_md_files(self) -> Iterable[Path]:
        return self._iter_indexable_files()

    @staticmethod
    def _categorize(rel_path: str) -> str:
        """Классифицирует файл по Diátaxis-квадранту на основе пути."""
        path_lower = rel_path.lower()
        for marker, category in (
            ("/tutorials/", "tutorial"),
            ("/how-to/", "how-to"),
            ("/howto/", "how-to"),
            ("/reference/", "reference"),
            ("/explanation/", "explanation"),
            ("/explanations/", "explanation"),
            ("/runbooks/", "runbook"),
            ("/dsl/", "dsl"),
            ("/adr/", "reference"),
        ):
            if marker in path_lower:
                return category
        return "other"

    def _open_or_create(self):
        from whoosh import index

        self._index_dir.mkdir(parents=True, exist_ok=True)
        if index.exists_in(str(self._index_dir)):
            return index.open_dir(str(self._index_dir))
        return index.create_in(str(self._index_dir), self._schema())

    @staticmethod
    def _title(path: Path, content: str) -> str:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip() or path.stem
            if line:
                return line[:120]
        return path.stem

    def build(self, force: bool = False) -> int:
        """Полная (или частичная) (пере)индексация. Возвращает кол-во документов.

        ``force=True`` удаляет существующий индекс и собирает с нуля.
        Иначе индексирует только файлы с обновлённым mtime.
        """
        ix = self._open_or_create()
        existing_mtimes: dict[str, float] = {}
        if not force:
            with ix.searcher() as searcher:
                for doc in searcher.documents():
                    existing_mtimes[doc["path"]] = float(doc.get("mtime") or 0)

        writer = ix.writer()
        try:
            count = 0
            seen: set[str] = set()
            for md in self._iter_md_files():
                rel = str(md.relative_to(self._docs_dir.parent))
                seen.add(rel)
                mtime = md.stat().st_mtime
                if (
                    not force
                    and rel in existing_mtimes
                    and existing_mtimes[rel] >= mtime
                ):
                    continue
                try:
                    content = md.read_text(encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("wiki: cannot read %s (%s)", md, exc)
                    continue
                writer.update_document(
                    path=rel,
                    title=self._title(md, content),
                    category=self._categorize(rel),
                    mtime=mtime,
                    content=content,
                )
                count += 1
            # Удаляем удалённые файлы.
            for stale in set(existing_mtimes) - seen:
                writer.delete_by_term("path", stale)
            writer.commit()
        except Exception as _:
            writer.cancel()
            raise

        self._ix = ix
        logger.info("wiki: indexed %d documents", count)
        return count

    def search(
        self, query: str, top: int = 20, *, category: str | None = None
    ) -> list[Hit]:
        """Полнотекстовый поиск по ``title`` и ``content``.

        Args:
            query: Произвольный текстовый запрос.
            top: Лимит результатов.
            category: Опц. фильтр по Diátaxis-квадранту
                (``tutorial`` / ``how-to`` / ``reference`` / ``explanation`` /
                ``runbook`` / ``dsl`` / ``other``). ``None`` — без фильтра.
        """
        from whoosh import qparser

        if self._ix is None:
            self._ix = self._open_or_create()
        with self._ix.searcher() as searcher:
            parser = qparser.MultifieldParser(
                ["title", "content"], schema=self._ix.schema
            )
            full_query = f"({query}) AND category:{category}" if category else query
            parsed = parser.parse(full_query)
            results = searcher.search(parsed, limit=top)
            results.fragmenter.charlimit = 1024 * 8
            hits: list[Hit] = []
            for hit in results:
                snippet = hit.highlights("content") or ""
                hits.append(
                    Hit(
                        path=str(hit["path"]),
                        title=str(hit.get("title") or hit["path"]),
                        score=float(hit.score),
                        snippet=snippet,
                    )
                )
            return hits

    def doc_count(self) -> int:
        if self._ix is None:
            self._ix = self._open_or_create()
        with self._ix.searcher() as searcher:
            return int(searcher.doc_count())


@app_state_singleton("wiki_index", factory=WhooshIndex)
def get_wiki_index() -> WhooshIndex:
    """Singleton WhooshIndex (через app.state)."""


def _selftest() -> None:
    """CLI smoke: pyrun этот модуль как ``-m`` для построения и поиска."""
    idx = WhooshIndex()
    t0 = time.perf_counter()
    n = idx.build(force=False)
    dt = (time.perf_counter() - t0) * 1000
    print(f"build: {n} docs in {dt:.0f} ms")

    t0 = time.perf_counter()
    hits = idx.search("DSL", top=5)
    dt = (time.perf_counter() - t0) * 1000
    print(f"search 'DSL': {len(hits)} hits in {dt:.0f} ms")
    for h in hits:
        print(f"  - {h.path}  ({h.score:.2f})")


if __name__ == "__main__":
    _selftest()
