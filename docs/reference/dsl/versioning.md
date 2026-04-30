# DSL apiVersion + Migrations (W25.3)

Двусторонний YAML ↔ Python-канал требует устойчивого формата
spec'ов. ``apiVersion`` — дискриминатор формата, который позволяет:

- хранить старые YAML-файлы и снапшоты в БД без потери совместимости;
- авто-апгрейдить их при загрузке через зарегистрированную цепочку
  миграций;
- эволюционировать формат, не ломая существующие routes.

## Дизайн

| Версия | Когда введена | Что в формате |
|---|---|---|
| `v0` | до W25 (legacy) | поле ``apiVersion`` отсутствует. Loader считает spec'ом v0 |
| `v1` | W25.3 (demo) | identity, маркируется ``_migrated_from`` |
| `v2` | W25.3 (текущая) | identity, ``CURRENT_VERSION`` для всех новых spec'ов |

Демо-миграции v0→v1 и v1→v2 — identity по структуре. Они нужны, чтобы
обкатать framework: при появлении реального breaking-change его
можно будет добавить как новую миграцию (``v2 → v3`` и т.д.) без
переработки инфраструктуры.

## Использование

### Загрузка YAML (auto-migrate)

```python
from src.dsl.yaml_loader import load_pipeline_from_yaml

yaml_str = """\
apiVersion: v0
route_id: legacy.route
processors:
  - log: {level: info}
"""
pipeline = load_pipeline_from_yaml(yaml_str)
# Pipeline'у уже соответствует apiVersion=v2 (CURRENT_VERSION)
```

### Сохранение Pipeline → YAML

`Pipeline.to_dict()` всегда сериализует с актуальной ``apiVersion``:

```python
pipeline.to_dict()
# {'apiVersion': 'v2', 'route_id': 'legacy.route', 'processors': [...]}
```

### Программный доступ к миграциям

```python
from src.dsl.versioning import apply_migrations

migrated = apply_migrations(spec, target_version="v2")
```

### CLI

```bash
# preview миграции всех YAML в каталоге
uv run python manage.py dsl migrate --target v2 --dry-run

# фактическая запись
uv run python manage.py dsl migrate --target v2
```

## Расширение: новая миграция

1. Создай `src/dsl/versioning/migrations_vN_to_vN+1.py`:
   ```python
   class VNtoVNplus1Migration:
       from_version = "vN"
       to_version = "vN+1"

       def migrate(self, spec):
           # ... преобразования
           return spec
   ```

2. Зарегистрируй в `default_registry()` (`migrations.py`).
3. Подними `CURRENT_VERSION` до `vN+1` в `migrations.py`.
4. Обнови alembic-миграцию `dsl_snapshots.api_version` server_default
   на `vN+1` (опционально — старые записи остаются с предыдущей версией).
5. Добавь юнит-тесты в `tests/unit/dsl/versioning/test_vN_to_vN+1.py`.

## Снапшоты в БД

Таблица ``dsl_snapshots`` несёт колонку ``api_version VARCHAR(8)``
(см. миграцию ``b8c9d0e1f2a3``). При сравнении двух снапшотов с
разными ``api_version`` ``PipelineVersionManager.compare`` сначала
прогоняет старший через миграции до ``CURRENT_VERSION``, чтобы
сравнение было корректным.

## ADR

См. `docs/adr/ADR-034-dsl-versioning.md` — обоснование выбора
schema-discriminator подхода вместо schema-only (Pydantic) или
external migrator.
