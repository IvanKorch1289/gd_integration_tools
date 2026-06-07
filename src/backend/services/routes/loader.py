"""ADR-043 (R1.2a) — :class:`RouteLoader` для ``routes/<name>/``.

Discovery + lifecycle V11-маршрутов:

1. scan ``routes/<name>/route.toml``;
2. ``requires_core`` + ``requires_plugins`` валидация по installed-таблице;
3. ``capabilities ⊆ union(plugin.capabilities) ∪ public-core`` invariant;
4. ``feature_flag`` резолвинг (None | bool | имя ENV или dotted-path);
5. регистрация всех ``pipelines`` через ``pipeline_registrar``;
6. unload — обратные шаги.

Параллельно с legacy-плоским ``dsl_routes/*.yaml``; миграция —
:mod:`tools.migrate_dsl_routes_to_v11`.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.backend.core.security.capabilities import (
    CapabilityError,
    CapabilityGate,
    CapabilityRef,
    CapabilitySupersetError,
    CapabilityVocabulary,
    check_capabilities_subset,
)
from src.backend.services.routes.manifest_v11 import (
    RouteManifestError,
    RouteManifestV11,
    load_route_manifest,
)

__all__ = (
    "AuditCallback",
    "FeatureFlagResolver",
    "InstalledPlugin",
    "LoadedRoute",
    "PipelineRegistrar",
    "RouteLoader",
    "default_env_feature_flag_resolver",
)

AuditCallback = Callable[[dict[str, Any]], None]
"""Подпись audit-callback'а RouteLoader: принимает event dict."""

_logger = get_logger("services.routes.loader")


PipelineRegistrar = Callable[[str, Path, RouteManifestV11], None]
"""Подпись callback'а: ``(route_name, pipeline_path, manifest) -> None``.

K-ARCH-4 (S17): третий параметр — полный manifest. Регистратор может
читать ``manifest.tenant_aware`` и пробрасывать в Pipeline.tenant_aware
для runtime-проверки в ExecutionEngine.
"""

FeatureFlagResolver = Callable[[str], bool]
"""Резолвер строкового feature_flag в bool."""


