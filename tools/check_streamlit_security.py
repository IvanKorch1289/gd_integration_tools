"""S78 W2 — security checks для Streamlit deployment.

FINAL_REPORT_V2 P0-D closure: Streamlit config.toml не валидируется
на insecure defaults. Pre-S78: enableCORS=false, enableXsrfProtection=false
(unsafe для production). S78 W2: validation helper для CI/pre-deploy.

**Checks**:
* ``enableXsrfProtection`` must be True (CSRF protection ON).
* ``enableCORS`` should be True with explicit allowlist (NOT wildcard).
* ``corsAllowedOrigins`` should not contain wildcards (``*``).
* ``gatherUsageStats`` should be False (privacy).
* ``server.headless`` should be True (production — no browser auto-open).

Use case:
* CI gate: ``python -m tools.check_streamlit_security`` fails build
  if insecure defaults detected.
* Pre-deploy: manual check на production servers.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(
    "src/frontend/streamlit_app/.streamlit/config.toml"
)

__all__ = (
    "SecurityCheck",
    "SecurityCheckResult",
    "check_streamlit_config",
)


@dataclass(frozen=True)
class SecurityCheck:
    """Single security check result."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class SecurityCheckResult:
    """Aggregate result of all Streamlit security checks."""

    config_path: Path
    checks: list[SecurityCheck]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed(self) -> list[SecurityCheck]:
        return [c for c in self.checks if not c.passed]


def _check_xsrf(config: dict[str, Any]) -> SecurityCheck:
    server = config.get("server", {})
    enabled = server.get("enableXsrfProtection", False)
    if enabled is True:
        return SecurityCheck(
            name="enableXsrfProtection",
            passed=True,
            detail="XSRF/CSRF protection is enabled.",
        )
    return SecurityCheck(
        name="enableXsrfProtection",
        passed=False,
        detail=(
            f"enableXsrfProtection={enabled!r} (must be True). "
            "Pre-S78 default was False (unsafe for production)."
        ),
    )


def _check_cors(config: dict[str, Any]) -> SecurityCheck:
    server = config.get("server", {})
    enabled = server.get("enableCORS", False)
    allowed = server.get("corsAllowedOrigins", [])

    if not enabled:
        return SecurityCheck(
            name="enableCORS",
            passed=False,
            detail=(
                "enableCORS=False (browser same-origin only). "
                "Если нужен cross-origin from admin UI: enable с allowlist."
            ),
        )

    if not allowed:
        return SecurityCheck(
            name="corsAllowedOrigins",
            passed=False,
            detail=(
                "enableCORS=True, но corsAllowedOrigins не задан. "
                "Without explicit allowlist Streamlit может accept any origin."
            ),
        )

    wildcards = [o for o in allowed if "*" in o]
    if wildcards:
        return SecurityCheck(
            name="corsAllowedOrigins",
            passed=False,
            detail=(
                f"Wildcard origins found: {wildcards}. "
                "Wildcard + credentials = security anti-pattern (CORS spec)."
            ),
        )

    return SecurityCheck(
        name="corsAllowedOrigins",
        passed=True,
        detail=f"Explicit allowlist: {len(allowed)} origins.",
    )


def _check_gather_usage_stats(config: dict[str, Any]) -> SecurityCheck:
    browser = config.get("browser", {})
    enabled = browser.get("gatherUsageStats", True)  # default True
    if enabled is False:
        return SecurityCheck(
            name="gatherUsageStats",
            passed=True,
            detail="Usage stats disabled (privacy OK).",
        )
    return SecurityCheck(
        name="gatherUsageStats",
        passed=False,
        detail=(
            f"gatherUsageStats={enabled!r} (must be False). "
            "Pre-S78 default was True (sends usage data to Streamlit analytics)."
        ),
    )


def _check_headless(config: dict[str, Any]) -> SecurityCheck:
    server = config.get("server", {})
    headless = server.get("headless", False)
    if headless is True:
        return SecurityCheck(
            name="headless",
            passed=True,
            detail="headless=True (production-safe, no browser auto-open).",
        )
    return SecurityCheck(
        name="headless",
        passed=False,
        detail=(
            f"headless={headless!r} (should be True для production). "
            "headless=False means Streamlit auto-opens browser on startup."
        ),
    )


def check_streamlit_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> SecurityCheckResult:
    """Run all security checks on Streamlit config.

    Args:
        config_path: path к ``config.toml``. Default: project's
            ``src/frontend/streamlit_app/.streamlit/config.toml``.

    Returns:
        :class:`SecurityCheckResult` с list of checks (passed + failed).

    Raises:
        FileNotFoundError: config_path не существует.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Streamlit config не найден: {config_path}"
        )

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    checks = [
        _check_xsrf(config),
        _check_cors(config),
        _check_gather_usage_stats(config),
        _check_headless(config),
    ]

    return SecurityCheckResult(
        config_path=config_path,
        checks=checks,
    )


def main() -> int:
    """CLI entrypoint для CI gate / pre-deploy check.

    Returns:
        Exit code: 0 = all passed, 1 = some failed.
    """
    # S78 W4 fix: read module attribute at call time (testability)
    result = check_streamlit_config(DEFAULT_CONFIG_PATH)
    print(f"Streamlit security check: {result.config_path}")
    print()
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        marker = "[OK]" if check.passed else "[!!]"
        print(f"  {marker} {status} {check.name}")
        if not check.passed:
            print(f"      {check.detail}")
    print()
    if result.all_passed:
        print("All security checks passed.")
        return 0
    print(f"{len(result.failed)} check(s) failed. See details above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
