"""ErrorExplainer — context-aware diagnostic helper (Wave 2 DX #55).

Pure-Python implementation:
- Parse traceback → extract file:line, function name, exception type.
- Heuristic-based suggestion для common exception types.
- Report format для UI/logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("ErrorExplanation", "ErrorExplainer", "explain_error", "get_error_explainer")


# Mapping common exception types → suggestions.
_EXCEPTION_HINTS: dict[str, list[str]] = {
    "KeyError": [
        "Check that the key exists in dict/object before access.",
        "Use dict.get(key, default) для safe access.",
        "Verify upstream code provides expected keys.",
    ],
    "ValueError": [
        "Check function arguments — invalid value passed.",
        "Validate input before calling function.",
        "Check schema validation result.",
    ],
    "TypeError": [
        "Object has wrong type for operation.",
        "Check argument types via type hints.",
        "Use isinstance() для runtime check.",
    ],
    "AttributeError": [
        "Object does not have this attribute.",
        "Check imports and __init__ order.",
        "Verify mock object setup in tests.",
    ],
    "ConnectionError": [
        "Check network connectivity.",
        "Verify host/port configuration.",
        "Check firewall rules.",
        "Use retry policy с exponential backoff.",
    ],
    "TimeoutError": [
        "Operation exceeded timeout.",
        "Increase timeout if expected.",
        "Check downstream latency.",
    ],
    "ImportError": [
        "Module not installed.",
        "Check pyproject.toml dependencies.",
        "Run uv sync / pip install.",
    ],
    "FileNotFoundError": [
        "Check file path.",
        "Verify working directory.",
        "Check file permissions.",
    ],
    "PermissionError": [
        "Insufficient permissions.",
        "Run as correct user (sudo/chown).",
        "Check file/directory mode bits.",
    ],
}


@dataclass(slots=True)
class ErrorExplanation:
    """Context-aware error explanation."""

    exception_type: str
    exception_message: str
    source_file: str = ""
    source_line: int = 0
    function_name: str = ""
    hints: list[str] = field(default_factory=list)
    suggested_commands: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line summary."""
        loc = f"{self.source_file}:{self.source_line}"
        return f"{self.exception_type}: {self.exception_message} at {loc}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "function_name": self.function_name,
            "hints": list(self.hints),
            "suggested_commands": list(self.suggested_commands),
            "related_files": list(self.related_files),
            "summary": self.summary,
        }


class ErrorExplainer:
    """Diagnostic helper для exceptions."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()

    def explain(self, exc: BaseException, *, tb: Any = None) -> ErrorExplanation:
        """Generate explanation для exception."""
        # Use provided traceback or extract from exception.
        if tb is None:
            tb = exc.__traceback__

        # Parse source location.
        source_file, source_line, function_name = self._extract_source(tb)
        exc_type = type(exc).__name__
        exc_message = str(exc)

        # Get hints based on exception type.
        hints = list(
            _EXCEPTION_HINTS.get(
                exc_type,
                [
                    "Check exception traceback for root cause.",
                    "Use logging for context.",
                    "Review related tests for expected behavior.",
                ],
            )
        )

        # Suggest reproduction commands.
        commands = self._suggest_commands(exc_type, source_file)

        # Find related files via grep (if source_file exists).
        related = self._find_related_files(source_file)

        return ErrorExplanation(
            exception_type=exc_type,
            exception_message=exc_message,
            source_file=source_file,
            source_line=source_line,
            function_name=function_name,
            hints=hints,
            suggested_commands=commands,
            related_files=related,
        )

    def _extract_source(self, tb: Any) -> tuple[str, int, str]:
        """Extract source file, line, function name из traceback."""
        if tb is None:
            return ("", 0, "")
        # Get last frame (innermost).
        frames = []
        current = tb
        while current is not None:
            frames.append(current)
            current = current.tb_next
        if not frames:
            return ("", 0, "")
        last_frame = frames[-1]
        # Python 3.13+ uses tb_frame; older uses f_code.
        if hasattr(last_frame, "tb_frame") and last_frame.tb_frame is not None:
            f = last_frame.tb_frame
            file_path = f.f_code.co_filename or ""
            line_no = last_frame.tb_lineno or 0
            func_name = f.f_code.co_name or ""
        else:
            file_path = getattr(last_frame, "f_code", None)
            if file_path is not None:
                file_path = file_path.co_filename or ""
            else:
                file_path = ""
            line_no = last_frame.f_lineno or 0
            func_name = ""
        # Make path relative to project_root.
        try:
            rel_path = str(Path(file_path).relative_to(self._project_root))
        except ValueError:
            rel_path = file_path
        return (rel_path, line_no, func_name)

    def _suggest_commands(self, exc_type: str, source_file: str) -> list[str]:
        """Suggest reproduction commands."""
        cmds: list[str] = []
        if source_file:
            # Suggest test command for the file.
            cmds.append(f"pytest {source_file} -v --tb=short")
            cmds.append(f"grep -n '{exc_type}' {source_file}")
        cmds.append(f"make reproduce-error EXC='{exc_type}'")
        return cmds

    def _find_related_files(self, source_file: str) -> list[str]:
        """Find files related to source (tests, ADRs)."""
        if not source_file:
            return []
        related: list[str] = []
        path = Path(source_file)
        # Test file: foo.py → test_foo.py.
        stem = path.stem
        if not stem.startswith("test_"):
            test_path = path.parent / f"test_{stem}.py"
            if (path.parent / f"test_{stem}.py").exists():
                related.append(str(test_path))
        # ADR/runbook directory.
        adr_dir = self._project_root / "docs" / "adr"
        if adr_dir.exists():
            # Find ADRs that mention similar terms.
            for adr in adr_dir.glob("*.md"):
                if adr.name in source_file or stem in adr.name:
                    related.append(f"docs/adr/{adr.name}")
                    break
        return related[:5]


def explain_error(
    exc: BaseException, *, project_root: Path | None = None
) -> ErrorExplanation:
    """Convenience function: explain exception."""
    expl = ErrorExplainer(project_root=project_root)
    return expl.explain(exc)


_explainer: ErrorExplainer | None = None


def get_error_explainer() -> ErrorExplainer:
    global _explainer
    if _explainer is None:
        _explainer = ErrorExplainer()
    return _explainer


def reset_error_explainer() -> None:
    global _explainer
    _explainer = None
