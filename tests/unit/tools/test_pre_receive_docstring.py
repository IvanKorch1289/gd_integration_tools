# ruff: noqa: S101, S603, S607
"""Тесты server-side pre-receive docstring-gate.

Wave: [wave:s8/k1-pre-receive-docstring]

Покрывают:

* успешный push (все публичные def/class документированы);
* push с публичной функцией без docstring (fail);
* push, где все изменения вне scope (skip без вызова чекера);
* zero-rev для новой ветки (берёт ``git rev-list --not --all``);
* интеграцию ``--files -`` режима ``check_docstrings.py``.

Тесты создают изолированный bare-репозиторий + рабочую копию во
временной директории и реально вызывают bash-hook через subprocess.
Это даёт high-fidelity покрытие STDIN-контракта git pre-receive.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOOK_PATH = PROJECT_ROOT / "tools" / "git_hooks" / "pre-receive"
CHECKER_PATH = PROJECT_ROOT / "tools" / "check_docstrings.py"

# Минимальный набор файлов docstring-чекера, который копируется в sandbox
# рабочую копию: сам чекер + allowlist (пустой allowlist для теста).
CHECKER_ARTEFACTS = [
    Path("tools") / "check_docstrings.py",
    Path("tools") / "check_docstrings_allowlist.txt",
]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Запускает git в указанной директории и возвращает stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"git {' '.join(args)} failed: {proc.stderr}"
        raise RuntimeError(msg)
    return proc.stdout


def _git_env(repo: Path) -> dict[str, str]:
    """Минимальное окружение git с фиксированным author/committer."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    return env


def _seed_workdir_with_checker(workdir: Path) -> None:
    """Копирует docstring-чекер и пустой allowlist в sandbox-копию проекта.

    Хук вызывает ``python tools/check_docstrings.py``, поэтому workdir,
    указанный через ``GD_PROJECT_DIR``, должен содержать актуальный CLI.
    """
    for rel in CHECKER_ARTEFACTS:
        target = workdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.name == "check_docstrings_allowlist.txt":
            # Используем пустой allowlist, чтобы амнистия baseline не
            # маскировала тестовые нарушения.
            target.write_text("", encoding="utf-8")
        else:
            shutil.copy2(PROJECT_ROOT / rel, target)


def _make_python_file(path: Path, *, with_doc: bool) -> None:
    """Создаёт минимальный *.py с публичной функцией ± docstring."""
    if with_doc:
        body = (
            '"""Module docstring."""\n\n'
            "def public_function(x: int) -> int:\n"
            '    """Возвращает удвоенное значение."""\n'
            "    return x * 2\n"
        )
    else:
        body = (
            '"""Module docstring."""\n\n'
            "def public_function(x: int) -> int:\n"
            "    return x * 2\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[dict[str, Path]]:
    """Готовит изолированный workdir + список путей для теста.

    Не создаёт git-репозиторий — это ответственность каждого теста, чтобы
    можно было собрать разные сценарии (zero-rev, обычный diff, удаление).
    """
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    _seed_workdir_with_checker(workdir)
    yield {"workdir": workdir, "tmp": tmp_path}


def _run_hook(
    workdir: Path, stdin_payload: str, *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Запускает pre-receive hook с переданным STDIN.

    ``workdir`` — каталог с tools/check_docstrings.py (передаётся через
    ``GD_PROJECT_DIR``). ``cwd`` — рабочая директория для самого hook'а
    (по умолчанию совпадает с workdir; для bare-репозитория нужно
    указывать сам bare-каталог, как делает git-сервер).
    """
    env = os.environ.copy()
    env["GD_PROJECT_DIR"] = str(workdir)
    env["GD_PYTHON_BIN"] = sys.executable
    return subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=stdin_payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or workdir),
        check=False,
    )


def _make_bare_repo(tmp_path: Path) -> Path:
    """Создаёт bare-репозиторий — имитация git-сервера."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare"], cwd=str(bare), capture_output=True, check=True
    )
    return bare


