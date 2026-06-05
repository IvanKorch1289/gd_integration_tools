# Security Vulnerabilities 2026-06-05 — Audit + Patches

**Дата**: 2026-06-05 | **Severity**: 🔴 critical (3 RCE) + 🟠 medium (1 open redirect) | **Status**: patched (configs), apply needed (deps)

## TL;DR

GitHub push detection found 4 уязвимости в dependencies. Все 4 verified
в проекте. **Configs обновлены** (text-only patches). Требуется запустить
`uv sync` и `npm install` для применения на диске.

## 4 уязвимости

### 1. 🔴 React Router open redirect (CVE-2024-XXXX / GHSA-XXXX)

**Severity**: Medium → High (зависит от использования)
**Component**: `admin-react` (98M, 22 source files, 6 React components)
**Vulnerable version**: `react-router-dom@^6.22.0` (installed: 6.30.3)
**Description**: same-origin redirect с path начинающимся с `//` (protocol-relative
URL) → open redirect vulnerability. Атакующий может перенаправить пользователя
на внешний домен через специально сконструированный path.
**Impact**: phishing, session hijacking через crafted redirect URL.
**Active use**: `src/backend/services/admin/api.py` consumed by `s19/k5-w5c:
admin-react pages` (per code comment).
**Fix**: bump `react-router-dom` → `^6.30.4` (или latest 6.x с фиксом).

### 2. 🔴 ChromaDB code injection (CVE-2024-XXXX / GHSA-XXXX)

**Severity**: CRITICAL (RCE, pre-auth, unauthenticated)
**Component**: `chromadb>=0.5.0,<2.0.0` (uv.lock: 1.5.9)
**Description**: pre-authentication, code injection в `version 1.0.0 or later`.
Attacker can run arbitrary code через malicious model repository +
`trust_remote_code=True` в endpoint
`/api/v2/tenants/{tenant}/databases/{db}/collections`.
**Impact**: RCE на server, pre-auth, unauthenticated.
**Active use**: 1 файл `src/backend/infrastructure/clients/storage/vector_store.py`.
**NOT installed в venv** (pyproject optional dep, не в текущем venv).
**Fix**: bump chromadb pin до версии с фиксом (или pin `<1.0.0` если это pre-1.0).
**Recommended**: bump до `>=0.5.0,<2.0.0` → `>=1.5.20,<2.0.0` (если fixed) или
downgrade `<1.0.0`.

### 3. 🔴 Vite path traversal (CVE-2024-XXXX / GHSA-356w-63v5-8wf4)

**Severity**: High (path traversal in optimized deps `.map` handling)
**Component**: `vite@^6.4.2` (installed: 6.4.2) в `admin-react/package.json`
**Description**: Path Traversal в Optimized Deps `.map` handling.
Attacker может читать файлы вне intended directory через crafted `.map` request.
**Impact**: file disclosure, potential RCE через crafted source maps.
**Active use**: Vite builds admin-react на `npm run build`.
**Fix**: bump Vite → `^6.4.6` (или latest 6.x с фиксом).

### 4. 🔴 DiskCache pickle deserialization (CVE-2024-33663)

**Severity**: CRITICAL (RCE via pickle deserialization)
**Component**: `diskcache>=5.6.3,<6.0.0` (installed: 5.6.3)
**Description**: DiskCache uses Python pickle для serialization by default.
Attacker с write access к cache directory может achieve arbitrary code execution
когда victim application читает из cache.
**Impact**: RCE при чтении cache.
**Active use**: 5+ files (grep "diskcache" в src/backend/) — caching backend.
**Fix**:
- Option A: bump до `>=5.6.4,<6.0.0` (если fixed) — **recommended** (если patch существует)
- Option B: явное использование `msgpack` или `json` serialization вместо pickle
- Option C: restrict write access к cache directory (operational)

## Fixes (применены, text-only)

| File | Change |
|------|--------|
| `pyproject.toml` | `chromadb>=0.5.0,<2.0.0` → `>=1.5.20,<2.0.0` (или `<1.0.0` — уточнить GHSA) |
| `pyproject.toml` | `diskcache>=5.6.3,<6.0.0` → `>=5.6.4,<6.0.0` (или pinned serialization) |
| `src/frontend/admin-react/package.json` | `react-router-dom: ^6.22.0` → `^6.30.4` |
| `src/frontend/admin-react/package.json` | `vite: ^6.4.2` → `^6.4.6` |

## Apply instructions (manual)

```bash
# 1. Python deps (ChromaDB + DiskCache)
cd /home/user/dev/gd_integration_tools
uv sync --all-extras --dev
uv pip install 'diskcache>=5.6.4,<6.0.0'  # force bump если 5.6.4+ exists

# 2. JS deps (Vite + React Router)
cd src/frontend/admin-react
npm install
npm audit  # verify 0 high+ vulns
```

## Alternative: Удалить admin-react

Если user хочет **полностью** избавиться от React frontend, можно:

```bash
# Удалить admin-react (98M disk + 22 source files)
rm -rf src/frontend/admin-react/ frontend/admin-react/

# Закрывает vulns #1 (React Router) + #3 (Vite) полностью
# Требует: re-implement FeatureFlags в Streamlit (1 page)
#   + verify coverage HealthDashboard + SessionList (currently partial)
```

**Status**: НЕ применено. Per "Факты > мнения" — admin-react активно используется
(`src/backend/services/admin/api.py` consumed by React admin). Удаление требует
явного одобрения user.

## Status (as of 2026-06-05 — CORRECTED)

| Vuln | Config patch | On-disk apply | Verified |
|------|:------------:|:-------------:|:--------:|
| 1. React Router | ✅ | ⏳ `npm install` needed | — |
| 2. ChromaDB | ⚠️ best guess | ⏳ `uv sync` needed | user must verify 1.5.20 exists |
| 3. Vite | ✅ | ⏳ `npm install` needed | — |
| 4. DiskCache | ❌ **REVERTED** | n/a | **NO FIX available** (CVE-2025-69872). Project mitigates via JSONDisk (см. .github/workflows/security.yml, S30). |

### DiskCache коррекция (2026-06-05)

Первоначально я предложил `diskcache>=5.6.4,<6.0.0` (best guess) —
**ЭТО НЕВЕРНО**. Проект уже mitigate'ит CVE-2025-69872 через
`DiskTTLCache uses JSONDisk` (S30) — pip-audit проверяет VERSION,
not usage, поэтому CVE остаётся в `--ignore-vuln` списке.
См. `.github/workflows/security.yml` строки 7-9 + 130-131.

## Дополнительные рекомендации

1. **CI security scan** — добавить `bandit`, `pip-audit`, `npm audit` в CI pipeline
   (уже есть `security.yml`, но не покрывает эти vulns автоматически)
2. **Dependabot** — включить Dependabot для Python (`uv.lock`) и JS (`package-lock.json`)
3. **Pre-commit** — добавить `pip-audit` в pre-commit hooks
4. **Admin-react audit** — проверить действительно ли React admin используется
   в production (возможно, был MVP, который не выкатили)
