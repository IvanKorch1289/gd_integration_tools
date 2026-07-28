"""RouteBuilder MRO depth gate (Cycle 43, Layer 3).

Назначение:
    Layer 3 (Routes/Plugins) audit (cycle 42) found RouteBuilder has 82
    classes in its MRO (was 36 at audit time, has GROWN 2x since).
    Each RouteBuilder() constructor walks 82 MRO levels; every IDE
    autocomplete is 82 entries long; every type error runs through
    80 mixins. This is the documented "god-class" anti-pattern that the
    CompositionRouteBuilder migration is supposed to address (currently
    stalled at step 1/4).

    This gate enforces an MRO-depth budget to prevent further god-class
    creep. Fails CI if MRO > MAX_MRO_DEPTH (default 50, configurable).

Usage:
    python tools/checks/check_routebuilder_mro.py
    python tools/checks/check_routebuilder_mro.py --max 40
    python tools/checks/check_routebuilder_mro.py --info  # show breakdown

Recommended follow-up: integrate into Makefile + CI pipeline.
"""

from __future__ import annotations

import argparse
import sys

DEFAULT_MAX_MRO_DEPTH = 50


def get_route_builder_mro() -> tuple[type, ...]:
    """Import RouteBuilder and return its MRO tuple.

    Returns:
        MRO tuple (includes RouteBuilder + all bases + object).
    """
    # Lazy import to avoid loading whole DSL on each invocation.
    from src.backend.dsl.builder import RouteBuilder

    return RouteBuilder.__mro__


def filter_top_level_bases(mro: tuple[type, ...]) -> list[type]:
    """Filter MRO to top-level mixin bases (skip nested base classes).

    The 82-class MRO includes many deeply-nested intermediate base classes
    (e.g., EIPMixinBase, AirpaMixin, EipRoutingMixin etc.). For the
    budget gate we count only DIRECT public-API mixin bases — the
    "user-facing" architectural surface.

    Returns:
        List of top-level mixin classes (skip nested _XxxBase classes
        and protocol stubs).
    """
    skip_suffixes = ("Base", "Protocol", "_Stub")
    skip_prefixes = ("_",)

    top_level = []
    for cls in mro:
        if cls is type(None) or cls is object:
            continue
        if any(cls.__name__.endswith(suf) for suf in skip_suffixes):
            continue
        if any(cls.__name__.startswith(pre) for pre in skip_prefixes):
            continue
        top_level.append(cls)
    return top_level


def check_mro_depth(max_mro_depth: int) -> tuple[bool, str]:
    """Run MRO-depth check.

    Args:
        max_mro_depth: Maximum allowed MRO depth.

    Returns:
        Tuple (passed, message). passed=True if MRO depth <= max_mro_depth.
    """
    mro = get_route_builder_mro()
    actual = len(mro)
    top_level = filter_top_level_bases(mro)
    actual_top = len(top_level)

    msg_lines = [
        f"RouteBuilder MRO depth: {actual} (limit: {max_mro_depth})",
        f"Top-level mixin bases: {actual_top}",
    ]

    if actual > max_mro_depth:
        msg_lines.append("FAIL: RouteBuilder MRO exceeds budget.")
        return False, "\n".join(msg_lines)

    msg_lines.append("OK: RouteBuilder MRO within budget.")
    return True, "\n".join(msg_lines)


def print_mro_breakdown() -> None:
    """Print full MRO breakdown for diagnostic purposes."""
    mro = get_route_builder_mro()
    print(f"RouteBuilder.__mro__ ({len(mro)} classes):")
    for idx, cls in enumerate(mro):
        print(f"  [{idx}] {cls.__module__}.{cls.__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="RouteBuilder MRO depth gate")
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_MRO_DEPTH,
        help=f"Max MRO depth (default: {DEFAULT_MAX_MRO_DEPTH})",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print full MRO breakdown instead of running the gate",
    )
    args = parser.parse_args()

    if args.info:
        print_mro_breakdown()
        return 0

    passed, message = check_mro_depth(args.max)
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
