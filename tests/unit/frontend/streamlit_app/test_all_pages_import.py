"""Регресс-гейт: все страницы портала импортируются без исключений.

Контекст (найдено в ходе фронт-аудита)
--------------------------------------
До S174 часть страниц падала **при каждой загрузке**:

* ``41_Поиск.py`` и ``16_Воркфлоу.py`` —
  ``st.session_state.get("...", "", key="...")`` → ``TypeError: Mapping.get()
  got multiple values for argument 'key'`` (``SessionStateProxy`` не
  переопределяет ``get``, ``key=`` — лишний аргумент);
* ``21_AI_Обратная_связь.py`` — ``st.number_input(value=1000, max_value=1)``
  → ``StreamlitValueAboveMaxError``;
* ``11/12/16/56/65/66/67/71/80/85_*.py`` и др. — 401 от backend поднимался
  как ``PermissionError``, а страницы ловили ``httpx.HTTPError`` (или узкий
  набор без ``PermissionError``) → пользователь видел traceback.

Гейт импортирует каждый модуль страницы при «backend отвечает 401» и
требует, чтобы ни одно исключение не дошло до пользователя.

Прогон идёт в **отдельном подпроцессе**: другие тесты фронт-зоны подменяют
``sys.modules['streamlit']`` моками, и в общем процессе pytest результат
зависел бы от порядка запуска. Подпроцесс даёт чистый ``sys.modules``.

Известное исключение — ``altair 5.5.0`` использует ``TypedDict(closed=True)``
(Python 3.15+), тогда как проект закреплён на Python 3.14 → любой chart-API
Streamlit падает. Это дефект зависимости (пин altair), не кода портала;
такой случай считается SKIPPED с указанием причины.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Harness, исполняемый в отдельном процессе (чистый sys.modules).
_HARNESS = '''
"""Импорт всех модулей страниц при backend, отвечающем 401."""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import sys
import traceback
import warnings
from pathlib import Path

ROOT = Path(os.environ["FRONTEND_IMPORT_REPO_ROOT"])
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

import httpx
import streamlit as st
from streamlit.runtime.scriptrunner_utils.exceptions import StopException

from src.frontend.streamlit_app.api_clients.base import UnauthorizedError


def _identity_cache(fn=None, **_kwargs):
    if fn is not None:
        return fn

    def deco(inner):
        return inner

    return deco


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __call__(self, *_a, **_kw):
        return self


def _unauthorized(*_args, **_kwargs):
    request = httpx.Request("GET", "http://localhost:8000/api/v1/test")
    response = httpx.Response(401, request=request)
    raise UnauthorizedError(
        "Unauthorized: /api/v1/test", request=request, response=response
    )


st.cache_data = _identity_cache
st.cache_resource = _identity_cache
st.spinner = _NullCtx()
st.set_page_config = lambda **_kwargs: None
httpx.Client.request = _unauthorized
httpx.Client.send = _unauthorized
httpx.AsyncClient.request = _unauthorized
httpx.AsyncClient.send = _unauthorized


def _stop():
    raise StopException()


st.stop = _stop

PAGES_DIR = ROOT / "src" / "frontend" / "streamlit_app" / "pages"


def _is_altair(exc):
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        frames.append(tb.tb_frame.f_code.co_filename)
        tb = tb.tb_next
    return any("altair" in frame for frame in frames)


def _is_missing_optional_dependency(exc):
    """Отсутствует ОПЦИОНАЛЬНЫЙ внешний пакет (не проектный модуль).

    polars/pyarrow и подобные живут в тяжёлых extras, которые CI не ставит.
    Такое отсутствие — не дефект страницы, поэтому страница считается
    пропущенной, а не упавшей. ModuleNotFoundError на проектный модуль
    (src.*, extensions.*) остаётся ошибкой.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return False
    name = getattr(exc, "name", "") or ""
    if not name:
        return False
    return name.split(".")[0] not in ("src", "extensions")


