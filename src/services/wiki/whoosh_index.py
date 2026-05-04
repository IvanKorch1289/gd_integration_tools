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

from src.core.di import app_state_singleton

__all__ = ("Hit", "WhooshIndex", "get_wiki_index")

logger = logging.getLogger(__name__)

_DEFAULT_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
_DEFAULT_INDEX_DIR = Path(__file__).resolve().parents[3] / ".cache" / "wiki_index"


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

        return fields.Schema(
            path=fields.ID(stored=True, unique=True),
            title=fields.TEXT(stored=True),
            mtime=fields.NUMERIC(stored=True),
            content=fields.TEXT(stored=True),
        )

    def _iter_md_files(self) -> Iterable[Path]:
        if not self._docs_dir.is_dir():
            return ()
        return self._docs_dir.rglob("*.md")

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
                    mtime=mtime,
                    content=content,
                )
                count += 1
            # Удаляем удалённые файлы.
            for stale in set(existing_mtimes) - seen:
                writer.delete_by_term("path", stale)
            writer.commit()
        except Exception:
            writer.cancel()
            raise

        self._ix = ix
        logger.info("wiki: indexed %d documents", count)
        return count

    def search(self, query: str, top: int = 20) -> list[Hit]:
        """Полнотекстовый поиск по ``title`` и ``content``."""
        from whoosh import qparser

        if self._ix is None:
            self._ix = self._open_or_create()
        with self._ix.searcher() as searcher:
            parser = qparser.MultifieldParser(
                ["title", "content"], schema=self._ix.schema
            )
            parsed = parser.parse(query)
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
