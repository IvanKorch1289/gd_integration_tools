"""Focused tests for ``core.file_safety`` (Wave 1 P0 #37-#39)."""

from __future__ import annotations

import json

import pytest

from src.backend.core.file_safety import (
    AtomicHandoff,
    FileManifest,
    FileSafetyService,
    QuarantineDecision,
    QuarantinePolicy,
    QuarantineResult,
    get_file_safety_service,
)
from src.backend.core.file_safety.manifest import compute_sha256
from src.backend.core.file_safety.quarantine import reset_file_safety_service


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_file_safety_service()


class TestComputeSha256:
    def test_compute_sha256(self) -> None:
        h = compute_sha256(b"hello")
        # SHA-256 of "hello".
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_compute_sha256_empty(self) -> None:
        h = compute_sha256(b"")
        # SHA-256 of empty.
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestFileManifest:
    def test_defaults(self) -> None:
        m = FileManifest(
            file_id="f1",
            hash_sha256="abc",
            size_bytes=100,
        )
        assert m.filename == ""
        assert m.source == ""
        assert m.tenant_id == ""
        assert m.classification == "internal"
        assert m.trace_id == ""
        assert m.created_at == ""
        assert m.attributes == {}

    def test_to_dict(self) -> None:
        m = FileManifest(
            file_id="f1",
            hash_sha256="abc",
            size_bytes=100,
            filename="report.pdf",
            source="upload-api",
            tenant_id="t1",
        )
        d = m.to_dict()
        assert d["file_id"] == "f1"
        assert d["filename"] == "report.pdf"
        assert d["tenant_id"] == "t1"

    def test_to_dict_full(self) -> None:
        m = FileManifest(
            file_id="f1",
            hash_sha256="abc",
            size_bytes=100,
            attributes={"uploader": "alice"},
        )
        d = m.to_dict()
        assert d["attributes"] == {"uploader": "alice"}


class TestFileSafetyServiceInit:
    def test_init_default(self) -> None:
        svc = FileSafetyService()
        assert svc.staging_dir.exists()

    def test_init_custom_staging(self, tmp_path) -> None:
        custom = tmp_path / "my_staging"
        svc = FileSafetyService(staging_dir=str(custom))
        assert svc.staging_dir == custom


class TestCreateManifest:
    def test_basic(self) -> None:
        svc = FileSafetyService()
        m = svc.create_manifest(content=b"hello world")
        assert m.size_bytes == 11
        assert m.hash_sha256 == compute_sha256(b"hello world")
        assert m.file_id  # UUID generated

    def test_with_metadata(self) -> None:
        svc = FileSafetyService()
        m = svc.create_manifest(
            content=b"x",
            filename="test.txt",
            source="upload",
            tenant_id="t1",
            classification="confidential",
            trace_id="trace-abc",
            attributes={"key": "value"},
        )
        assert m.filename == "test.txt"
        assert m.tenant_id == "t1"
        assert m.classification == "confidential"
        assert m.trace_id == "trace-abc"
        assert m.attributes == {"key": "value"}


class TestStageFile:
    def test_stage_file(self, tmp_path) -> None:
        svc = FileSafetyService(staging_dir=str(tmp_path / "stage"))
        staged = svc.stage_file(content=b"test", filename="f.txt")
        assert staged.exists()
        assert staged.read_bytes() == b"test"
        assert "f.txt" in staged.name

    def test_stage_unique_names(self, tmp_path) -> None:
        svc = FileSafetyService(staging_dir=str(tmp_path / "stage"))
        s1 = svc.stage_file(content=b"x", filename="f.txt")
        s2 = svc.stage_file(content=b"x", filename="f.txt")
        assert s1 != s2


class TestQuarantinePolicy:
    def test_defaults(self) -> None:
        p = QuarantinePolicy()
        assert p.max_size_bytes == 100 * 1024 * 1024
        assert "application/pdf" in p.allowed_mime_types
        assert p.require_av_scan is False
        assert p.reject_on_size_exceeded is True

    def test_custom(self) -> None:
        p = QuarantinePolicy(
            max_size_bytes=1024,
            allowed_mime_types=("text/plain",),
            require_av_scan=True,
            pii_detection_enabled=True,
        )
        assert p.max_size_bytes == 1024
        assert p.allowed_mime_types == ("text/plain",)
        assert p.require_av_scan is True


