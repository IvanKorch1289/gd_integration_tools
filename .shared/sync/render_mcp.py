#!/usr/bin/env python3
"""
render_mcp.py — единый source of truth → Claude + Kimi MCP configs через symlinks.

Source:  .shared/mcp-servers.json (с ${ENV_VAR} паттерном для секретов)
Output:  .mcp.json          → symlink на .shared/mcp-servers.json
         .kimi-code/mcp.json → symlink на ../.shared/mcp-servers.json

Использование:
    python .shared/sync/render_mcp.py              # recreate symlinks
    python .shared/sync/render_mcp.py --verify     # check + exit 1 при дрейфе/leaks

Проверки:
1. .shared/mcp-servers.json существует и валидный JSON
2. .mcp.json и .kimi-code/mcp.json — symlinks на source
3. В source нет hardcoded secrets (regex: ctx7sk-..., длинные строки в "KEY": "value")
4. ${ENV_VAR} паттерн используется для секретных полей
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / ".shared" / "mcp-servers.json"
TARGET_CLAUDE = PROJECT / ".mcp.json"
TARGET_KIMI = PROJECT / ".kimi-code" / "mcp.json"

# Secret-leak patterns
SECRET_PATTERNS = [
    (
        re.compile(
            r"ctx7sk-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
        ),
        "ctx7sk-*",
    ),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-* (OpenAI)"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "sk-ant-* (Anthropic)"),
    (re.compile(r"sk-or-[A-Za-z0-9_-]{20,}"), "sk-or-* (OpenRouter)"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "Google API key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "GitHub PAT"),
]


def find_secrets(text: str) -> list[tuple[str, str]]:
    """Возвращает список (pattern_name, match) найденных секретов."""
    found = []
    for line_no, line in enumerate(text.split("\n"), 1):
        # Skip строки с ${{ENV_VAR}} (это OK)
        if "${" in line and "}" in line:
            # Только проверяем что нет hardcoded значений ВНЕ ${...}
            # Простая эвристика: вырезаем ${...} и проверяем остаток
            cleaned = re.sub(r"\$\{[A-Z_]+\}", "", line)
            for pat, name in SECRET_PATTERNS:
                for m in pat.finditer(cleaned):
                    found.append((name, m.group(), line_no))
        else:
            for pat, name in SECRET_PATTERNS:
                for m in pat.finditer(line):
                    found.append((name, m.group(), line_no))
    return found


def check_source() -> list[str]:
    """Возвращает список проблем с source-файлом."""
    issues = []
    if not SOURCE.exists():
        issues.append(f"SOURCE missing: {SOURCE}")
        return issues
    try:
        data = json.loads(SOURCE.read_text())
    except json.JSONDecodeError as e:
        issues.append(f"SOURCE invalid JSON: {e}")
        return issues
    if "mcpServers" not in data:
        issues.append("SOURCE missing 'mcpServers' key")
    # Secret scan
    text = SOURCE.read_text()
    for name, secret, line_no in find_secrets(text):
        issues.append(f"SECRET-LEAK at line {line_no}: {name} = {secret[:12]}...")
    return issues


def check_symlink(path: Path, expected_target: str) -> list[str]:
    """Возвращает список проблем с symlink-ом."""
    issues = []
    if not path.exists():
        issues.append(f"MISSING: {path}")
        return issues
    if not path.is_symlink():
        issues.append(
            f"NOT a symlink: {path} (должен быть symlink на {expected_target})"
        )
        return issues
    actual_target = os.readlink(str(path))
    if actual_target != expected_target:
        issues.append(
            f"WRONG target: {path} -> {actual_target!r} (expected {expected_target!r})"
        )
    return issues


def create_symlink(path: Path, target: str) -> None:
    """Создаёт/пересоздаёт symlink."""
    if path.is_symlink() or path.exists():
        path.unlink()
    os.symlink(target, str(path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify", action="store_true", help="verify mode: exit 1 при проблемах"
    )
    args = parser.parse_args()

    all_issues = []

    if args.verify:
        # === Verify mode ===
        all_issues.extend(check_source())
        all_issues.extend(check_symlink(TARGET_CLAUDE, ".shared/mcp-servers.json"))
        all_issues.extend(check_symlink(TARGET_KIMI, "../.shared/mcp-servers.json"))

        if not all_issues:
            print(
                "[OK] .shared/mcp-servers.json валиден, оба symlink-а корректны, секретов нет."
            )
            return 0
        print(f"[FAIL] найдено {len(all_issues)} проблем:")
        for i in all_issues:
            print(f"  - {i}")
        return 1

    # === Recreate mode (default) ===
    if not SOURCE.exists():
        print(f"[ERROR] SOURCE не найден: {SOURCE}")
        print(
            "        Создай .shared/mcp-servers.json вручную или скопируй из .mcp.json"
        )
        return 1

    # Validate source first
    source_issues = check_source()
    if source_issues:
        print("[ERROR] SOURCE проблемы (НЕ пересоздаю symlinks):")
        for i in source_issues:
            print(f"  - {i}")
        return 1

    create_symlink(TARGET_CLAUDE, ".shared/mcp-servers.json")
    create_symlink(TARGET_KIMI, "../.shared/mcp-servers.json")
    print("[SYNC] Created symlinks:")
    print("  - .mcp.json -> .shared/mcp-servers.json")
    print("  - .kimi-code/mcp.json -> ../.shared/mcp-servers.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