def main() -> int:
    pages = sorted(PAGES_DIR.rglob("*.py"))
    ok = 0
    altair = 0
    failures = []
    optional_skipped = 0
    devnull = open(os.devnull, "w")
    old = sys.stderr
    sys.stderr = devnull
    try:
        for path in pages:
            rel = path.relative_to(PAGES_DIR).with_suffix("")
            name = "_page_" + "__".join(rel.parts)
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    spec.loader.exec_module(module)
                ok += 1
            except StopException:
                ok += 1
            except BaseException as exc:
                if _is_altair(exc):
                    altair += 1
                elif _is_missing_optional_dependency(exc):
                    # Отсутствующий ОПЦИОНАЛЬНЫЙ пакет (polars и т.п. живут
                    # в тяжёлых extras) — не дефект страницы: страница
                    # импортируется в окружении, где этого пакета нет.
                    # Ошибки импорта проектных модулей сюда не попадают.
                    optional_skipped += 1
                else:
                    buf = io.StringIO()
                    traceback.print_exception(
                        type(exc), exc, exc.__traceback__, file=buf
                    )
                    failures.append((str(path.relative_to(ROOT)), buf.getvalue()))
            finally:
                sys.modules.pop(name, None)
    finally:
        sys.stderr = old
        devnull.close()

    print(
        f"TOTAL={len(pages)} OK={ok} ALTAIR_SKIPPED={altair} "
        f"OPTIONAL_SKIPPED={optional_skipped} FAIL={len(failures)}"
    )
    for rel, tb in failures:
        print("=" * 70)
        print("FAIL:", rel)
        print(tb)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


@pytest.mark.unit
def test_optional_dependency_detector_distinguishes_project_modules() -> None:
    """Отсутствие внешнего пакета — не ошибка; отсутствие модуля проекта — ошибка.

    Проверяет логику harness'а: страница, требующая polars/pyarrow (тяжёлые
    extras), в CI-окружении без них считается пропущенной, а реальный
    ModuleNotFoundError на проектный модуль остаётся падением.
    """
    harness_ns: dict[str, object] = {"__name__": "harness_probe"}
    # Harness читает корень репозитория из env — задаём его на время exec'а.
    previous = os.environ.get("FRONTEND_IMPORT_REPO_ROOT")
    os.environ["FRONTEND_IMPORT_REPO_ROOT"] = str(REPO_ROOT)
    try:
        exec(  # noqa: S102 — исполняем текст harness'а, чтобы проверить его же
            compile(_HARNESS, "harness", "exec"), harness_ns
        )
    finally:
        if previous is None:
            os.environ.pop("FRONTEND_IMPORT_REPO_ROOT", None)
        else:
            os.environ["FRONTEND_IMPORT_REPO_ROOT"] = previous
    check = harness_ns["_is_missing_optional_dependency"]
    assert callable(check)

    def _missing(name: str) -> ModuleNotFoundError:
        exc = ModuleNotFoundError(f"No module named '{name}'")
        exc.name = name
        return exc

    assert check(_missing("polars")) is True
    assert check(_missing("pyarrow")) is True
    assert check(_missing("src.backend.core.auth")) is False
    assert check(_missing("extensions.orders")) is False
    assert check(ValueError("boom")) is False


@pytest.mark.unit
def test_all_page_modules_import_without_error(tmp_path: Path) -> None:
    """Ни одна страница не падает при импорте (backend отвечает 401)."""
    harness = tmp_path / "page_import_harness.py"
    harness.write_text(_HARNESS, encoding="utf-8")

    proc = subprocess.run(  # noqa: S603 — фиксированный путь, без shell
        [sys.executable, str(harness)],
        cwd=str(REPO_ROOT),
        env={**os.environ, "FRONTEND_IMPORT_REPO_ROOT": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert "TOTAL=" in proc.stdout, (
        f"harness не отработал:\nstdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"
    )
    summary = proc.stdout.split("TOTAL=", 1)[1].splitlines()[0]
    assert "FAIL=0" in summary, (
        "страницы падают при импорте:\n"
        f"{summary}\n{proc.stdout[proc.stdout.find('FAIL:') :][:4000]}"
    )
