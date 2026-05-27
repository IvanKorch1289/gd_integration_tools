# admin-react Integration Status

> **Статус**: DEPRECATED (S27 Wave 3, 2026-05-27)

## Резюме

admin-react (MVP React-фронтенд) **выведен из эксплуатации**.
Вся функциональность мигрирована в Streamlit-приложение.

## Редирект API Bridge

Для обратной совместимости backend предоставляет редиректы:

```
/api/admin/*  →  /api/v1/admin/*
```

Реализовано в `src/backend/plugins/composition/app_factory.py`
через `_admin_bridge_router`.

### Поддерживаемые endpoints

| Legacy Path | Современный Path | Статус |
|-------------|-----------------|--------|
| `/api/admin/sessions` | `/api/v1/admin/langgraph/checkpoints` | ✅ |
| `/api/admin/flags` | `/api/v1/admin/feature-flags` | ✅ |
| `/api/admin/plugins` | `/api/v1/admin/plugins` | ✅ |
| `/api/admin/routes` | `/api/v1/routes` | ✅ |

## Миграция компонентов

| Компонент | Status | Streamlit替代 |
|----------|--------|--------------|
| SessionList | ✅ мигрирован | `pages/84_Sessions.py` |
| FeatureFlags | ⚠️ deprecated | `pages/50_Feature_Flags.py` |
| AuditLog | ⚠️ deprecated | `pages/61_Audit_Log.py` |
| RouteList | ⚠️ deprecated | `pages/11_Routes.py` |
| PluginInventory | ⚠️ deprecated | `pages/68_Plugin_Marketplace.py` |

## Рекомендуемый workflow

1. Используйте Streamlit-приложение
2. Для интеграции сторонних React-компонентов — создавайте
   Streamlit-страницы вместо отдельных приложений
3. Для сложных UI — используйте `st.components` с iframe или
   создавайте Plugin-страницы в `extensions/<name>/frontend/pages/`

## Даты

- **DEPRECATED**: 2026-05-27 (S27 Wave 3)
- **API bridge добавлен**: 2026-05-27
- **Полное удаление**: запланировано на S28+
