"""Wave F.7 — генератор post-wave memory note (Roadmap V10 #13).

Создаёт скелет файла в auto-memory сессии Claude:
``~/.claude/projects/<repo-slug>/memory/feedback_<name>.md`` и добавляет
запись в ``MEMORY.md`` (если ещё не добавлена).

Использование:

  python tools/wave_memory.py --name invoker_consolidation
  python tools/wave_memory.py --name async_db_only --type feedback
  python tools/wave_memory.py --name logging_choice --type project

После генерации файл нужно дописать руками — это скелет с метаданными.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Путь к auto-memory: ~/.claude/projects/<slug>/memory/
HOME = Path.home()
PROJECT_SLUG = (
    "-" + str(PROJECT_ROOT.resolve())
    .lstrip("/")
    .replace("/", "-")
    .replace("_", "-")
)
MEMORY_DIR = HOME / ".claude" / "projects" / PROJECT_SLUG / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"

VALID_TYPES = ("feedback", "project", "user", "reference")


def _slugify(name: str) -> str:
    """Безопасное имя файла: [a-z0-9_]."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    if not s:
        raise ValueError("name пустой после нормализации")
    return s


def _build_skeleton(name: str, mem_type: str, title: str | None) -> str:
    """Шаблон с frontmatter — имя/описание/тип + 3 секции под заполнение."""
    title = title or name.replace("_", " ").capitalize()
    description = (
        "TODO: одно предложение, специфичное и полезное для будущих сессий"
    )
    if mem_type == "feedback":
        body = (
            "**Правило**: TODO — кратко, как делать.\n\n"
            "**Why:** TODO — обоснование (incident / измерение / "
            "продакшен-фидбек).\n\n"
            "**How to apply:** TODO — когда применять и где.\n"
        )
    elif mem_type == "project":
        body = (
            "**Факт**: TODO.\n\n"
            "**Why:** TODO — мотивация / стейкхолдер / срок.\n\n"
            "**How to apply:** TODO — как использовать в решениях.\n"
        )
    else:
        body = "TODO: содержательная сводка.\n"

    return (
        f"---\n"
        f"name: {title}\n"
        f"description: {description}\n"
        f"type: {mem_type}\n"
        f"---\n\n"
        f"{body}"
    )


def _ensure_index_entry(file_name: str, title: str) -> bool:
    """Добавляет строку в MEMORY.md если её нет; возвращает True при изменении."""
    if not MEMORY_INDEX.exists():
        MEMORY_INDEX.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_INDEX.write_text("", encoding="utf-8")
    content = MEMORY_INDEX.read_text(encoding="utf-8")
    if file_name in content:
        return False
    line = f"- [{title}]({file_name}) — TODO: однострочное описание\n"
    if content and not content.endswith("\n"):
        content += "\n"
    MEMORY_INDEX.write_text(content + line, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", required=True, help="Идентификатор memory (snake_case)."
    )
    parser.add_argument(
        "--type",
        default="feedback",
        choices=VALID_TYPES,
        help=f"Тип memory (один из: {', '.join(VALID_TYPES)}).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Человекочитаемый заголовок (по умолчанию из --name).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующий файл.",
    )
    args = parser.parse_args(argv)

    slug = _slugify(args.name)
    file_name = f"{args.type}_{slug}.md" if args.type != "user" else f"user_{slug}.md"
    file_path = MEMORY_DIR / file_name

    if file_path.exists() and not args.force:
        print(
            f"[wave-memory] {file_path} уже существует. Используйте --force.",
            file=sys.stderr,
        )
        return 1

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    skeleton = _build_skeleton(slug, args.type, args.title)
    file_path.write_text(skeleton, encoding="utf-8")
    title = args.title or slug.replace("_", " ").capitalize()
    indexed = _ensure_index_entry(file_name, title)

    print(f"[wave-memory] создан: {file_path}")
    if indexed:
        print(f"[wave-memory] MEMORY.md обновлён ({file_name})")
    else:
        print("[wave-memory] запись в MEMORY.md уже была")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
