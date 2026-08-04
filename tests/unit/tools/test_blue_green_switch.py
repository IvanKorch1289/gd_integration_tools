"""Targeted-тесты для ``cmd_switch`` в ``tools/blue_green.sh`` (Sprint 6 Devops 3).

Проверяет логику переключения nginx-router без actual ``docker exec``
(все docker-вызовы подменяются mock-скриптом через PATH):

* ``test_invalid_target_rejected`` — switch red → die, state не создан.
* ``test_noop_when_target_matches_state`` — switch на текущий stack →
  exit 0, docker не вызывается.
* ``test_dry_run_when_docker_missing`` — docker отсутствует в PATH →
  state обновляется, exit 0, reload не выполняется.
* ``test_dry_run_when_container_unavailable`` — ``docker inspect``
  возвращает non-zero → dry-run fallback (state обновлён, ``nginx -t``
  / ``nginx -s reload`` НЕ вызываются).
* ``test_reload_success_updates_state`` — все docker-вызовы успешны →
  state обновляется, вызовы идут в правильном порядке
  (inspect → exec nginx -t → exec nginx -s reload).
* ``test_reload_failure_keeps_state`` — ``nginx -t`` падает → state
  НЕ обновляется, exit non-zero, ``nginx -s reload`` НЕ вызывается
  (fail-closed для rollback).

Используется copy-script-in-tmp подход: STATE_FILE и PROJECT_ROOT
резолвятся относительно ``BASH_SOURCE`` (SCRIPT_DIR), поэтому копия
скрипта в ``tmp_path`` даёт изолированный state без env-overrides
и не трогает боевой ``.blue_green.state``.

Honest scope: 6 тестов покрывают все branch'и ``cmd_switch`` (Sprint 6
DoD). E2E с реальным nginx — отдельный sub-task (см. ADR-0060).
"""

# ruff: noqa: S101, S603, S607

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_SRC = PROJECT_ROOT / "tools" / "blue_green.sh"
NGINX_CONTAINER = "gd-nginx-router"