class TestQuarantineResult:
    def test_defaults(self) -> None:
        r = QuarantineResult(decision=QuarantineDecision.RELEASE)
        assert r.manifest is None
        assert r.reasons == []
        assert r.policy is None


class TestQuarantineDecisionEnum:
    def test_values(self) -> None:
        assert QuarantineDecision.RELEASE.value == "release"
        assert QuarantineDecision.QUARANTINE.value == "quarantine"
        assert QuarantineDecision.REJECT.value == "reject"


class TestAtomicHandoffPromote:
    def test_promote(self, tmp_path) -> None:
        staged = tmp_path / "staged.txt"
        staged.write_bytes(b"content")
        target_dir = tmp_path / "consumer"

        final = AtomicHandoff.promote(
            staged_path=staged,
            target_dir=target_dir,
            target_filename="final.txt",
        )
        assert final.exists()
        assert final.name == "final.txt"
        assert final.read_bytes() == b"content"
        # Staged moved (rename), no longer exists.
        assert not staged.exists()

    def test_promote_default_filename(self, tmp_path) -> None:
        staged = tmp_path / "staged_name.txt"
        staged.write_bytes(b"x")
        target_dir = tmp_path / "consumer"

        final = AtomicHandoff.promote(
            staged_path=staged,
            target_dir=target_dir,
        )
        assert final.name == "staged_name.txt"

    def test_promote_missing_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            AtomicHandoff.promote(
                staged_path=tmp_path / "missing.txt",
                target_dir=tmp_path / "out",
            )

    def test_promote_creates_target_dir(self, tmp_path) -> None:
        staged = tmp_path / "staged.txt"
        staged.write_bytes(b"x")
        target = tmp_path / "deep" / "nested" / "dir"
        final = AtomicHandoff.promote(staged_path=staged, target_dir=target)
        assert target.exists()
        assert final.exists()


class TestAtomicHandoffVerifyChecksum:
    def test_verify_checksum_correct(self, tmp_path) -> None:
        content = b"test data"
        path = tmp_path / "f.txt"
        path.write_bytes(content)
        expected = compute_sha256(content)
        assert AtomicHandoff.verify_checksum(path=path, expected_sha256=expected) is True

    def test_verify_checksum_mismatch(self, tmp_path) -> None:
        path = tmp_path / "f.txt"
        path.write_bytes(b"test data")
        assert AtomicHandoff.verify_checksum(path=path, expected_sha256="wrong") is False


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_file_safety_service()
        s2 = get_file_safety_service()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_file_safety_service()
        reset_file_safety_service()
        s2 = get_file_safety_service()
        assert s1 is not s2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import file_safety

        assert len(file_safety.__all__) == 7


class TestRealisticExample:
    def test_full_lifecycle(self, tmp_path) -> None:
        """Full upload flow: stage → manifest → atomic promote → verify."""
        svc = FileSafetyService(staging_dir=str(tmp_path / "staging"))
        target_dir = tmp_path / "consumer_inbox"

        # 1. Stage file (simulating upload).
        content = b"PDF binary content here"
        staged = svc.stage_file(content=content, filename="report.pdf")
        assert staged.exists()

        # 2. Create manifest.
        manifest = svc.create_manifest(
            content=content,
            filename="report.pdf",
            source="upload-api",
            tenant_id="tenant-1",
            classification="confidential",
            trace_id="trace-abc",
        )
        assert manifest.size_bytes == len(content)
        assert manifest.hash_sha256 == compute_sha256(content)

        # 3. Atomic promote.
        final = AtomicHandoff.promote(
            staged_path=staged,
            target_dir=target_dir,
            target_filename=f"{manifest.file_id}.pdf",
        )
        assert final.exists()
        assert not staged.exists()

        # 4. Verify checksum.
        assert AtomicHandoff.verify_checksum(
            path=final, expected_sha256=manifest.hash_sha256
        ) is True

        # 5. Serialize manifest for downstream consumer.
        manifest_dict = manifest.to_dict()
        manifest_json = json.dumps(manifest_dict)
        restored = json.loads(manifest_json)
        assert restored["file_id"] == manifest.file_id
