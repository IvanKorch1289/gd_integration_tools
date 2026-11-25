"""Unit tests for tools/checks/release_evidence.py (аудит 2026-11-20).

Manifest о готовности должен быть машинно-читаемым и честным: ``READY_RC``
возможен только при выполненных проверках, нулевых кодах возврата, чистом
рабочем дереве и отсутствии внешних блокеров. Отсутствие доказательств —
это блокер, а не успех.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.checks import release_evidence as evidence


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    """Временный git-репозиторий с одним коммитом (чистое дерево).

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Путь к корню репозитория.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=30)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=smoke@example.com",
            "-c",
            "user.name=smoke",
            "add",
            ".",
        ],
        cwd=repo,
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=smoke@example.com",
            "-c",
            "user.name=smoke",
            "commit",
            "-qm",
            "init",
        ],
        cwd=repo,
        check=True,
        timeout=30,
    )
    return repo


def _collect(repo: Path, **kwargs: object) -> evidence.EvidenceManifest:
    """Собрать manifest с дефолтами для тестов.

    Args:
        repo: Корень репозитория.
        **kwargs: Переопределения параметров.

    Returns:
        Готовый manifest.
    """
    params: dict[str, object] = {
        "root": repo,
        "profile": "test",
        "scopes": ["unit"],
        "commands": [],
        "artifacts": [],
        "blockers": [],
        "image": None,
        "image_digest": "sha256:" + "a" * 64,
        "log_dir": None,
        "run_commands": True,
        "attestation": "https://ghcr.io/example/attestation.sig",
    }
    params.update(kwargs)
    return evidence.collect_manifest(**params)  # type: ignore[arg-type]


class TestNormalizeCommand:
    """Подстановка интерпретатора."""

    def test_python_command_uses_current_interpreter(self) -> None:
        """``python ...`` выполняется тем же интерпретатором.

        Args:
            None.
        """
        import sys

        result = evidence._normalize_command("python tools/checks/x.py")
        assert result.startswith(sys.executable)
        assert result.endswith("tools/checks/x.py")

    def test_other_command_is_unchanged(self) -> None:
        """Прочие команды не переписываются.

        Args:
            None.
        """
        assert evidence._normalize_command("make lint") == "make lint"


class TestParsePair:
    """Разбор аргументов ``имя:значение``."""

    def test_valid_pair(self) -> None:
        """Пара разбирается.

        Args:
            None.
        """
        assert evidence._parse_pair("label:command here", ":", "проверки") == (
            "label",
            "command here",
        )

    def test_invalid_pair_raises(self) -> None:
        """Нет разделителя → ValueError.

        Args:
            None.
        """
        with pytest.raises(ValueError):
            evidence._parse_pair("no-separator", ":", "проверки")


class TestReleaseEvidenceAttestation:
    """ЭТАП 4: вердикт требует подтверждённый digest И attestation."""

    def test_missing_digest_blocks(self, clean_repo: Path) -> None:
        """Без подтверждённого digest'а образа вердикт — BLOCKED.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            image_digest=None,
            image=None,
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("digest" in reason for reason in manifest.verdict_reasons)

    def test_missing_attestation_blocks(self, clean_repo: Path) -> None:
        """Образ без attestation — BLOCKED (подписывать нечем).

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            attestation=None,
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("attestation" in reason for reason in manifest.verdict_reasons)

    def test_attestation_placeholder_is_treated_as_missing(
        self, clean_repo: Path
    ) -> None:
        """Плейсхолдер «n/a» = attestation не предъявлена → BLOCKED.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            attestation="n/a",
        )
        assert manifest.attestation == {}
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("attestation" in reason for reason in manifest.verdict_reasons)

    def test_attestation_for_another_image_blocks(self, clean_repo: Path) -> None:
        """Attestation чужого образа → BLOCKED.

        Свидетельство должно относиться к ТОМУ ЖЕ digest'у, что и образ в
        манифесте, иначе можно приложить свидетельство другого образа.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            attestation="ghcr.io/example/image@sha256:" + "b" * 64,
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("другому образу" in reason for reason in manifest.verdict_reasons)

    def test_attestation_file_is_hashed(self, clean_repo: Path, tmp_path: Path) -> None:
        """Attestation-файл попадает в manifest со sha256 и размером.

        Args:
            clean_repo: Временный репозиторий.
            tmp_path: Временный каталог.
        """
        predicate = tmp_path / "attestation.json"
        predicate.write_text('{"_type": "https://in-toto.io/Statement/v1"}\n')
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            attestation=str(predicate),
        )
        assert manifest.attestation["ref"] == str(predicate)
        assert len(manifest.attestation["sha256"]) == 64
        assert manifest.verdict == evidence.VERDICT_READY


