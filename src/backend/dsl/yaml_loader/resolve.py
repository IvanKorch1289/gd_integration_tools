"""S62 W4 — resolve.py part of yaml_loader decomp.

Funcs: _is_route_composition_include_enabled, _resolve_include_extends.

include/extends resolution (153 LOC BIG).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Sentinel for "not set" to distinguish from None
_MISSING = object()


def _is_route_composition_include_enabled() -> bool:
    """Check if route_composition_include feature flag is enabled."""
    try:
        from src.backend.core.config.features import feature_flags

        return getattr(feature_flags, "route_composition_include", False)
    except ImportError:
        return False


def _resolve_contained_path(
    ref: str, base_path: Path | None, trusted_root: Path
) -> Path:
    """Резолвит ``ref`` относительно ``base_path`` и проверяет containment.

    Defense-in-depth против path traversal: ``extends: ../../../etc/passwd``
    и абсолютные пути (``extends: /etc/passwd``) режутся здесь, до
    ``read_text``. Возвращает ``.resolve()``-нутый путь; бросает
    ``ValueError`` если итоговый путь выходит за ``trusted_root``.

    Args:
        ref: Строка из YAML (``extends``/``include``).
        base_path: Директория файла-источника (или None → ``Path.cwd()``).
        trusted_root: Граница, наружу которую нельзя выходить.

    Returns:
        Path: Абсолютный путь к YAML-файлу.

    Raises:
        ValueError: Путь выходит за ``trusted_root``.
    """
    candidate = (
        (base_path / ref).resolve() if base_path is not None else Path(ref).resolve()
    )
    if not candidate.is_relative_to(trusted_root):
        raise ValueError(
            f"extends/include path escapes trusted root {trusted_root}: "
            f"{ref!r} resolves to {candidate}"
        )
    return candidate


def _resolve_include_extends(
    data: dict[str, Any],
    base_path: Path | None = None,
    _visited: set[str] | None = None,
    _is_root: bool = True,
    _trusted_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve include: and extends: fields in a YAML spec with cycle detection.

    Args:
        data: Parsed YAML dict.
        base_path: Base directory for resolving relative paths.
            On first call from load_pipeline_from_yaml, this is the directory
            containing the YAML file (file_path.parent). On recursive calls it's
            the parent directory of the extended/included file.
        _visited: Internal set for cycle detection (files being processed).
        _is_root: True for the initial call, False for recursive calls.
        _trusted_root: Граница containment для path-traversal защиты.
            Пинится на первом вызове из ``base_path`` (или ``Path.cwd()``,
            если ``base_path`` не задан — для прямых вызовов
            ``load_pipeline_from_yaml`` без файла).

    Raises:
        RuntimeError: If a cycle is detected in include/extends chain.
        ValueError: If extends/include path escapes ``_trusted_root``.
    """
    if _visited is None:
        _visited = set()

    # Pin trusted_root на первом вызове — все extends/include
    # должны оставаться внутри этой директории.
    if _is_root:
        _trusted_root = (
            base_path.resolve() if base_path is not None else Path.cwd().resolve()
        )

    # Work on a copy to avoid mutating the original
    spec = dict(data)

    # Handle extends: - inherit from a base YAML file
    extends_path = spec.pop("extends", None)
    if extends_path is not None:
        ext_str = str(extends_path)
        resolved_path = _resolve_contained_path(ext_str, base_path, _trusted_root)

        if not resolved_path.exists():
            raise FileNotFoundError(f"Extended YAML file not found: {resolved_path}")

        resolved_str = str(resolved_path)
        if resolved_str in _visited:
            raise RuntimeError(
                f"Cycle detected in extends: chain: {resolved_str} is already "
                f"being processed. Chain: {_visited}",
            )
        _visited.add(resolved_str)

        ext_yaml_str = resolved_path.read_text(encoding="utf-8")
        import yaml

        base_data = yaml.safe_load(ext_yaml_str)
        if not isinstance(base_data, dict):
            raise ValueError(
                f"Extended YAML must be a mapping, got: {type(base_data).__name__}",
            )

        # Recursively resolve the base (in case it also has include/extends)
        base_data = _resolve_include_extends(
            base_data,
            resolved_path.parent,
            _visited,
            _is_root=False,
            _trusted_root=_trusted_root,
        )

        # Merge: child overrides parent
        # Start with base, then overlay child (child takes precedence)
        merged: dict[str, Any] = {}
        # First add all from base (including steps)
        for k, v in base_data.items():
            if k not in ("include", "extends"):
                merged[k] = v
        # Then overlay from child (allows overriding)
        for k, v in spec.items():
            if k not in ("include", "extends"):
                merged[k] = v
        # For 'steps', we must CONCATENATE not replace (extends adds steps)
        if "steps" in base_data and "steps" in spec:
            merged["steps"] = base_data["steps"] + spec["steps"]
        spec = merged

    # Handle include: - include steps from other YAML files (one level)
    include_paths = spec.pop("include", None)
    if include_paths is not None:
        if isinstance(include_paths, str):
            include_paths = [include_paths]
        if not isinstance(include_paths, list):
            raise ValueError(
                f"include: must be a string or list of strings, got: "
                f"{type(include_paths).__name__}",
            )

        # Collect steps from all included files
        all_steps: list[Any] = []

        for inc_path in include_paths:
            inc_str = str(inc_path)
            resolved_inc = _resolve_contained_path(inc_str, base_path, _trusted_root)

            # Check existence BEFORE tracking to avoid false-positive on first pass
            if not resolved_inc.exists():
                raise FileNotFoundError(f"Included YAML file not found: {resolved_inc}")

            resolved_inc_str = str(resolved_inc)
            if resolved_inc_str in _visited:
                raise RuntimeError(
                    f"Cycle detected in include: chain: {resolved_inc_str} is "
                    f"already being processed. Chain: {_visited}",
                )
            _visited.add(resolved_inc_str)

            inc_yaml_str = resolved_inc.read_text(encoding="utf-8")
            import yaml

            inc_data = yaml.safe_load(inc_yaml_str)
            if not isinstance(inc_data, dict):
                raise ValueError(
                    f"Included YAML must be a mapping, got: {type(inc_data).__name__}",
                )

            # Get steps from included file (recursive resolution for nested includes)
            inc_data = _resolve_include_extends(
                inc_data,
                resolved_inc.parent,
                _visited,
                _is_root=False,
                _trusted_root=_trusted_root,
            )
            inc_steps = inc_data.get("steps", [])
            if not isinstance(inc_steps, list):
                raise ValueError(
                    f"steps: in included file must be a list, got: "
                    f"{type(inc_steps).__name__}",
                )
            all_steps.extend(inc_steps)

        # Append included steps to the current spec's steps
        existing_steps = spec.get("steps", [])
        if not isinstance(existing_steps, list):
            raise ValueError(
                f"steps: must be a list, got: {type(existing_steps).__name__}",
            )
        spec["steps"] = existing_steps + all_steps

    return spec
