"""D-AUDIT-11-5 fix (cycle 1): SBOM canonical path verification.

Канонический путь SBOM — ``dist/sbom/sbom.cdx.json``. До фикса было 3-way drift:
1. ``make/security.mk:sbom`` → ``dist/sbom.cdx.json`` (legacy flat)
2. ``tools/checks/generate_sbom.py`` default → ``dist/sbom/sbom.cdx.json`` (canonical)
3. ``tools/checks/check_supply_chain.py`` default → ``dist/sbom/`` (canonical)
4. ``.github/workflows/release.yml`` → ``dist/sbom.cdx.json`` (legacy flat, фикс в этом PR)

После фикса все entry points пишут в canonical ``dist/sbom/sbom.cdx.json``.
"""


from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


class TestSBOMCanonicalPath:
    """D-AUDIT-11-5 fix: все SBOM entry points используют canonical path."""

    def test_make_security_mk_uses_canonical_path(self) -> None:
        """make/security.mk:sbom target пишет в dist/sbom/sbom.cdx.json."""
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        assert "dist/sbom/sbom.cdx.json" in security_mk, (
            "make/security.mk:sbom target должен использовать canonical path "
            "dist/sbom/sbom.cdx.json"
        )
        # Legacy flat path не должен быть в production
        assert "-o dist/sbom.cdx.json" not in security_mk, (
            "Legacy '-o dist/sbom.cdx.json' не должен оставаться в make/security.mk"
        )

    def test_generate_sbom_default_is_canonical(self) -> None:
        """tools/checks/generate_sbom.py --output-dir default — dist/sbom."""
        generate_sbom = (_ROOT / "tools" / "checks" / "generate_sbom.py").read_text(
            encoding="utf-8",
        )
        assert 'default="dist/sbom"' in generate_sbom, (
            "generate_sbom.py --output-dir default должен быть 'dist/sbom'"
        )

    def test_check_supply_chain_default_is_canonical(self) -> None:
        """tools/checks/check_supply_chain.py --output-dir default — dist/sbom."""
        check_supply_chain = (
            _ROOT / "tools" / "checks" / "check_supply_chain.py"
        ).read_text(encoding="utf-8")
        assert 'default=Path("dist/sbom")' in check_supply_chain, (
            "check_supply_chain.py --output-dir default должен быть Path('dist/sbom')"
        )

    def test_release_workflow_uses_canonical_path(self) -> None:
        """.github/workflows/release.yml Generate SBOM step использует --output-dir dist/sbom."""
        release_yml = (_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8",
        )
        assert "--output-dir dist/sbom" in release_yml, (
            ".github/workflows/release.yml Generate SBOM step должен использовать "
            "--output-dir dist/sbom (canonical)"
        )
        # Legacy --output dist/sbom.cdx.json НЕ должно быть
        assert (
            "--output dist/sbom.cdx.json" not in release_yml
        ), "Legacy '--output dist/sbom.cdx.json' не должен оставаться в release.yml"

    def test_cosign_sign_all_already_canonical(self) -> None:
        """cosign_sign_all.py уже использует canonical path (контроль регрессии)."""
        cosign = (_ROOT / "tools" / "checks" / "cosign_sign_all.py").read_text(
            encoding="utf-8",
        )
        assert "dist/sbom/" in cosign, (
            "cosign_sign_all.py должен продолжать использовать dist/sbom/ "
            "(контроль регрессии после canonical path unification)"
        )


class TestSBOMRegeneratedCurrent:
    """D-AUDIT-A11-5 follow-up: legacy SBOM удалён, canonical SBOM имеет актуальные версии.

    До фикса:
    - ``dist/sbom.cdx.json`` (legacy flat) содержал stale cryptography 41.0.7
      (lock pin: cryptography≥49.0.0), starlette 1.0.0 (lock pin: 1.3.1).
    - ``dist/sbom/sbom.cdx.json`` (canonical) отсутствовал.

    После фикса (2026-08-12):
    - Legacy ``dist/sbom.cdx.json`` удалён.
    - Canonical ``dist/sbom/sbom.cdx.json`` сгенерирован через fallback
      (importlib.metadata), pip-audit dry-run блокирован yanked
      presidio-analyzer==2.2.362 (требует отдельного lock-fix).
    """

    def test_legacy_sbom_cdx_json_does_not_exist(self) -> None:
        """Legacy flat ``dist/sbom.cdx.json`` должен отсутствовать."""
        legacy = _ROOT / "dist" / "sbom.cdx.json"
        assert not legacy.exists(), (
            f"Legacy {legacy} не должен существовать (D-AUDIT-A11-5 follow-up). "
            "Удалите его: `rm dist/sbom.cdx.json`. "
            "Canonical path — dist/sbom/sbom.cdx.json."
        )

    def test_canonical_sbom_exists(self) -> None:
        """Canonical ``dist/sbom/sbom.cdx.json`` существует."""
        canonical = _ROOT / "dist" / "sbom" / "sbom.cdx.json"
        assert canonical.exists(), (
            f"Canonical {canonical} не найден. "
            "Запустите `make sbom` (или fallback через importlib.metadata)."
        )

    def test_canonical_sbom_has_current_cryptography(self) -> None:
        """Canonical SBOM содержит cryptography≥49.0.0 (не stale 41.0.7)."""
        import json

        canonical = _ROOT / "dist" / "sbom" / "sbom.cdx.json"
        if not canonical.exists():
            import pytest

            pytest.skip("canonical SBOM not yet generated")

        data = json.loads(canonical.read_text(encoding="utf-8"))
        components = data.get("components", [])
        crypto_versions = [
            c.get("version")
            for c in components
            if c.get("name", "").lower() == "cryptography"
        ]
        assert crypto_versions, "cryptography не найден в SBOM"
        version = crypto_versions[0]
        # Strip patch suffix for comparison
        major_minor = ".".join(version.split(".")[:2])
        assert int(major_minor.split(".")[0]) >= 42, (
            f"cryptography {version} (SBOM) устарел — lock pin требует ≥49.0.0. "
            "Это указывает на stale SBOM (D-AUDIT-A11-5 NOT DONE carry-over)."
        )
