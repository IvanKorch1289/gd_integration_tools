"""S181 P0-#8: regression тесты для ``check_tool_allowed`` glob semantics.

Подтверждает, что whitelist/blacklist поддерживают case-sensitive glob
через :func:`fnmatch.fnmatchcase`. До фикса: ``whitelist=["db.*"]`` л
итерально не содержал ``db.read`` (поведение: deny). После фикса:
``whitelist=["db.*"]`` glob-матчит ``db.read``/``db.write`` (поведение: allow).

Все примеры взяты из docstring ``tools_policy.py:65-67`` — теперь
соответствуют реальной семантике.
"""

from __future__ import annotations

from src.backend.core.ai.policy.enforcer.tools_policy import check_tool_allowed
from src.backend.core.ai.policy.spec import ToolsSpec


def test_glob_whitelist_allows_matching_pattern() -> None:
    """Whitelist ``db.*`` — tool ``db.read`` allowed через glob."""
    spec = ToolsSpec(whitelist=["db.*"])
    assert check_tool_allowed("db.read", spec) is True


def test_glob_whitelist_allows_nested_namespace() -> None:
    """Whitelist ``db.*`` — tool ``db.write.batch`` тоже matches."""
    spec = ToolsSpec(whitelist=["db.*"])
    assert check_tool_allowed("db.write.batch", spec) is True


def test_glob_whitelist_rejects_non_matching() -> None:
    """Whitelist ``db.*`` — tool ``fs.write`` denied (different namespace)."""
    spec = ToolsSpec(whitelist=["db.*"])
    assert check_tool_allowed("fs.write", spec) is False


def test_glob_blacklist_blocks_matching_pattern() -> None:
    """Blacklist ``fs.*`` — tool ``fs.write`` blocked через glob."""
    spec = ToolsSpec(blacklist=["fs.*"])
    assert check_tool_allowed("fs.write", spec) is False


def test_glob_blacklist_blocks_nested_namespace() -> None:
    """Blacklist ``fs.*`` — tool ``fs.read.batch`` тоже blocked."""
    spec = ToolsSpec(blacklist=["fs.*"])
    assert check_tool_allowed("fs.read.batch", spec) is False


def test_glob_blacklist_allows_non_matching() -> None:
    """Blacklist ``fs.*`` — tool ``db.read`` НЕ blocked (different ns)."""
    spec = ToolsSpec(blacklist=["fs.*"])
    assert check_tool_allowed("db.read", spec) is True


def test_backward_compat_literal_name_still_matches() -> None:
    """Whitelist с буквальным именем (без glob-символов) — exact match works."""
    spec = ToolsSpec(whitelist=["db.read"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("db.write", spec) is False


def test_glob_case_sensitive() -> None:
    """Glob-матчинг case-sensitive (``DB.read`` ≠ ``db.*`` для lowercase-only)."""
    spec = ToolsSpec(whitelist=["db.*"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("DB.read", spec) is False


def test_glob_question_mark_wildcard() -> None:
    """Single-char wildcard ``?`` works через fnmatch."""
    spec = ToolsSpec(whitelist=["db.rea?"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("db.reax", spec) is True
    assert check_tool_allowed("db.write", spec) is False


def test_glob_brackets_range() -> None:
    """Character class ``[seq]`` works через fnmatch."""
    spec = ToolsSpec(whitelist=["db.[rw]ead"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("db.wead", spec) is True
    assert check_tool_allowed("db.tead", spec) is False


def test_no_whitelist_no_blacklist_allows_all() -> None:
    """Backward-compat: empty whitelist + empty blacklist → allow any tool."""
    spec = ToolsSpec()
    assert check_tool_allowed("any.tool", spec) is True


def test_whitelist_and_blacklist_combined_glob() -> None:
    """Blacklist globals выигрывает над whitelist (explicit denylist)."""
    spec = ToolsSpec(whitelist=["db.*"], blacklist=["db.write"])
    # db.read: glob-match whitelist, не в blacklist → allow
    assert check_tool_allowed("db.read", spec) is True
    # db.write: glob-match whitelist, но в blacklist → deny
    assert check_tool_allowed("db.write", spec) is False
    # fs.write: не в whitelist → deny
    assert check_tool_allowed("fs.write", spec) is False
