# Build first plugin

Собираем V11-плагин с двумя features за минуту.

## Цель

* `extensions/<name>/` создан с hybrid layout (ADR R1.6);
* плагин загружается через `loader_v11`;
* features регистрируются как actions.

## Шаги

1. Scaffold через codegen:

    ```bash
    make new-plugin NAME=demo_widget FEATURES='ping,echo' \
        CAPABILITIES='mq.publish' WITH_FRONTEND=1
    ```

2. Проверить `plugin.toml` валиден:

    ```bash
    uv run python -c "
    from src.backend.services.plugins.manifest_v11 import load_plugin_manifest
    m = load_plugin_manifest('extensions/demo_widget/plugin.toml')
    print(m.name, m.version, m.capabilities)
    "
    ```

3. Открыть Streamlit page **71_Capabilities** — `demo_widget` появится в
   matrix как plugin × capability.

## Что дальше

* Замените echo-handlers в `extensions/demo_widget/plugin.py` на реальную логику;
* Расширьте `features/<f>/route.toml` step'ами DSL;
* Добавьте unit-тесты в `features/<f>/test_<f>.py`.

См. также:
* [Sign release](../how-to/sign_release.md) — keyless подпись Docker images.
* [Run perf locally](../how-to/run_perf_locally.md) — локальный SLO-gate.
