# Admin React Integration Analysis

**Created**: 2026-05-27
**Status**: Assessment complete — integration recommended as separate wave

---

## Current State

### admin-react (React 18 + Vite SPA)
Located at: `src/frontend/admin-react/`

**Components**:
| Component | API endpoint | Status |
|-----------|-------------|--------|
| `RouteList` | `/api/admin/routes` | Real API |
| `HealthDashboard` | — | **Mock data only** |
| `FeatureFlags` | `/api/admin/flags` | Real API |
| `AuditLog` | `/api/admin/audit` | Real API |
| `SessionList` | — | Unknown |
| `PluginInventory` | — | Unknown |

**API path mismatch**: admin-react uses `/api/admin/*` (legacy),
FastAPI backend exposes `/api/v1/admin/*` (current).

---

## Streamlit Admin Coverage (duplicates)

| admin-react | Streamlit page | Coverage |
|-------------|----------------|---------|
| RouteList | `11_Routes.py` | Partial |
| HealthDashboard | `51_Healthcheck.py` | Full |
| FeatureFlags | `50_Feature_Flags.py` | Full |
| AuditLog | `61_Audit_Log.py` | Full |
| PluginInventory | `68_Plugin_Marketplace.py` | Full |
| SessionList | — | No equivalent |

---

## Integration Options

### Option A: Replace admin-react with Streamlit (recommended for S28)
admin-react provides lightweight admin UI, but:
- HealthDashboard uses mock data (no real integration)
- SessionList has no Streamlit equivalent
- React components are basic (minimal error handling, no loading states)

**Action**: Deprecate admin-react; migrate SessionList → `streamlit_app/pages/Sessions.py`

### Option B: Bridge APIs (low-effort, maintains both)
1. Add `/api/admin/*` → `/api/v1/admin/*` redirects in FastAPI
2. Update admin-react API client to use `/api/v1/admin/*`
3. Both frontends use same backend

**Effort**: 1-2 days
**Benefit**: Both apps work; no data migration

### Option C: Merge admin-react into Streamlit as iframes
Serve admin-react from FastAPI static files; embed pages via `st.iframe()`

**Effort**: 3-5 days
**Benefit**: Single dashboard experience
**Risk**: CORS, auth sharing, iframe resize issues

---

## Recommended Path (based on PLAN.md V22)

admin-react is noted as "интегрировать" (not delete). The practical approach:

1. **Immediate** (this session): Document API path bridge
2. **Next wave**: Add `/api/admin/*` alias routes in FastAPI pointing to `/api/v1/admin/*`
3. **Future**: Migrate SessionList functionality to Streamlit; deprecate admin-react SPA

---

## API Path Bridge (proposed)

Add to FastAPI router registration:

```python
# Redirect legacy /api/admin/* → /api/v1/admin/*
@app.get("/api/admin/{path:path}")
async def admin_legacy_redirect(path: str):
    return RedirectResponse(url=f"/api/v1/admin/{path}", status_code=307)
```

After bridge: admin-react FeatureFlags and AuditLog will work against real data.

---

## Files to Modify for Integration

1. `src/backend/entrypoints/main.py` — add legacy alias routes
2. `src/frontend/admin-react/src/components/FeatureFlags.tsx` — update API paths
3. `src/frontend/admin-react/src/components/AuditLog.tsx` — update API paths
4. `src/frontend/streamlit_app/pages/PAGES_GROUPS.toml` — already documented overlap
