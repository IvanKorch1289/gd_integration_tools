"""S84 W2 codemod: redirect infrastructure.logging imports → core.logging.

V2 P0 #3: 257 файлов импортируют infrastructure.logging.{factory,base,router}
напрямую → layer violations.

Правила:
1. `from src.backend.infrastructure.logging.factory import X` →
   `from src.backend.core.logging import X`
2. `from src.backend.infrastructure.logging import X` →
   `from src.backend.core.logging import X`
3. `from src.backend.infrastructure.logging.base import X` →
   `from src.backend.core.logging import X`
4. `from src.backend.infrastructure.logging.router import X` →
   `from src.backend.core.logging import X`  (для get_router/configure_router/etc)
   OR keep in infrastructure (для SinkRouter/build_sinks_for_profile)
5. infrastructure.logging НЕ УДАЛЯЕТСЯ (backward compat) — только imports меняются.
"""

from __future__ import annotations

import re
from pathlib import Path

# Patterns:
# from src.backend.infrastructure.logging.factory import (a, b, c)
# from src.backend.infrastructure.logging import X, Y
# from src.backend.infrastructure.logging.base import X
# from src.backend.infrastructure.logging.router import X  (только некоторые)

RE_FACTORY = re.compile(
    r"^from src\.backend\.infrastructure\.logging\.factory import (.+)$",
    re.MULTILINE,
)
RE_INFRA_LOGGING = re.compile(
    r"^from src\.backend\.infrastructure\.logging import (.+)$",
    re.MULTILINE,
)
RE_BASE = re.compile(
    r"^from src\.backend\.infrastructure\.logging\.base import (.+)$",
    re.MULTILINE,
)
RE_ROUTER_CORE = re.compile(
    r"^from src\.backend\.infrastructure\.logging\.router import ("
    r"configure_router|get_router|is_router_configured|reset_router|route_to_sinks)(.*)$",
    re.MULTILINE,
)

# Router-only symbols (НЕ переносим в core/logging)
ROUTER_ONLY = {"SinkRouter", "build_sinks_for_profile"}


def transform_imports(text: str) -> tuple[str, int]:
    """Replace infrastructure.logging imports → core.logging.

    Returns (new_text, num_replacements).
    """
    count = 0

    def factory_sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"from src.backend.core.logging import {m.group(1)}"

    def base_sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"from src.backend.core.logging import {m.group(1)}"

    def infra_sub(m: re.Match) -> str:
        # Filter out names that aren't in core.logging
        names_raw = m.group(1)
        # Parse names (handle parens, commas)
        names = [n.strip() for n in names_raw.replace("(", "").replace(")", "").split(",") if n.strip()]
        core_names = []
        kept_infra = []
        for n in names:
            n_clean = n.split(" as ")[0].strip()
            # names that exist in core.logging facade
            if n_clean in {
                "configure_logging", "get_logger", "init_log_sinks",
                "shutdown_log_sinks", "shutdown_logging", "LoggerProtocol",
            }:
                core_names.append(n)
            else:
                kept_infra.append(n)
        result = ""
        if core_names:
            result += f"from src.backend.core.logging import {', '.join(core_names)}\n"
        if kept_infra:
            result += f"from src.backend.infrastructure.logging import {', '.join(kept_infra)}"
        if result:
            nonlocal count
            count += 1
            return result.rstrip()
        return m.group(0)  # nothing changed

    def router_core_sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"from src.backend.core.logging import {m.group(1)}{m.group(2)}"

    text = RE_FACTORY.sub(factory_sub, text)
    text = RE_BASE.sub(base_sub, text)
    text = RE_INFRA_LOGGING.sub(infra_sub, text)
    text = RE_ROUTER_CORE.sub(router_core_sub, text)
    return text, count


def main() -> None:
    src_dir = Path("src")
    files_changed = 0
    total_replacements = 0
    for py_file in src_dir.rglob("*.py"):
        # Skip infrastructure/* — they CAN import from infrastructure.logging
        # (own layer). Only core/services/entrypoints/dsl need core.logging facade.
        if "infrastructure" in py_file.parts:
            continue
        text = py_file.read_text()
        new_text, count = transform_imports(text)
        if count > 0:
            py_file.write_text(new_text)
            files_changed += 1
            total_replacements += count
            print(f"  {py_file}: {count} replacements")
    print(f"\nTotal: {files_changed} files, {total_replacements} replacements")


if __name__ == "__main__":
    main()