def _push_and_run_hook(
    *, workdir: Path, bare: Path, refspec: str, expected_old: str, expected_new: str
) -> subprocess.CompletedProcess[str]:
    """Эмулирует pre-receive: формирует payload вручную и вызывает hook.

    Pre-receive в реальности запускается git-сервером с PWD = bare-репо,
    и его cwd содержит только git-метаданные (не рабочее дерево). Hook
    обращается к ``GD_PROJECT_DIR`` для CLI чекера и к git-репозиторию
    через стандартное окружение git'а.

    Чтобы избежать зависимости от реального push-event'а (который
    непросто перехватить программно с проверкой stdin'а), мы:

    1. Пушим коммиты в bare-репо обычным ``git push``.
    2. Затем вызываем hook вручную из bare-каталога с известным payload'ом.

    Это даёт корректный ``--not --all`` semantics: ref ``refs/heads/main``
    в bare-репо уже обновлён, но мы передаём в hook payload так же,
    как git делает на реальном сервере.
    """
    env = _git_env(workdir)
    # Push всех веток в bare. На сервере ref ещё не обновлён в момент
    # pre-receive; но для теста мы интересуемся, что hook делает с
    # переданным payload'ом, а не воспроизводим точный момент диспетчеризации.
    subprocess.run(
        ["git", "push", "--mirror", str(bare)],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    payload = f"{expected_old} {expected_new} {refspec}\n"
    return _run_hook(workdir, payload, cwd=bare)


# --------------------------------------------------------------------------- #
# Sanity                                                                      #
# --------------------------------------------------------------------------- #
def test_hook_exists_and_executable() -> None:
    """Hook присутствует и имеет exec-бит."""
    assert HOOK_PATH.is_file(), f"hook не найден: {HOOK_PATH}"
    assert os.access(HOOK_PATH, os.X_OK), "hook не исполняемый (chmod +x)"


def test_hook_passes_bash_syntax() -> None:
    """``bash -n`` (no-op syntax check) не падает."""
    proc = subprocess.run(
        ["bash", "-n", str(HOOK_PATH)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------- #
# CLI --files режим                                                           #
# --------------------------------------------------------------------------- #
def test_cli_files_mode_passes_for_documented(tmp_path: Path) -> None:
    """``--files`` принимает явный список и не падает на документированном."""
    target = tmp_path / "ok.py"
    _make_python_file(target, with_doc=True)
    proc = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "--strict", "--files", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_files_mode_fails_for_missing_docstring(tmp_path: Path) -> None:
    """``--files --strict`` ловит публичную функцию без docstring."""
    target = tmp_path / "bad.py"
    _make_python_file(target, with_doc=False)
    proc = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "--strict", "--files", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    # S59 W1: typer+rich uses stderr (console_err) for violations.
    assert "public_function" in proc.stderr or "public_function" in proc.stdout


def test_cli_files_mode_reads_stdin(tmp_path: Path) -> None:
    """``--files -`` принимает список путей со stdin."""
    target = tmp_path / "ok.py"
    _make_python_file(target, with_doc=True)
    proc = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "--strict", "--files", "-"],
        input=str(target) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_files_mode_requires_input() -> None:
    """Без paths и без --files CLI отвечает usage-error (exit 2)."""
    proc = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "paths" in proc.stderr or "--files" in proc.stderr


# --------------------------------------------------------------------------- #
# Pre-receive hook сценарии                                                   #
# --------------------------------------------------------------------------- #
def test_push_with_documented_file_passes(sandbox: dict[str, Path]) -> None:
    """Push с документированной функцией в scope — exit 0."""
    workdir = sandbox["workdir"]
    env = _git_env(workdir)
    _git(workdir, "init", "--initial-branch=main", env=env)

    target_rel = Path("src") / "backend" / "core" / "demo.py"
    _make_python_file(workdir / target_rel, with_doc=True)
    _git(workdir, "add", str(target_rel), env=env)
    _git(workdir, "commit", "-m", "add demo", env=env)

    old = "0" * 40
    new = _git(workdir, "rev-parse", "HEAD", env=env).strip()
    payload = f"{old} {new} refs/heads/main\n"

    proc = _run_hook(workdir, payload)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_push_without_docstring_fails(sandbox: dict[str, Path]) -> None:
    """Push с публичной функцией без docstring в scope — exit 1."""
    workdir = sandbox["workdir"]
    env = _git_env(workdir)
    _git(workdir, "init", "--initial-branch=main", env=env)

    target_rel = Path("src") / "backend" / "core" / "bad.py"
    _make_python_file(workdir / target_rel, with_doc=False)
    _git(workdir, "add", str(target_rel), env=env)
    _git(workdir, "commit", "-m", "add bad", env=env)

    old = "0" * 40
    new = _git(workdir, "rev-parse", "HEAD", env=env).strip()
    payload = f"{old} {new} refs/heads/main\n"

    proc = _run_hook(workdir, payload)
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "Push отклонён" in combined
    assert "bad.py" in combined or "public_function" in combined


def test_push_outside_scope_skips_check(sandbox: dict[str, Path]) -> None:
    """Изменения вне ``src/backend/core/**`` etc — gate пропускается."""
    workdir = sandbox["workdir"]
    env = _git_env(workdir)
    _git(workdir, "init", "--initial-branch=main", env=env)

    # Файл вне scope — даже без docstring не должен блокировать push.
    out_of_scope = Path("src") / "backend" / "services" / "demo.py"
    _make_python_file(workdir / out_of_scope, with_doc=False)
    _git(workdir, "add", str(out_of_scope), env=env)
    _git(workdir, "commit", "-m", "add out-of-scope", env=env)

    old = "0" * 40
    new = _git(workdir, "rev-parse", "HEAD", env=env).strip()
    payload = f"{old} {new} refs/heads/main\n"

    proc = _run_hook(workdir, payload)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Ожидаем сообщение про "вне scope" или "Нет защищённых .py-файлов".
    combined = proc.stdout + proc.stderr
    assert "вне scope" in combined or "Нет защищённых" in combined, combined


def test_push_new_branch_zero_rev(sandbox: dict[str, Path]) -> None:
    """Zero-rev (новая ветка) → diff через ``git rev-list --not --all``.

    Сценарий: на main есть документированный файл; в новой ветке добавляется
    публичная функция без docstring. Hook должен увидеть только новый
    коммит ветки и упасть с exit 1.
    """
    workdir = sandbox["workdir"]
    env = _git_env(workdir)
    _git(workdir, "init", "--initial-branch=main", env=env)

    # main: документированный файл (попадёт в --not --all → исключится).
    main_rel = Path("src") / "backend" / "core" / "ok.py"
    _make_python_file(workdir / main_rel, with_doc=True)
    _git(workdir, "add", str(main_rel), env=env)
    _git(workdir, "commit", "-m", "main: ok", env=env)

    # Новая ветка с нарушением.
    _git(workdir, "checkout", "-b", "feature/bad", env=env)
    bad_rel = Path("src") / "backend" / "dsl" / "engine" / "bad.py"
    _make_python_file(workdir / bad_rel, with_doc=False)
    _git(workdir, "add", str(bad_rel), env=env)
    _git(workdir, "commit", "-m", "feature: bad", env=env)

    old = "0" * 40
    new = _git(workdir, "rev-parse", "HEAD", env=env).strip()
    payload = f"{old} {new} refs/heads/feature/bad\n"

    proc = _run_hook(workdir, payload)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "bad.py" in combined or "public_function" in combined


def test_push_branch_deletion_skips(sandbox: dict[str, Path]) -> None:
    """Удаление ветки (newrev = zero) — exit 0 без проверок."""
    workdir = sandbox["workdir"]
    env = _git_env(workdir)
    _git(workdir, "init", "--initial-branch=main", env=env)

    # Нужен хотя бы один коммит, чтобы oldrev был валидный SHA.
    target_rel = Path("src") / "backend" / "core" / "ok.py"
    _make_python_file(workdir / target_rel, with_doc=True)
    _git(workdir, "add", str(target_rel), env=env)
    _git(workdir, "commit", "-m", "init", env=env)

    old = _git(workdir, "rev-parse", "HEAD", env=env).strip()
    new = "0" * 40
    payload = f"{old} {new} refs/heads/feature/old\n"

    proc = _run_hook(workdir, payload)
    assert proc.returncode == 0, proc.stdout + proc.stderr
