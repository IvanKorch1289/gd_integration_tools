# gd_integration_tools — Documentation

Интеграционная шина на Python 3.14+ с DSL, workflow-оркестрацией,
коннекторами и developer portal.

## Документация

```{toctree}
:maxdepth: 2
:caption: Tutorials

../tutorials/getting-started
../tutorials/build-first-action
../tutorials/build-rest-connector
../tutorials/build-grpc-service
../tutorials/write-dsl-route
../tutorials/plugin-development
../tutorials/rag-setup
../tutorials/rpa-script
../tutorials/multi-tenant-setup
```

```{toctree}
:maxdepth: 1
:caption: Runbooks

../runbooks/deploy
../runbooks/rollback
../runbooks/scale-out
../runbooks/incident-response
../runbooks/db-migration
../runbooks/cache-flush
../runbooks/audit-export
../runbooks/key-rotation
../runbooks/plugin-install
../runbooks/cdc-restart
../runbooks/taskiq-worker
```

```{toctree}
:maxdepth: 1
:caption: Reference

glossary
dsl_reference
../adr/INDEX
```

```{toctree}
:maxdepth: 1
:caption: Architecture

../ARCHITECTURE
../DEVELOPER_GUIDE
../DEPLOYMENT
../QUICKSTART
../AI_INTEGRATION
../CDC_GUIDE
../PROCESSORS
../DSL_COOKBOOK
../RPA_GUIDE
../DEPRECATIONS
```

## API reference (autoapi)

См. сгенерированную секцию ``api/`` в боковой панели — собирается из
docstrings в ``src/core``, ``src/dsl``, ``src/services``, ``src/schemas``.
