"""WorkflowLauncher — S19 K3 W1: SemVer range resolution for workflow invocation.

Назначение:
    * Resolves workflow name + optional SemVer range to best matching version
      from installed workflows.
    * Used by InvokeWorkflowProcessor when workflow reference contains a range.
    * Integrates with WorkflowRegistry for version lookup.

Использование::

    launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0", "wf_b": "2.1.0"})
    resolved = launcher.resolve("wf_a", ">=1.0,<2.0")  # Returns "1.5.0"
    resolved = launcher.resolve("wf_b", ">=2.0,<3.0")  # Returns "2.1.0"

"""

from __future__ import annotations

from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from src.backend.core.logging import get_logger

__all__ = ("WorkflowLauncher", "WorkflowResolutionError")

_logger = get_logger(__name__)


class WorkflowResolutionError(ValueError):
    """Raised when workflow version cannot be resolved."""


@dataclass(frozen=True, slots=True)
class ResolvedWorkflow:
    """Result of successful workflow resolution."""

    name: str
    version: str
    spec: str  # Original spec string (e.g., ">=1.0,<2.0")


class WorkflowLauncher:
    """Resolves workflow references with SemVer ranges to installed versions.

    Args:
        installed_workflows: Mapping of workflow_name → installed version.
        registry: Optional WorkflowRegistry for additional lookup.
    """

    def __init__(
        self,
        installed_workflows: dict[str, str] | None = None,
        registry: object | None = None,  # WorkflowRegistry
    ) -> None:
        self._installed = dict(installed_workflows or {})
        self._registry = registry

    def resolve(self, workflow_name: str, spec: str | None = None) -> ResolvedWorkflow:
        """Resolve workflow name + SemVer spec to best matching version.

        Args:
            workflow_name: Name of the workflow to resolve.
            spec: Optional SemVer specifier string (e.g., ">=1.0,<2.0").
                  If None, returns the installed version if available.

        Returns:
            ResolvedWorkflow with name, version, and original spec.

        Raises:
            WorkflowResolutionError: If workflow not found or no version
                matches the spec.
        """
        if spec is None:
            # No spec provided - just return installed version if available
            version = self._installed.get(workflow_name)
            if version is None:
                raise WorkflowResolutionError(
                    f"Workflow '{workflow_name}' not found in installed workflows. "
                    f"Available: {list(self._installed.keys())}"
                )
            return ResolvedWorkflow(name=workflow_name, version=version, spec="*")

        # Parse the spec
        try:
            spec_set = SpecifierSet(spec)
        except InvalidSpecifier as exc:
            raise WorkflowResolutionError(
                f"Invalid SemVer spec for workflow '{workflow_name}': {spec!r}. "
                f"Error: {exc}"
            ) from exc

        installed_version_str = self._installed.get(workflow_name)
        if installed_version_str is None:
            raise WorkflowResolutionError(
                f"Workflow '{workflow_name}' not found in installed workflows. "
                f"Available: {list(self._installed.keys())}"
            )

        # Check if installed version matches the spec
        try:
            installed_version = Version(installed_version_str)
        except Exception as exc:
            raise WorkflowResolutionError(
                f"Invalid version string for workflow '{workflow_name}': "
                f"{installed_version_str!r}. Error: {exc}"
            ) from exc

        if installed_version in spec_set:
            return ResolvedWorkflow(
                name=workflow_name, version=installed_version_str, spec=spec
            )

        # Find best matching version if multiple versions were available
        # In practice, we only have one installed version, so check if it matches
        raise WorkflowResolutionError(
            f"Installed version '{installed_version_str}' of workflow "
            f"'{workflow_name}' does not match spec '{spec}'"
        )

    def resolve_best_match(
        self, workflow_name: str, spec: str, available_versions: list[str] | None = None
    ) -> ResolvedWorkflow:
        """Resolve to best matching version from available versions.

        If multiple versions are available, selects the highest version
        that satisfies the spec (using exponential sorting).

        Args:
            workflow_name: Name of the workflow.
            spec: SemVer specifier string.
            available_versions: List of available version strings.
                If None, uses installed_workflows dict.

        Returns:
            ResolvedWorkflow with best matching version.

        Raises:
            WorkflowResolutionError: If no version matches the spec.
        """
        if available_versions is None:
            # Use single installed version
            return self.resolve(workflow_name, spec)

        try:
            spec_set = SpecifierSet(spec)
        except InvalidSpecifier as exc:
            raise WorkflowResolutionError(
                f"Invalid SemVer spec: {spec!r}. Error: {exc}"
            ) from exc

        matching: list[tuple[Version, str]] = []
        for version_str in available_versions:
            try:
                v = Version(version_str)
                if v in spec_set:
                    matching.append((v, version_str))
            except Exception as _:
                continue

        if not matching:
            raise WorkflowResolutionError(
                f"No version of workflow '{workflow_name}' matches spec '{spec}'. "
                f"Available versions: {available_versions}"
            )

        # Sort by version and return highest
        matching.sort(key=lambda x: x[0], reverse=True)
        best_version = matching[0][1]
        return ResolvedWorkflow(name=workflow_name, version=best_version, spec=spec)

    def is_compatible(self, workflow_name: str, spec: str) -> bool:
        """Check if installed workflow version is compatible with spec.

        Args:
            workflow_name: Name of the workflow.
            spec: SemVer specifier string.

        Returns:
            True if installed version matches the spec, False otherwise.
        """
        try:
            self.resolve(workflow_name, spec)
            return True
        except WorkflowResolutionError:
            return False

    def get_installed_version(self, workflow_name: str) -> str | None:
        """Get installed version for a workflow.

        Args:
            workflow_name: Name of the workflow.

        Returns:
            Installed version string or None if not found.
        """
        return self._installed.get(workflow_name)

    def set_installed_version(self, workflow_name: str, version: str) -> None:
        """Set installed version for a workflow.

        Args:
            workflow_name: Name of the workflow.
            version: Version string.
        """
        self._installed[workflow_name] = version

    def list_workflows(self) -> list[str]:
        """List all installed workflow names."""
        return list(self._installed.keys())
