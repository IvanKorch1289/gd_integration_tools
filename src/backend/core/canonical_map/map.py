"""CanonicalMap — module placement registry + import-linter rules."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "CanonicalMap",
    "ImportRule",
    "LayerRule",
    "PathEntry",
    "get_canonical_map",
)


@dataclass(slots=True)
class PathEntry:
    """Canonical placement одного модуля/пакета."""

    path: str  # e.g., "src/backend/core/idempotency"
    responsibility: str  # human-readable description
    public_api: list[str] = field(default_factory=list)  # exported symbols
    layer: str = ""  # "core", "infrastructure", "extensions", "services"
    forbidden_imports: list[str] = field(default_factory=list)  # layer-level rules
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportRule:
    """Запрет import pattern → target pattern."""

    pattern: str  # regex для source module path
    forbidden_imports: list[str] = field(default_factory=list)  # regex для forbidden
    reason: str = ""


@dataclass(slots=True)
class LayerRule:
    """Описание архитектурного слоя."""

    name: str  # "core", "infrastructure", "extensions", "services", "dsl"
    allowed_imports: list[str] = field(default_factory=list)  # layers
    forbidden_imports: list[str] = field(default_factory=list)  # layers
    description: str = ""


class CanonicalMap:
    """Registry canonical placements + import rules."""

    def __init__(self) -> None:
        self._paths: dict[str, PathEntry] = {}
        self._import_rules: list[ImportRule] = []
        self._layers: dict[str, LayerRule] = {}

    def register_path(
        self,
        *,
        path: str,
        responsibility: str,
        public_api: list[str] | None = None,
        layer: str = "",
        forbidden_imports: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register canonical path."""
        entry = PathEntry(
            path=path,
            responsibility=responsibility,
            public_api=list(public_api or []),
            layer=layer,
            forbidden_imports=list(forbidden_imports or []),
            tags=list(tags or []),
        )
        self._paths[path] = entry

    def add_rule(self, rule: ImportRule) -> None:
        """Add import rule."""
        self._import_rules.append(rule)

    def add_layer(self, layer: LayerRule) -> None:
        """Add layer rule."""
        self._layers[layer.name] = layer

    def get_path(self, path: str) -> PathEntry | None:
        """Get entry по path или None."""
        return self._paths.get(path)

    def list_paths(
        self,
        *,
        layer: str | None = None,
        tag: str | None = None,
    ) -> list[PathEntry]:
        """List paths с фильтрами."""
        result = list(self._paths.values())
        if layer is not None:
            result = [p for p in result if p.layer == layer]
        if tag is not None:
            result = [p for p in result if tag in p.tags]
        return result

    def get_layer(self, name: str) -> LayerRule | None:
        return self._layers.get(name)

    def check_import(
        self, source_module: str, target_module: str
    ) -> list[str]:
        """Check если ``source_module`` нарушает rules при import ``target_module``.

        Returns:
            List of violation messages (empty if OK).

        """
        violations: list[str] = []
        # Match source pattern.
        for rule in self._import_rules:
            if not re.search(rule.pattern, source_module):
                continue
            for forbidden in rule.forbidden_imports:
                if re.search(forbidden, target_module):
                    msg = (
                        f"{source_module} → {target_module}: "
                        f"forbidden import (rule: {rule.pattern} → {forbidden})"
                    )
                    if rule.reason:
                        msg += f" — {rule.reason}"
                    violations.append(msg)
        return violations

    def check_imports(
        self, *, project_root: str | None = None
    ) -> list[str]:
        """Scan project imports и detect violations.

        Args:
            project_root: project root для сканирования (default = current).

        Returns:
            List of violation messages.

        """
        import ast

        root = Path(project_root) if project_root else Path.cwd()
        violations: list[str] = []
        # Walk all .py files.
        src_root = root / "src" / "backend"
        if not src_root.exists():
            return violations
        for py_file in src_root.rglob("*.py"):
            if "__pycache__" in py_file.parts or "/.venv/" in str(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            # Source module = file path → dotted module.
            rel = py_file.relative_to(root).with_suffix("")
            source_module = ".".join(rel.parts)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    target = node.module
                    violations.extend(
                        self.check_import(source_module, target)
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        target = alias.name
                        violations.extend(
                            self.check_import(source_module, target)
                        )
        return violations

    def size(self) -> int:
        return len(self._paths)

    def rule_count(self) -> int:
        return len(self._import_rules)

    def layer_count(self) -> int:
        return len(self._layers)

    def clear(self) -> None:
        self._paths.clear()
        self._import_rules.clear()
        self._layers.clear()


_map: CanonicalMap | None = None


def get_canonical_map() -> CanonicalMap:
    global _map
    if _map is None:
        _map = CanonicalMap()
    return _map


def reset_canonical_map() -> None:
    global _map
    _map = None
