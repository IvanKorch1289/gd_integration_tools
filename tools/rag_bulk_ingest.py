"""CLI массовой загрузки документов в RAG-индекс (Wave D.2).

Использование::

    python tools/rag_bulk_ingest.py --dir ./docs --collection demo
    python tools/rag_bulk_ingest.py --dir ./docs --collection demo --workers 4
    python tools/rag_bulk_ingest.py --dir ./docs --dry-run

При ``--dry-run`` файлы только перечисляются; ingest не выполняется.

Скрипт не использует FastAPI app — поднимает только ``RAGService`` через
``app.state`` или, если его нет, инстанцирует напрямую с дефолтным
vector store и embedding provider.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("rag_bulk_ingest")


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".json", ".yaml", ".yml"}


def _iter_files(root: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes
    )


async def _build_service() -> object:
    """Поднимает ``RagIngestService`` без HTTP-app."""
    from src.backend.infrastructure.clients.storage.vector_store import (
        get_vector_store,
    )
    from src.backend.services.ai.rag_ingest_service import RagIngestService
    from src.backend.services.ai.rag_service import RAGService

    rag = RAGService(store=get_vector_store())
    return RagIngestService(rag_service=rag, deferred=False)


async def _ingest_batch(
    service: object, files: list[Path], *, collection: str, workers: int
) -> dict[str, int]:
    sem = asyncio.Semaphore(max(1, workers))
    success = 0
    failed = 0

    async def _one(path: Path) -> None:
        nonlocal success, failed
        async with sem:
            data = path.read_bytes()
            try:
                result = await service.ingest(  # type: ignore[attr-defined]
                    [(path.name, data)], collection=collection
                )
                doc_ids = result.get("doc_ids") or []
                errors = result.get("errors") or []
                if errors:
                    failed += 1
                    logger.warning("FAIL %s: %s", path.name, errors)
                else:
                    success += 1
                    logger.info("OK   %s → %s", path.name, doc_ids)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.error("ERR  %s: %s", path.name, exc)

    await asyncio.gather(*(_one(p) for p in files))
    return {"success": success, "failed": failed, "total": len(files)}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rag_bulk_ingest", description="Bulk RAG ingest CLI (Wave D.2)"
    )
    parser.add_argument("--dir", required=True, type=Path, help="Каталог с файлами.")
    parser.add_argument("--collection", default="default", help="Namespace RAG.")
    parser.add_argument(
        "--workers",
        default=4,
        type=int,
        help="Параллелизм (default 4).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать список файлов без ingest.",
    )
    parser.add_argument(
        "--suffixes",
        default=",".join(sorted(SUPPORTED_SUFFIXES)),
        help="Список расширений через запятую.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


async def _amain() -> int:
    args = _parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(message)s")
    root: Path = args.dir
    if not root.exists() or not root.is_dir():
        logger.error("Каталог %s не существует", root)
        return 2
    suffixes = {s if s.startswith(".") else f".{s}" for s in args.suffixes.split(",")}
    files = _iter_files(root, suffixes)
    if not files:
        logger.warning("Файлы с расширениями %s не найдены в %s", suffixes, root)
        return 0
    logger.info("Найдено %d файлов в %s", len(files), root)
    if args.dry_run:
        for p in files:
            print(p)
        return 0

    service = await _build_service()
    summary = await _ingest_batch(
        service, files, collection=args.collection, workers=args.workers
    )
    logger.info("DONE: %s", summary)
    return 0 if summary["failed"] == 0 else 1


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
