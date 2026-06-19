"""API versioning: header/URL, deprecation+sunset metadata."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("APIVersion",)


@dataclass(slots=True)
class APIVersion:
    """API version information for response headers.

    Attributes:
        version: Version string (e.g. "v1").
        deprecated: Whether this version is deprecated.
        sunset: Sunset date in ISO format (RFC 8594).
    """
    version: str
    deprecated: bool = False
    sunset: str | None = None  # ISO date (RFC 8594)

    def as_headers(self) -> dict[str, str]:
        """Convert to HTTP headers dict.

        Returns:
            Dictionary of version-related headers.
        """
        out = {"API-Version": self.version}
        if self.deprecated:
            out["Deprecation"] = "true"
        if self.sunset:
            out["Sunset"] = self.sunset
        return out
