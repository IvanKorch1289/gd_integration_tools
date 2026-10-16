"""Regression test (P0-1, 2026-10-13): cve-gate excludes optional-extras.

После переключения `make/security.mk:audit-deps` на
`uv export --no-dev --no-all-extras` (вместо `uv pip freeze`)
audit-requirements.txt не должен содержать пакетов,
которые существуют ТОЛЬКО в `[project.optional-dependencies]`
(redteam, ai, rag, mcp, rpa, ...).

Цель: предотвратить регресс, при котором `make cve-gate` снова
становится в зависимость от optional extra (например `deepteam`),
чей py3.14-installability сломан upstream-метаданными.

NB: `spacy` (ai-safety extra) и `streamlit` (frontend extra)
появляются в runtime export как transitive deps (`presidio-analyzer`
тянет spacy, `gd-advanced-tools` тянет streamlit). Это легитимные
runtime-deps, не extras. Тест не должен их блокировать.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
SECURITY_MK = REPO / "make" / "security.mk"


def _list_pyproject_optional_packages() -> set[str]:
    """Прочитать имена пакетов из `[project.optional-dependencies]`.

    Возвращает set всех extra-deps. Используется в тесте как reference
    list того, что НЕ ДОЛЖНО попасть в runtime export (если не
    transitive override).
    """
    in_section = False
    packages: set[str] = set()
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        if line.startswith("[project.optional-dependencies]"):
            in_section = True
            continue
        if in_section:
            if line.startswith("[") and not line.startswith("["):
                # Новая секция — выходим
                break
            # Извлекаем пакеты вида `"name>=version"` или `"name"`
            m = re.findall(r'"([a-zA-Z0-9_-]+)(?:>=|<|=|;|$)', line)
            packages.update(m)
    return packages


def test_audit_deps_uses_uv_export_not_uv_freeze() -> None:
    """`make/security.mk:audit-deps` ДОЛЖЕН использовать `uv export`,
    а НЕ `uv pip freeze` (который включает optional-extras).

    Аудит-контракт: cve-gate source-of-truth — `uv export --no-dev
    --no-all-extras` (исключает [project.optional-dependencies]).
    """
    body = SECURITY_MK.read_text(encoding="utf-8")

    # Найти recipe audit-deps до следующей строки верхнего уровня
    lines = body.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("audit-deps:"))
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("##", "#")):
            break
        recipe.append(line)
    recipe_text = "\n".join(recipe)

    assert re.search(r"uv\s+export\s+--no-dev\s+--no-all-extras", recipe_text), (
        "audit-deps recipe must use `uv export --no-dev --no-all-extras` "
        "to exclude [project.optional-dependencies] (redteam/ai/rag/mcp/rpa) "
        "from cve-gate."
    )

    # `uv pip freeze` допустим ТОЛЬКО как `||` fallback, не primary.
    for line in recipe_text.splitlines():
        if "uv pip freeze" in line and "||" not in line:
            pytest.fail(
                f"`uv pip freeze` в audit-deps без `||` fallback: {line!r}. "
                "freeze включает все установленные optional-extras (deepteam "
                "и др.), которые ломают cve-gate на py3.14."
            )


@pytest.mark.parametrize(
    "extra_pkg",
    [
        # redteam: первоочередной (deepteam 1.0.4 metadata `requires_python<3.14`
        # блокирует pip-audit --strict на py3.14, cve-gate fail-fast)
        "deepteam",
        # ai: lazy-import → not runtime, не должен попадать в cve-gate
        "langgraph",
        "dspy-ai",
        # rpa: pure extras (Linux-incompatible wheels)
        "patchright",
        # mcp: pure extra
        "fastmcp",
    ],
)
def test_optional_extra_not_in_runtime_export(extra_pkg: str) -> None:
    """Пакеты, перечисленные ТОЛЬКО в `[project.optional-dependencies]`
    (а не в main deps), НЕ ДОЛЖНЫ быть в `uv export --no-dev
    --no-all-extras` как direct pins.

    NB: transitive deps (e.g., spacy via presidio-analyzer) НЕ блокируются —
    они легитимные runtime-deps. Этот тест проверяет только direct extras.
    """
    proc = subprocess.run(
        ["uv", "export", "--no-dev", "--no-all-extras", "--format", "requirements-txt"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )

    # uv export — hash-pinned multi-line; direct pins идут в начале строки.
    direct_hits = [
        line
        for line in proc.stdout.splitlines()
        if line.strip().startswith(f"{extra_pkg}==")
        or line.strip().startswith(f"{extra_pkg} ;")
        or line.strip().startswith(f"{extra_pkg};")
    ]

    assert not direct_hits, (
        f"Optional extra `{extra_pkg}` appears as a direct pin in "
        f"`uv export --no-dev --no-all-extras`. Это значит, что audit-deps "
        f"не фильтрует [project.optional-dependencies] корректно, и cve-gate "
        f"будет падать на py3.14 wheels или metadata-incompatible extras."
    )


def test_make_cve_gate_passes() -> None:
    """End-to-end: `make cve-gate` ДОЛЖЕН проходить без уязвимостей.

    Это интеграционный regression test — гарантирует, что после
    пинов и изменения audit-deps recipe cve-gate остаётся зелёным.
    Требует ~30-60 сек.
    """
    proc = subprocess.run(
        ["make", "cve-gate"], capture_output=True, text=True, cwd=REPO
    )
    assert proc.returncode == 0, (
        f"`make cve-gate` failed (exit {proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout[-2000:]}\n"
        f"--- stderr ---\n{proc.stderr[-2000:]}"
    )
    assert "CVE gate passed" in proc.stdout or "CVE gate passed" in proc.stderr
