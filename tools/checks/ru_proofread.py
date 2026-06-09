"""CLI / API ru-language proofreader для Markdown в ``docs/``.

Wave: ``[wave:s8/k5-ru-proofreader]``. Использует
``language-tool-python>=2.8`` (опц. extra ``docs-ru``) для grammar check
русскоязычной документации. Fail-soft: если library не установлена —
Streamlit-кнопка показывает helpful warning, CI пропускает gate.

Использование (CLI)::

    python tools/checks/ru_proofread.py docs/
    python tools/checks/ru_proofread.py docs/ --limit 20  # ограничить файлы

Output формат: ``<path>:<line>: <issue>``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

__all__ = ("proofread_docs", "main")


def _iter_md_files(root: Path, limit: int | None = None) -> Iterable[Path]:
    """Yields Markdown-файлы под ``root`` (опц. с лимитом для smoke-проверок)."""
    seen = 0
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            yield path
            seen += 1
            if limit is not None and seen >= limit:
                return


def proofread_docs(
    root: Path, *, limit_files: int | None = None, language: str = "ru-RU"
) -> list[str]:
    """Проверяет ``*.md`` файлы под ``root`` через LanguageTool.

    Args:
        root: Каталог с Markdown-файлами.
        limit_files: Опц. лимит файлов (для CI-smoke / Streamlit).
        language: Код языка LanguageTool (``ru-RU`` для русского).

    Returns:
        Список строк формата ``<rel_path>:<line>: <короткое описание>``.

    Raises:
        ImportError: ``language-tool-python`` не установлен — вызывающий
            должен решить, эскалировать или fail-soft.
    """
    import language_tool_python  # type: ignore[import-not-found]

    tool = language_tool_python.LanguageTool(language)
    issues: list[str] = []
    try:
        for md in _iter_md_files(root, limit=limit_files):
            try:
                content = md.read_text(encoding="utf-8")
            except OSError:
                continue
            matches = tool.check(content)
            for m in matches:
                # Приближённый расчёт номера строки по offset.
                line_no = content.count("\n", 0, m.offset) + 1
                rel = md.relative_to(root.parent)
                short = (m.message or "").splitlines()[0][:120]
                issues.append(f"{rel}:{line_no}: {short}")
    finally:
        try:
            tool.close()
        except Exception:  # noqa: BLE001, S110  # silent fallback (best-effort cleanup, non-critical)
            pass
    return issues


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.

    Returns:
        ``0`` если замечаний нет; ``1`` иначе.
    """
    parser = argparse.ArgumentParser(
        description="Russian-language proofreader для docs/*.md."
    )
    parser.add_argument("root", type=Path, help="Корневой каталог (обычно docs/)")
    parser.add_argument("--limit", type=int, default=None, help="Опц. лимит файлов")
    parser.add_argument(
        "--language", default="ru-RU", help="Код LanguageTool (default ru-RU)"
    )
    args = parser.parse_args(argv)

    try:
        issues = proofread_docs(
            args.root, limit_files=args.limit, language=args.language
        )
    except ImportError:
        print(
            "ERROR: language-tool-python не установлен. "
            "Установите: uv sync --extra docs-ru",
            file=sys.stderr,
        )
        return 2

    for issue in issues:
        print(issue)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
