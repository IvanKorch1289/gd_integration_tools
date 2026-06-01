# admin-react

> **DEPRECATED** с S27 Wave 3 (2026-05-27)
>
> Функциональность admin-react мигрирована в Streamlit-приложение.
> Новая реализация: `src/frontend/streamlit_app/pages/84_Sessions.py`

## История

admin-react был MVP React-фронтендом для администрирования AI-сессий.
Использовал отдельную сборку Vite и не был интегрирован в основное
Streamlit-приложение.

## Миграция

| Компонент | Статус | Замена |
|-----------|--------|--------|
| SessionList | ✅ мигрирован | `pages/84_Sessions.py` |
| FeatureFlags | ⚠️ bridge only | `/api/admin/*` → `/api/v1/admin/*` |
| AuditLog | ⚠️ bridge only | `pages/61_Audit_Log.py` |
| RouteList | ⚠️ bridge only | `pages/11_Routes.py` |
| PluginInventory | ⚠️ bridge only | `pages/68_Plugin_Marketplace.py` |

## API Bridge

Backend предоставляет редиректы `/api/admin/*` → `/api/v1/admin/*`
через `app_factory.py` (S27 Wave 3).

## Рекомендация

Используйте Streamlit-приложение `src/frontend/streamlit_app/app.py`
вместо admin-react. Оно обеспечивает единый UX и полную интеграцию
с backend API.