def _install_script(tmp_path: Path) -> Path:
    """Скопировать ``blue_green.sh`` в ``tmp_path/tools/`` с executable bit.

    Скрипт вычисляет ``PROJECT_ROOT`` как ``cd $SCRIPT_DIR/..`` (см.
    ``tools/blue_green.sh``), поэтому копия должна лежать на один
    уровень глубже ``tmp_path`` — иначе state-файл уйдёт в parent
    директорию. ``tmp_path/tools/blue_green.sh`` → PROJECT_ROOT ==
    ``tmp_path`` → STATE_FILE == ``tmp_path/.blue_green.state``.
    """
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(exist_ok=True)
    dst = tools_dir / "blue_green.sh"
    shutil.copy2(SCRIPT_SRC, dst)
    mode = dst.stat().st_mode
    dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def _make_mock_docker(
    tmp_path: Path,
    *,
    container_available: bool,
    nginx_t_ok: bool,
    nginx_reload_ok: bool,
) -> Path:
    """Создать ``bin/`` с mock-скриптом ``docker`` для подмены в PATH.

    Управляемые exit codes:
    * ``docker inspect <container>`` — 0 если container_available, иначе 1.
    * ``docker exec ... nginx -t`` — 0 если nginx_t_ok, иначе 1.
    * ``docker exec ... nginx -s reload`` — 0 если nginx_reload_ok, иначе 1.

    Каждый вызов логируется в ``tmp_path/docker_calls.log`` (для assert'ов
    на порядок и факт вызова).
    """
    bin_dir = tmp_path / "mock_bin"
    bin_dir.mkdir()
    log_file = tmp_path / "docker_calls.log"
    docker = bin_dir / "docker"

    inspect_rc = 0 if container_available else 1
    t_rc = 0 if nginx_t_ok else 1
    reload_rc = 0 if nginx_reload_ok else 1

    docker.write_text(
        dedent(f"""\
            #!/usr/bin/env bash
            # Mock docker для тестов cmd_switch (Sprint 6 Devops 3).
            printf '%s\\n' "$*" >> "{log_file}"
            case "$1" in
                inspect)
                    exit {inspect_rc}
                    ;;
                exec)
                    if [[ "$3" == "nginx" && "$4" == "-t" ]]; then
                        exit {t_rc}
                    elif [[ "$3" == "nginx" && "$4" == "-s" && "$5" == "reload" ]]; then
                        exit {reload_rc}
                    fi
                    exit 0
                    ;;
            esac
            exit 0
        """),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return bin_dir


def _run_switch(
    tmp_path: Path,
    target: str,
    *,
    mock_bin: Path | None = None,
    initial_state: str | None = None,
    docker_in_path: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Запустить ``switch <target>`` в изолированной tmp_path.

    State-файл идёт в ``tmp_path/.blue_green.state`` (см. SCRIPT_DIR
    resolution в ``blue_green.sh``). PATH настраивается через ``mock_bin``
    или обрезается до ``/usr/bin:/bin`` для negative-сценария.
    """
    script = _install_script(tmp_path)
    state_file = tmp_path / ".blue_green.state"
    if initial_state is not None:
        state_file.write_text(initial_state, encoding="utf-8")

    env: Mapping[str, str] = os.environ.copy()
    path = env.get("PATH", "/usr/bin:/bin")
    if mock_bin is not None and docker_in_path:
        env = {**env, "PATH": f"{mock_bin}{os.pathsep}{path}"}
    elif not docker_in_path:
        # Минимальный PATH без docker для negative-сценария.
        env = {**env, "PATH": "/usr/bin:/bin"}

    return subprocess.run(
        ["bash", str(script), "switch", target],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )


def _read_state(tmp_path: Path) -> str | None:
    """Прочитать ``.blue_green.state`` или ``None`` если отсутствует."""
    state_file = tmp_path / ".blue_green.state"
    if not state_file.exists():
        return None
    return state_file.read_text(encoding="utf-8")


def _docker_calls(tmp_path: Path) -> str:
    """Вернуть содержимое mock-docker call log (пустая строка если нет)."""
    log = tmp_path / "docker_calls.log"
    if not log.exists():
        return ""
    return log.read_text(encoding="utf-8")


class TestCmdSwitch:
    """Целевые сценарии для ``cmd_switch`` (Sprint 6 Devops 3)."""

    def test_invalid_target_rejected(self, tmp_path: Path) -> None:
        """``target`` не blue/green → die, state не создан."""
        result = _run_switch(tmp_path, "red")
        assert result.returncode != 0
        assert "target must be blue or green" in result.stderr
        assert _read_state(tmp_path) is None

    def test_noop_when_target_matches_state(self, tmp_path: Path) -> None:
        """Switch на текущий stack → exit 0, state не меняется, docker не вызывается."""
        mock_bin = _make_mock_docker(
            tmp_path, container_available=True, nginx_t_ok=True, nginx_reload_ok=True
        )
        result = _run_switch(
            tmp_path, "green", mock_bin=mock_bin, initial_state="green"
        )
        assert result.returncode == 0
        assert "no-op" in result.stderr
        assert _read_state(tmp_path) == "green"
        # No-op ветка не должна вызывать docker.
        assert _docker_calls(tmp_path) == ""

    def test_dry_run_when_docker_missing(self, tmp_path: Path) -> None:
        """docker отсутствует в PATH → dry-run fallback: state обновлён, exit 0."""
        result = _run_switch(
            tmp_path, "green", docker_in_path=False, initial_state="blue"
        )
        assert result.returncode == 0
        assert _read_state(tmp_path) == "green"
        assert "dry-run" in result.stderr

    def test_dry_run_when_container_unavailable(self, tmp_path: Path) -> None:
        """``docker inspect`` падает → dry-run: state обновлён, nginx exec НЕ вызван."""
        mock_bin = _make_mock_docker(
            tmp_path, container_available=False, nginx_t_ok=True, nginx_reload_ok=True
        )
        result = _run_switch(tmp_path, "green", mock_bin=mock_bin, initial_state="blue")
        assert result.returncode == 0
        assert _read_state(tmp_path) == "green"
        assert "dry-run" in result.stderr
        # nginx exec НЕ должен вызываться (early-return после inspect).
        log = _docker_calls(tmp_path)
        assert "inspect gd-nginx-router" in log
        assert "exec" not in log

    def test_reload_success_updates_state(self, tmp_path: Path) -> None:
        """Полный success path: state обновляется, вызовы в правильном порядке."""
        mock_bin = _make_mock_docker(
            tmp_path, container_available=True, nginx_t_ok=True, nginx_reload_ok=True
        )
        result = _run_switch(tmp_path, "green", mock_bin=mock_bin, initial_state="blue")
        assert result.returncode == 0
        assert _read_state(tmp_path) == "green"
        assert "nginx reloaded" in result.stderr
        # Порядок: inspect → exec nginx -t → exec nginx -s reload.
        log = _docker_calls(tmp_path)
        lines = [line for line in log.splitlines() if line]
        assert len(lines) == 3, f"expected 3 docker calls, got: {lines!r}"
        assert "inspect gd-nginx-router" in lines[0]
        assert "nginx -t" in lines[1]
        assert "nginx -s reload" in lines[2]

    def test_reload_failure_keeps_state(self, tmp_path: Path) -> None:
        """``nginx -t`` падает → state НЕ обновляется, exit non-zero (fail-closed)."""
        mock_bin = _make_mock_docker(
            tmp_path, container_available=True, nginx_t_ok=False, nginx_reload_ok=True
        )
        result = _run_switch(tmp_path, "green", mock_bin=mock_bin, initial_state="blue")
        assert result.returncode != 0
        assert _read_state(tmp_path) == "blue", (
            "fail-closed: state MUST NOT change when nginx -t fails"
        )
        assert "nginx reload failed" in result.stderr
        # ``nginx -s reload`` НЕ вызывается (short-circuit на -t).
        log = _docker_calls(tmp_path)
        assert "nginx -s reload" not in log
