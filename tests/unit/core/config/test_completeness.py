"""Config completeness test (Sprint 170 M2 Phase 5)."""

from __future__ import annotations

from pathlib import Path


def test_env_example_exists():
    assert Path(".env.example").exists(), ".env.example missing"


def test_base_yml_exists():
    assert Path("config_profiles/base.yml").exists(), "config_profiles/base.yml missing"


def test_critical_env_vars_documented():
    """Критичные СЕКРЕТЫ должны быть в .env.example (ADR-0373).

    Несекретные переменные (APP_ENV, ENVIRONMENT, JUPYTER_BACKEND,
    DSL_YAML_STORE_DIR, SEARXNG_BASE_URL) в ``.env.example`` запрещены —
    они живут в ``config_profiles/{profile}.yml``.
    """
    env_example = Path(".env.example").read_text()
    critical = [
        "AUDIT_SECRET_KEY",
        "E2B_API_KEY",
        "SEC_SECRET_KEY",
        "SEC_API_KEY",
        "DB_PASSWORD",
    ]
    missing = [v for v in critical if v not in env_example]
    assert not missing, f"Missing in .env.example: {missing}"

    non_secret = [
        "APP_ENV",
        "APP_PROFILE",
        "ENVIRONMENT",
        "JUPYTER_BACKEND",
        "DSL_YAML_STORE_DIR",
        "SEARXNG_BASE_URL",
    ]
    leaked = [v for v in non_secret if f"\n{v}=" in f"\n{env_example}"]
    assert not leaked, f"Non-secret vars must not be in .env.example: {leaked}"


def test_yml_pool_sizes_present():
    """base.yml must declare pool sizes for DB connections."""
    base = Path("config_profiles/base.yml").read_text()
    has_db_pool = "pool_size" in base or "max_connections" in base
    assert has_db_pool, "No pool size configured in base.yml"


def test_all_config_profiles_have_app_section():
    """Each profile must have app: section."""
    for profile in ["base.yml", "dev.yml", "prod.yml", "staging.yml"]:
        path = Path(f"config_profiles/{profile}")
        if not path.exists():
            continue
        content = path.read_text()
        assert "app:" in content, f"{profile}: missing app section"


def test_no_secrets_in_yml():
    """Secrets (password, token, secret) should not be hardcoded in yml."""
    for profile in ["base.yml", "dev.yml", "prod.yml", "staging.yml"]:
        path = Path(f"config_profiles/{profile}")
        if not path.exists():
            continue
        content = path.read_text().lower()
        # Look for actual values, not placeholder mentions
        bad = []
        for line in content.split("\n"):
            line_clean = line.strip()
            if line_clean.startswith("#"):
                continue
            if ": " in line_clean:
                key, _, val = line_clean.partition(": ")
                val = val.strip().strip('"').strip("'")
                # Allow empty, placeholder, or "$" (env reference)
                if not val or val.startswith(("$", "{{")):
                    continue
                # Only flag if the value looks like a real secret (long random-looking, not a path)
                if any(s in key for s in ["password", "token", "secret", "api_key"]):
                    # Allow Vault paths (contain "/")
                    if "/" in val or val.startswith("changeme"):
                        continue
                    if val and len(val) > 5:
                        bad.append(f"{profile}:{key}={val}")
        assert not bad, f"Hardcoded secrets: {bad}"
