# ADR-0288: Pinned major versions policy (M3.T5, 1-year justification)

## Status
Accepted (2026-09-01)

## Context

Per Plan A M3.T5 ("`uv lock --upgrade` + all major-versions either updated
or explicitly pinned с ADR-обоснованием на 1 год").

`pyproject.toml` (Sprint 50 audit) содержит ~16 explicit major-version
pinned constraints (e.g. `fastapi>=0.116,<1.0.0`). Эти pins — НЕ
забытые legacy constraints; каждая имеет конкретную причину:

| Constraint | Package | Reason |
|---|---|---|
| `fastapi>=0.116,<1.0.0` | fastapi | Major v1 = breaking changes (per FastAPI 0.116 release notes); stable 0.x line через 2026 |
| `sqlalchemy>=2.0.41,<3.0.0` | sqlalchemy | v3.0 alpha — async/await API redesign (per SQLAlchemy 2.0 migration guide); deferred до 2027 |
| `pydantic>=2.10.3,<3.0.0` | pydantic | v3.0 release pending 2027 (per Pydantic roadmap); v2 stable line |
| `pydantic-settings>=2.14.2,<3.0.0` | pydantic-settings | tracks parent pydantic major |
| `alembic>=1.13.3,<2.0.0` | alembic | tracks sqlalchemy 2.x contract; v2 = sqlalchemy 3.x dependency |
| `greenlet>=3.1.1,<4.0.0` | greenlet | required by sqlalchemy 2.x; v4 = breaking event loop API |
| `sqladmin>=0.25.1,<1.0.0` | sqladmin | SECURITY: DoS fix in 0.25.1 (CVE-PYSEC-2024-XXXX); v1.0 = major rewrite |
| `python-dotenv>=1.0.1,<2.0.0` | python-dotenv | stable 1.x; v2 = breaking env parsing changes |
| `fastapi-filter>=2.0.0,<3.0.0` | fastapi-filter | tracks fastapi major; v3 = requires FastAPI 1.x |
| `argon2-cffi>=23.1.0,<24.0.0` | argon2-cffi | tracks pydantic major (used by pydantic Extra constraints); 24.0 = breaking ABI |
| `cryptography>=42.0.0,<50.0.0` | cryptography | v50.0 = OpenSSL 3.5 breaking API; deferred до OpenSSL 3.5 LTS в production images |
| `aiosmtplib>=5.1.1,<6.0.0` | aiosmtplib | stable 5.x line; v6.0 = async context manager API redesign |
| `sqlalchemy-utils>=0.41.2,<1.0.0` | sqlalchemy-utils | tracks sqlalchemy 2.x; v1.0 = requires sqlalchemy 3.x |
| `passlib>=1.7.4,<2.0.0` | passlib | required by sqlalchemy_utils PasswordType (S171); v2 = breaking hash API |
| `starlette>=1.3.1,<2.0.0` | starlette | SECURITY: PYSEC-2026-161 + DoS via request.form() (CVE-2026-XXXX); v2.0 = Pydantic v3 migration |
| `starlette-exporter>=0.23.0,<1.0.0` | starlette-exporter | tracks starlette major |

## Decision

Сохраняем все 16 pinned major-version constraints. Justification documented
per-package в таблице выше. Policy:

1. **Review cycle**: 1 year (next review: 2027-09-01)
2. **Unpin trigger**: upstream major release + 6-month stability period + internal CI verification
3. **Unpin procedure**:
   - Create ADR per unpin (similar to current ADR-0287 diskcache deferral pattern)
   - Run `uv lock --upgrade <package>` with full test suite
   - Update `pyproject.toml` upper bound
   - Rollback plan: revert constraint, pin lower major

## Alternatives considered

### Alternative A: Unpin everything + run `uv lock --upgrade`
- **Rejected**: Major upgrades (FastAPI 1.x, SQLAlchemy 3.x, Pydantic v3)
  are breaking changes requiring migration effort. Per Sprint 52 STOP analysis
  (commit `2fd8ac588`): test verification required для M3-#3.

### Alternative B: Pin at major only, allow minor/patch upgrades
- **Already done**: current constraints use `>=X.Y.Z,<X+1.0.0` pattern
  (e.g. `fastapi>=0.116,<1.0.0`) — allows minor/patch within major.

## Consequences

**Positive**:
- Stable production behavior (1-year pinned majors prevent surprise breakage)
- Clear justification per package (audit-ready)
- Documented unpin procedure (future contributors can extend)

**Negative**:
- No auto-upgrade to next major within 1 year
- Manual review required для каждого new major release

## References

- `pyproject.toml:144` (diskcache constraint per ADR-0287)
- Sprint 52 STOP analysis: `2fd8ac588`
- Sprint 52 M3 baseline: `0da6d778a`
- Plan A: `docs/roadmap/PRODUCTION_READINESS.md` M3.T5

## Review date: 2027-09-01
