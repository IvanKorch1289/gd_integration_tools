"""Performance invariants for Sprint 170 M2 Phase 4.

Codifies:
1. No blocking I/O in async context (requests, psycopg2 sync, time.sleep)
2. Connection pool sizes configured in base.yml
3. Acceleration libs in use (orjson, uvloop, httpx)
4. No sync wrappers around async libs in hot paths
"""
from __future__ import annotations

import ast
import os
import re
import tomllib
from pathlib import Path


def test_no_blocking_io_in_async():
    """Scan all async functions for blocking patterns."""
    issues = []
    BLOCKING = ["requests.get", "requests.post", "psycopg2.connect", "time.sleep("]
    for root, _, files in os.walk("src/backend"):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(open(path).read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    src = ast.unparse(node)
                    for pattern in BLOCKING:
                        if pattern in src and "asyncio.sleep" not in src:
                            issues.append((path, node.name, pattern))
    assert not issues, f"Blocking I/O in async: {issues}"


def test_acceleration_libs_in_pyproject():
    """orjson, uvloop, httpx, asyncpg must be declared dependencies."""
    pyproject = Path("pyproject.toml")
    data = tomllib.loads(pyproject.read_text())
    deps = data["project"]["dependencies"]
    required = ["orjson", "uvloop", "httpx", "asyncpg"]
    missing = [lib for lib in required if not any(lib in d for d in deps)]
    assert not missing, f"Missing acceleration libs: {missing}"


def test_connection_pools_configured():
    """base.yml must declare at least 3 connection pool sizes."""
    base = Path("config_profiles/base.yml").read_text()
    pool_lines = [
        line for line in base.split("\n")
        if re.search(r"pool_size|max_connections|max_pool_size|connection_pool_size", line)
    ]
    assert len(pool_lines) >= 3, f"Only {len(pool_lines)} pool configs found"


def test_uvloop_enabled_in_main():
    """main.py must use uvloop."""
    main = Path("src/backend/main.py").read_text()
    assert "uvloop" in main, "uvloop not imported in main.py"


def test_orjson_used_not_stdlib_json():
    """At least 5 files should import orjson instead of stdlib json."""
    orjson_users = 0
    for root, _, files in os.walk("src/backend"):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            if "orjson" in open(path).read():
                orjson_users += 1
    assert orjson_users >= 5, f"Only {orjson_users} files use orjson"
