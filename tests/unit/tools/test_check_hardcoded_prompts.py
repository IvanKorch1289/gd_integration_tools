"""Unit-тесты AST-checker hardcoded prompts (Wave 13 GAP-AI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.checks.check_hardcoded_prompts import (
    PROMPT_BUILDER_CALLS,
    PROMPT_KWARGS,
    Finding,
    _const_str_value,
    _load_allowlist,
    main,
    scan_file,
    scan_paths,
)


def _write(tmp_path: Path, name: str, src: str) -> Path:
    path = tmp_path / name
    path.write_text(src, encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# scan_file: kwarg detection
# ──────────────────────────────────────────────────────────────────────────────


def test_kwarg_long_literal_detected(tmp_path: Path) -> None:
    """Литерал > 50 символов в system_prompt → finding."""
    src = "agent.invoke(\n    system_prompt='" + "А" * 60 + "',\n)\n"
    path = _write(tmp_path, "a.py", src)
    findings = scan_file(path)
    assert len(findings) == 1
    assert findings[0].kind == "hardcoded-prompt-kwarg"
    assert "system_prompt" in findings[0].where


def test_kwarg_short_literal_ignored(tmp_path: Path) -> None:
    """Литерал короче min_length — не finding."""
    src = "agent.invoke(system_prompt='короткий')\n"
    path = _write(tmp_path, "a.py", src)
    assert scan_file(path) == []


def test_kwarg_non_target_name_ignored(tmp_path: Path) -> None:
    """Имя kwarg вне PROMPT_KWARGS — не finding."""
    src = "agent.invoke(label='" + "x" * 80 + "')\n"
    path = _write(tmp_path, "a.py", src)
    assert scan_file(path) == []


def test_kwarg_variable_value_ignored(tmp_path: Path) -> None:
    """Если значение — variable (не литерал) — не finding."""
    src = "agent.invoke(system_prompt=PROMPT)\n"
    path = _write(tmp_path, "a.py", src)
    assert scan_file(path) == []


def test_kwarg_min_length_override(tmp_path: Path) -> None:
    """--min-length поднимает порог триггера."""
    src = "agent.invoke(prompt='" + "A" * 60 + "')\n"
    path = _write(tmp_path, "a.py", src)
    assert scan_file(path, min_length=50)  # есть
    assert scan_file(path, min_length=100) == []  # нет при пороге 100


# ──────────────────────────────────────────────────────────────────────────────
# scan_file: positional builder detection
# ──────────────────────────────────────────────────────────────────────────────


def test_system_message_positional_detected(tmp_path: Path) -> None:
    """SystemMessage('...long string...') → finding."""
    src = "SystemMessage('" + "B" * 60 + "')\n"
    path = _write(tmp_path, "a.py", src)
    findings = scan_file(path)
    assert len(findings) == 1
    assert findings[0].kind == "hardcoded-prompt-positional"
    assert "SystemMessage" in findings[0].where


def test_chat_prompt_template_from_template(tmp_path: Path) -> None:
    """ChatPromptTemplate.from_template('...') → finding."""
    src = "ChatPromptTemplate.from_template('" + "C" * 60 + "')\n"
    path = _write(tmp_path, "a.py", src)
    findings = scan_file(path)
    assert findings
    assert findings[0].where.startswith("позиционный")


# ──────────────────────────────────────────────────────────────────────────────
# scan_file: JoinedStr / multiline
# ──────────────────────────────────────────────────────────────────────────────


def test_joined_str_constant_parts(tmp_path: Path) -> None:
    """f-строка с constant parts склеивается для проверки длины."""
    body = "A" * 70
    src = "agent.invoke(prompt=f'" + body + "')\n"
    path = _write(tmp_path, "a.py", src)
    assert len(scan_file(path)) == 1


def test_implicit_concatenation(tmp_path: Path) -> None:
    """'aaa' 'bbb' — один Constant в AST после parsing."""
    src = "agent.invoke(prompt='" + "x" * 30 + "' '" + "y" * 30 + "')\n"
    path = _write(tmp_path, "a.py", src)
    assert len(scan_file(path)) == 1


# ──────────────────────────────────────────────────────────────────────────────
# scan_paths + allowlist
# ──────────────────────────────────────────────────────────────────────────────


def test_scan_paths_directory_recursion(tmp_path: Path) -> None:
    """scan_paths рекурсивно обходит каталог."""
    (tmp_path / "pkg").mkdir()
    _write(tmp_path / "pkg", "a.py", "agent.invoke(system_prompt='" + "x" * 60 + "')\n")
    _write(tmp_path / "pkg", "b.py", "agent.invoke(label='ok')\n")
    findings = scan_paths([tmp_path / "pkg"])
    assert len(findings) == 1
    assert findings[0].path.name == "a.py"


def test_allowlist_excludes_glob(tmp_path: Path) -> None:
    """Файлы из allowlist игнорируются."""
    _write(tmp_path, "ignored.py", "agent.invoke(prompt='" + "z" * 60 + "')\n")
    findings = scan_paths([tmp_path], allowlist=["**/ignored.py"])
    assert findings == []


def test_default_excludes_tests(tmp_path: Path) -> None:
    """Стандартные excludes отсекают tests/."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write(tests_dir, "test_x.py", "agent.invoke(prompt='" + "z" * 60 + "')\n")
    findings = scan_paths([tmp_path])
    assert findings == []


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def test_const_str_value_basic() -> None:
    import ast

    tree = ast.parse("'hello'", mode="eval")
    assert _const_str_value(tree.body) == "hello"