def default_env_feature_flag_resolver(flag: str) -> bool:
    """Резолвит строку как ENV-переменную (truthy: ``1``/``true``/``yes``)."""
    raw = os.environ.get(flag, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    """Информация об установленном плагине для проверки ``requires_plugins``."""

    name: str
    version: str
    capabilities: tuple[CapabilityRef, ...]


@dataclass(slots=True)
class LoadedRoute:
    """Результат попытки загрузки одного маршрута."""

    name: str
    version: str
    manifest_path: Path
    status: str  # "enabled" | "disabled" | "failed" | "skipped"
    reason: str | None = None
    manifest: RouteManifestV11 | None = None
    registered_pipelines: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для ``/api/v1/routes/inventory``."""
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "manifest_path": str(self.manifest_path),
            "tags": list(self.manifest.tags) if self.manifest else [],
            "pipelines": [str(p) for p in self.registered_pipelines],
        }


class RouteLoader:
    """V11 RouteLoader: scan ``routes/<name>/route.toml``.

    Args:
        routes_dir: Каталог с подкаталогами маршрутов.
        capability_gate: Runtime-gate для декларации route-capabilities.
        vocabulary: Capability-registry (для subset-проверки).
        core_version: Текущая версия ядра.
        installed_plugins: Mapping ``name → InstalledPlugin``.
        pipeline_registrar: Callback регистрации YAML-pipeline'а в DSL-engine.
        feature_flag_resolver: Резолвер строкового feature_flag (ENV / DI).
    """

    def __init__(
        self,
        *,
        routes_dir: Path,
        capability_gate: CapabilityGate,
        vocabulary: CapabilityVocabulary,
        core_version: str,
        installed_plugins: dict[str, InstalledPlugin],
        pipeline_registrar: PipelineRegistrar,
        feature_flag_resolver: FeatureFlagResolver = default_env_feature_flag_resolver,
        audit_callback: AuditCallback | None = None,
        strict_capabilities: bool | None = None,
        installed_workflows: dict[str, str] | None = None,
    ) -> None:
        self._routes_dir = Path(routes_dir)
        self._gate = capability_gate
        self._vocabulary = vocabulary
        self._core_version = core_version
        self._installed = installed_plugins
        self._registrar = pipeline_registrar
        self._resolve_flag = feature_flag_resolver
        self._audit = audit_callback
        # ── strict-режим: route без declared capabilities → failed.
        #    Источник по умолчанию — feature_flags.routes_capability_gate_strict
        #    (K-ARCH-3, S17). None → попытаться прочитать из feature_flags.
        self._strict_capabilities = strict_capabilities
        self._loaded: dict[str, LoadedRoute] = {}
        # K3 S19 W1: workflow version checking
        self._installed_workflows = installed_workflows or {}

    @property
    def loaded(self) -> tuple[LoadedRoute, ...]:
        """Все маршруты (enabled / disabled / failed / skipped)."""
        return tuple(self._loaded.values())

    @property
    def enabled(self) -> tuple[LoadedRoute, ...]:
        """Только активные маршруты."""
        return tuple(r for r in self._loaded.values() if r.status == "enabled")

    async def discover_and_load(self) -> tuple[LoadedRoute, ...]:
        """Сканировать ``routes/`` и активировать совместимые маршруты."""
        if not self._routes_dir.is_dir():
            _logger.info(
                "Routes dir %s not found — no V11 routes discovered", self._routes_dir
            )
            return ()

        for child in sorted(self._routes_dir.iterdir()):
            manifest_path = child / "route.toml"
            if not manifest_path.is_file():
                continue
            self._load_one(manifest_path)
        return self.loaded

    async def unload_all(self) -> None:
        """Снять все capability-декларации и зачистить состояние."""
        for entry in tuple(self._loaded.values()):
            if entry.status == "enabled":
                self._gate.revoke(entry.name)
        self._loaded.clear()

    # ── private ──────────────────────────────────────────────────────

    def _load_one(self, manifest_path: Path) -> None:
        """Обработать один ``route.toml`` целиком."""
        try:
            manifest = load_route_manifest(manifest_path)
        except RouteManifestError as exc:
            _logger.warning("Route manifest invalid (%s): %s", manifest_path, exc)
            self._loaded[manifest_path.parent.name] = LoadedRoute(
                name=manifest_path.parent.name,
                version="?",
                manifest_path=manifest_path,
                status="failed",
                reason=f"manifest_error: {exc}",
            )
            return

        # ── Pre-condition: requires_core
        if not manifest.is_compatible_with_core(self._core_version):
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="skipped",
                reason=(
                    f"requires_core={manifest.requires_core}, core={self._core_version}"
                ),
            )
            return

        # ── Pre-condition: requires_plugins
        installed_versions = {n: p.version for n, p in self._installed.items()}
        missing = manifest.missing_plugins(installed_versions)
        if missing:
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"missing_plugins: {missing}",
            )
            return

        # ── Pre-condition: requires_workflows (K3 S19 W1)
        if manifest.requires_workflows:
            missing_wf = manifest.missing_workflows(self._installed_workflows)
            if missing_wf:
                # Emit audit event for workflow version mismatch
                self._emit_audit(
                    {
                        "event": "workflow.version.mismatch",
                        "route": manifest.name,
                        "version": manifest.version,
                        "missing_workflows": missing_wf,
                    }
                )
                self._loaded[manifest.name] = LoadedRoute(
                    name=manifest.name,
                    version=manifest.version,
                    manifest_path=manifest_path,
                    manifest=manifest,
                    status="failed",
                    reason=f"missing_workflows: {missing_wf}",
                )
                return

        # ── Pre-condition: requires_permission format validation (K3 S19 W3)
        if manifest.security and manifest.security.requires_permission:
            invalid = self._validate_permission_strings(
                manifest.security.requires_permission
            )
            if invalid:
                self._loaded[manifest.name] = LoadedRoute(
                    name=manifest.name,
                    version=manifest.version,
                    manifest_path=manifest_path,
                    manifest=manifest,
                    status="failed",
                    reason=f"invalid_permission_format: {invalid}",
                )
                return

        # ── Inv: route.capabilities ⊆ plugin-каталог ∪ public-core
        try:
            plugin_caps_by_name = {
                name: self._installed[name].capabilities
                for name in manifest.requires_plugins
            }
            check_capabilities_subset(
                route=manifest.name,
                route_caps=manifest.capabilities,
                plugin_caps_by_name=plugin_caps_by_name,
                vocabulary=self._vocabulary,
            )
        except CapabilitySupersetError as exc:
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"capability_superset: {exc}",
            )
            return

        # ── feature_flag → enabled / disabled
        try:
            enabled = self._resolve_feature_flag(manifest.feature_flag)
        except Exception as exc:
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"feature_flag_error: {exc}",
            )
            return

        if not enabled:
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="disabled",
                reason=f"feature_flag={manifest.feature_flag!r}=False",
            )
            return

        # ── strict-режим (K-ARCH-3, S17): route без declared capabilities → fail
        if self._is_strict() and not manifest.capabilities:
            reason = (
                "routes_capability_gate_strict: route has no declared "
                "capabilities (manifest.capabilities is empty)"
            )
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=reason,
            )
            return

        # ── Декларация capabilities в gate'е ДО pipeline_registrar
        #    (route — equal-rights peer плагина). K-ARCH-3 (S17).
        try:
            self._gate.declare(manifest.name, manifest.capabilities)
        except (CapabilityError, ValueError) as exc:
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"capability_error: {exc}",
            )
            return

        # ── Audit: capability-аллокация (route.capabilities.allocated)
        self._emit_audit(
            {
                "event": "route.capabilities.allocated",
                "route": manifest.name,
                "version": manifest.version,
                "capabilities": [
                    {"name": ref.name, "scope": ref.scope}
                    for ref in manifest.capabilities
                ],
            }
        )

        # ── Регистрация pipelines через registrar
        registered: list[Path] = []
        try:
            for relative in manifest.pipelines:
                pipeline_path = manifest_path.parent / relative
                if not pipeline_path.is_file():
                    raise FileNotFoundError(f"Pipeline file not found: {pipeline_path}")
                self._registrar(manifest.name, pipeline_path, manifest)
                registered.append(pipeline_path)
        except Exception as exc:
            _logger.exception("Route %s pipeline registration failed", manifest.name)
            self._gate.revoke(manifest.name)
            self._loaded[manifest.name] = LoadedRoute(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"pipeline_register_error: {exc}",
            )
            return

        self._loaded[manifest.name] = LoadedRoute(
            name=manifest.name,
            version=manifest.version,
            manifest_path=manifest_path,
            manifest=manifest,
            status="enabled",
            registered_pipelines=tuple(registered),
        )
        _logger.info(
            "Route enabled (V11): %s v%s (%d pipeline%s)",
            manifest.name,
            manifest.version,
            len(registered),
            "" if len(registered) == 1 else "s",
        )

    def _resolve_feature_flag(self, flag: str | bool | None) -> bool:
        """Резолвит ``manifest.feature_flag`` в bool.

        - ``None`` → True (по умолчанию route активен);
        - ``bool`` → as-is;
        - ``str`` → через :attr:`_resolve_flag`.
        """
        if flag is None:
            return True
        if isinstance(flag, bool):
            return flag
        return self._resolve_flag(flag)

    def _is_strict(self) -> bool:
        """K-ARCH-3 (S17): strict-режим routes-capability-gate.

        Источник:
            1. Явный конструктор ``strict_capabilities=True/False``;
            2. ``feature_flags.routes_capability_gate_strict``.
        """
        if self._strict_capabilities is not None:
            return self._strict_capabilities
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.routes_capability_gate_strict)
        except Exception as _:
            return False

    def _emit_audit(self, event: dict[str, Any]) -> None:
        """Эмиссия audit-event через ``audit_callback`` (best-effort)."""
        if self._audit is None:
            return
        try:
            self._audit(event)
        except Exception:
            _logger.exception(
                "RouteLoader audit_callback failed: %s", event.get("event")
            )

    # ── permission validation helpers ──────────────────────────────────

    PERMISSION_PREFIXES = ("role:", "scope:")

    def _validate_permission_strings(self, permissions: tuple[str, ...]) -> str | None:
        """Валидирует формат permission-strings.

        Каждая permission должна начинаться с ``role:`` или ``scope:``.

        Returns:
            None если все валидны; str с описанием первой ошибки иначе.
        """
        for perm in permissions:
            if not any(perm.startswith(prefix) for prefix in self.PERMISSION_PREFIXES):
                return (
                    f"permission {perm!r} must start with "
                    f"{' or '.join(repr(p) for p in self.PERMISSION_PREFIXES)}"
                )
        return None
