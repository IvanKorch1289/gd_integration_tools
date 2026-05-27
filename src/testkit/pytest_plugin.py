"""Pytest entry-point plugin for ``src.testkit`` fixtures.

K5 S19 W3 (S-L10-1). Registers :mod:`src.testkit.fixtures` so that
``har_recorder``, ``har_cassette_path``, ``memory_metrics``, and
``audit_events`` fixtures are automatically available to tests without
explicit imports.

The entry-point is registered in ``pyproject.toml`` under
``[project.entry-points."pytest11"]`` as::

    src_testkit = "src.testkit.pytest_plugin"

Unlike the root ``testkit`` package which also registers fixtures for
docker containers (postgres, redis, temporal, toxiproxy), this plugin
only registers lightweight in-process fixtures suitable for unit tests
and plugin author tests.
"""

from __future__ import annotations

pytest_plugins = ("src.testkit.fixtures",)