def test_const_str_value_non_str_returns_none() -> None:
    import ast

    tree = ast.parse("42", mode="eval")
    assert _const_str_value(tree.body) is None


def test_load_allowlist_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "allow.txt"
    path.write_text("# comment\n\n**/x.py\n  \n**/y.py\n", encoding="utf-8")
    assert _load_allowlist(path) == ["**/x.py", "**/y.py"]


def test_load_allowlist_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_allowlist(tmp_path / "absent.txt") == []


def test_finding_format() -> None:
    f = Finding(
        path=Path("a.py"),
        lineno=10,
        col_offset=4,
        kind="hardcoded-prompt-kwarg",
        where="kwarg `prompt`",
        snippet="hello world",
    )
    formatted = f.format()
    assert "a.py:10:4" in formatted
    assert "[hardcoded-prompt-kwarg]" in formatted


def test_prompt_kwargs_constants() -> None:
    """Регрессионная проверка состава PROMPT_KWARGS."""
    assert "system_prompt" in PROMPT_KWARGS
    assert "prompt" in PROMPT_KWARGS
    assert "instructions" in PROMPT_KWARGS
    assert "SystemMessage" in PROMPT_BUILDER_CALLS
    assert "ChatPromptTemplate" in PROMPT_BUILDER_CALLS


# ──────────────────────────────────────────────────────────────────────────────
# CLI main()
# ──────────────────────────────────────────────────────────────────────────────


def test_cli_exit_zero_when_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чистый каталог → exit=0."""
    _write(tmp_path, "ok.py", "agent.invoke(label='ok')\n")
    rc = main(["--root", str(tmp_path), "--allowlist", "/nonexistent"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


def test_cli_exit_one_when_strict_and_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Findings + --strict → exit=1."""
    _write(tmp_path, "bad.py", "agent.invoke(system_prompt='" + "x" * 60 + "')\n")
    rc = main(["--root", str(tmp_path), "--allowlist", "/nonexistent", "--strict"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FOUND" in err


def test_cli_exit_zero_when_warn_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Findings без --strict → exit=0 (warn-only)."""
    _write(tmp_path, "bad.py", "agent.invoke(system_prompt='" + "x" * 60 + "')\n")
    rc = main(["--root", str(tmp_path), "--allowlist", "/nonexistent"])
    assert rc == 0


def test_scan_file_handles_syntax_error(tmp_path: Path) -> None:
    """SyntaxError → пустой список (а не падение)."""
    _write(tmp_path, "broken.py", "def x(:\n")
    assert scan_file(tmp_path / "broken.py") == []