class TestCollectManifest:
    """Правила вычисления вердикта."""

    def test_clean_tree_and_successful_command_is_ready(self, clean_repo: Path) -> None:
        """Все проверки зелёные, дерево чистое, блокеров нет → READY_RC.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo, commands=[("ok", f"{evidence.sys.executable} -c pass")]
        )
        assert manifest.verdict == evidence.VERDICT_READY
        assert manifest.verdict_reasons == []
        assert manifest.image_digest.startswith("sha256:")
        assert manifest.attestation["ref"]
        assert manifest.commands[0].exit_code == 0
        assert manifest.dirty is False
        assert len(manifest.sha) == 40

    def test_failed_command_blocks(self, clean_repo: Path) -> None:
        """Проверка с ненулевым кодом → BLOCKED с указанием проверки.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[
                ("broken", f"{evidence.sys.executable} -c 'raise SystemExit(3)'")
            ],
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("broken=3" in reason for reason in manifest.verdict_reasons)

    def test_no_commands_is_blocked(self, clean_repo: Path) -> None:
        """Нет выполненных проверок → BLOCKED (нет доказательств).

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(clean_repo, commands=[])
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("не выполнена" in reason for reason in manifest.verdict_reasons)

    def test_no_scope_is_blocked(self, clean_repo: Path) -> None:
        """Без объёма проверок вердикт нечитаем → BLOCKED.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            scopes=[],
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("test_scope" in reason for reason in manifest.verdict_reasons)

    def test_external_blocker_is_blocked(self, clean_repo: Path) -> None:
        """Внешний блокер → BLOCKED.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            blockers=[("skb-stand", "нет доступа к стенду")],
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert manifest.external_blockers == [
            {"name": "skb-stand", "reason": "нет доступа к стенду"}
        ]

    def test_dirty_tree_is_blocked(self, clean_repo: Path) -> None:
        """Грязное рабочее дерево → BLOCKED (артефакт невоспроизводим).

        Args:
            clean_repo: Временный репозиторий.
        """
        (clean_repo / "README.md").write_text("changed\n", encoding="utf-8")
        manifest = _collect(
            clean_repo, commands=[("ok", f"{evidence.sys.executable} -c pass")]
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert manifest.dirty is True
        assert any("не чистое" in reason for reason in manifest.verdict_reasons)

    def test_artifacts_are_hashed(self, clean_repo: Path) -> None:
        """Артефакты фиксируются с sha256 и размером.

        Args:
            clean_repo: Временный репозиторий.
        """
        artifact = clean_repo / "coverage.xml"
        artifact.write_text("<coverage/>", encoding="utf-8")
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            artifacts=[str(artifact)],
        )
        assert len(manifest.artifacts) == 1
        assert manifest.artifacts[0].bytes == len("<coverage/>")
        assert len(manifest.artifacts[0].sha256) == 64

    def test_missing_artifact_is_skipped(self, clean_repo: Path) -> None:
        """Отсутствующий артефакт не ломает сборку manifest'а.

        Args:
            clean_repo: Временный репозиторий.
        """
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c pass")],
            artifacts=[str(clean_repo / "missing.xml")],
        )
        assert manifest.artifacts == []
        assert manifest.verdict == evidence.VERDICT_READY

    def test_logs_are_written_and_hashed(
        self, clean_repo: Path, tmp_path: Path
    ) -> None:
        """Лог команды сохраняется, в manifest попадает его sha256.

        Args:
            clean_repo: Временный репозиторий.
            tmp_path: Временный каталог pytest.
        """
        log_dir = tmp_path / "logs"
        manifest = _collect(
            clean_repo,
            commands=[("ok", f"{evidence.sys.executable} -c 'print(\"marker\")'")],
            log_dir=log_dir,
        )
        command = manifest.commands[0]
        assert command.log_path is not None
        assert command.log_sha256 is not None
        assert "marker" in Path(command.log_path).read_text(encoding="utf-8")


class TestRecordedChecks:
    """Проверки, выполненные другим шагом CI (--record)."""

    def test_record_parsing_uses_last_equals(self) -> None:
        """Метка может содержать двоеточие: делим по последнему '='.

        Args:
            None.
        """
        assert evidence._parse_record("dist:uv build=success") == (
            "dist:uv build",
            "success",
        )

    def test_outcome_to_exit_code(self) -> None:
        """Outcome шага CI переводится в код возврата.

        Args:
            None.
        """
        assert evidence._outcome_to_exit_code("success") == 0
        assert evidence._outcome_to_exit_code("failure") == 1
        assert evidence._outcome_to_exit_code("skipped") is None
        assert evidence._outcome_to_exit_code("3") == 3

    def test_recorded_success_does_not_block(self, tmp_path) -> None:
        """Успешные зафиксированные проверки не блокируют вердикт.

        Args:
            tmp_path: Временный каталог.
        """
        manifest = evidence.collect_manifest(
            root=tmp_path,
            profile="release",
            scopes=["dist:uv build"],
            commands=[],
            artifacts=[],
            blockers=[],
            image=None,
            image_digest=None,
            log_dir=None,
            run_commands=False,
            recorded=[("dist:uv build", "success")],
        )
        assert manifest.recorded[0].exit_code == 0
        assert not any("неуспешна" in reason for reason in manifest.verdict_reasons)

    def test_recorded_failure_blocks(self, tmp_path) -> None:
        """Неуспешная зафиксированная проверка блокирует вердикт.

        Args:
            tmp_path: Временный каталог.
        """
        manifest = evidence.collect_manifest(
            root=tmp_path,
            profile="release",
            scopes=["dist:uv build"],
            commands=[],
            artifacts=[],
            blockers=[],
            image=None,
            image_digest=None,
            log_dir=None,
            run_commands=False,
            recorded=[("dist:uv build", "failure")],
        )
        assert manifest.verdict == evidence.VERDICT_BLOCKED
        assert any("неуспешна" in reason for reason in manifest.verdict_reasons)
