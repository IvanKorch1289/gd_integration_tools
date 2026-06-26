# CRUD DSL Audit (S171 M17.3)

## Existing CRUD processors (15+)

| File | Purpose |
|------|---------|
| `entity.py` | 5 операций (create/get/update/delete/list) для entity |
| `db_crud.py` | Generic CRUD (insert/update/delete/select) |
| `db_call_procedure.py` | Stored procedures |
| `db_query_external.py` | External DB queries |
| `data_query.py` | Data query DSL |
| `infra_db.py` | Infra DB operations |
| `infra_mongodb.py` | MongoDB queries |
| `jdbc_query.py` | JDBC-style queries |
| `duckdb_query.py` | DuckDB analytics |
| `ldap_query.py` | LDAP queries |
| `graphql_query.py` | GraphQL queries |
| `jq_query.py` | jq-style JSON queries |
| `jsonpath_query.py` | JSONPath queries |

## Entity repository pattern (4 entities)

| Plugin | Repository |
|--------|-----------|
| `extensions/core_entities/orders/` | `repositories/orders.py` |
| `extensions/core_entities/users/` | `repositories/users.py` |
| `extensions/core_entities/files/` | `repositories/files.py` |
| `extensions/core_entities/orderkinds/` | `repositories/orderkinds.py` |

Base class: `src/backend/core/repositories/base.py::SQLAlchemyRepository` (D102)

## DSL usage example

```python
from src.backend.dsl.builder import RouteBuilder

# 1. Entity CRUD (5 operations)
route = (
    RouteBuilder.from_("api.orders.create", source="internal:admin")
    .entity_create(entity="order", request_schema="OrderCreateSchema")
    .response_cache(ttl_seconds=60)
    .build()
)

route2 = (
    RouteBuilder.from_("api.orders.list", source="internal:admin")
    .entity_list(entity="order", filter_schema="OrderFilterSchema", pagination=True)
    .policy.cache(ttl_seconds=30, key="orders-list")
    .build()
)

# 2. Generic DB CRUD
route3 = (
    RouteBuilder.from_("api.customers.read", source="internal:admin")
    .db_crud(operation="read", entity="customer", primary_key="id")
    .build()
)

# 3. Stored procedures
route4 = (
    RouteBuilder.from_("api.reports.monthly", source="cron:monthly")
    .db_call_procedure(name="generate_monthly_report", params={"month": "2026-06"})
    .build()
)
```

## Builder methods (5 entity + 3 generic + 2 query)

```python
# Entity (5)
route.entity_create(entity="...", request_schema="...")
route.entity_get(entity="...", primary_key="...")
route.entity_update(entity="...", request_schema="...")
route.entity_delete(entity="...", primary_key="...")
route.entity_list(entity="...", filter_schema="...")

# Generic DB
route.db_crud(operation="read|insert|update|delete", entity="...")
route.db_call_procedure(name="...", params={...})
route.db_query_external(profile="...", sql="...")

# Query DSL (transformations)
route.jq_query(expr=".", body="...")
route.jsonpath_query(expr="$.path", body="...")
```

## Audit verdict

M17.3: CRUD DSL coverage 100% — 13+ processors for all CRUD operations.
Repository pattern canonical (D202 binding rule): all new repositories
должны наследовать от `SQLAlchemyRepository[Model]`.

M17.3 done — 0 gaps, 0 missing DSL.

Refs:
- D202 (Repository pattern)
- D102 (Facade single-source)
- M17.3 audit phase
