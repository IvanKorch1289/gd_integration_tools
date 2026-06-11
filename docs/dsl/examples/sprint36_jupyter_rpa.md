# Примеры DSL: Jupyter Execution + RPA (Sprint 36)

## Jupyter Notebook Execution

```python
from src.backend.dsl.builder import RouteBuilder

# Выполнение notebook через JupyterHub
route = (
    RouteBuilder.from_("analytics.run", source="timer:300s")
    .notebook_execute(
        user_name="alice",
        notebook_path="analysis.ipynb",
        timeout_seconds=120.0,
    )
    .build()
)

# Экспорт notebook в HTML
route = (
    RouteBuilder.from_("reports.export", source="webhook:/export")
    .notebook_export(
        user_name="alice",
        notebook_path="monthly_report.ipynb",
        fmt="html",
    )
    .to_s3(bucket="reports", key="monthly.html")
    .build()
)
```

## SSH Remote Execution

```python
# Выполнение команд на remote server
route = (
    RouteBuilder.from_("remote.healthcheck", source="timer:60s")
    .ssh_exec(
        host="server.company.com",
        command="df -h",
        username="admin",
        key_file="/secrets/id_rsa",
        result_property="disk_usage",
    )
    .build()
)
```

## File Watcher

```python
# Мониторинг директории
route = (
    RouteBuilder.from_("etl.incoming", source="timer:30s")
    .watch_files(
        directory="/data/incoming",
        pattern="*.csv",
        result_property="csv_files",
    )
    .build()
)
```

## Desktop Automation (Linux/macOS)

```python
# Cross-platform desktop automation через pyautogui
route = (
    RouteBuilder.from_("rpa.screenshot", source="timer:300s")
    .desktop_automate("screenshot", result_property="screen")
    .build()
)

route = (
    RouteBuilder.from_("rpa.click", source="webhook:/click")
    .desktop_automate("click", x=100, y=200)
    .desktop_automate("type_text", text="Hello World")
    .desktop_automate("press_key", key="enter")
    .build()
)
```

## YAML Configuration

```yaml
routes:
  - route_id: analytics.run
    source: timer:300s
    steps:
      - processor: notebook_execute
        user_name: alice
        notebook_path: analysis.ipynb
        timeout_seconds: 120.0

  - route_id: remote.healthcheck
    source: timer:60s
    steps:
      - processor: ssh_exec
        host: server.company.com
        command: df -h
        username: admin
        key_file: /secrets/id_rsa
        result_property: disk_usage

  - route_id: etl.incoming
    source: timer:30s
    steps:
      - processor: file_watch
        directory: /data/incoming
        pattern: "*.csv"
        result_property: csv_files

  - route_id: rpa.screenshot
    source: timer:300s
    steps:
      - processor: desktop_pyautogui
        action: screenshot
        result_property: screen
```

## Capability Gates

| Processor | Capability |
|---|---|
| `notebook_execute` | `jupyter.execute` |
| `notebook_export` | `jupyter.export` |
| `ssh_exec` | `rpa.ssh.execute` |
| `file_watch` | `fs.watch` |
| `desktop_pyautogui` | `rpa.desktop.automate` |
| `script_runner` | `rpa.script.execute` |
| `shell_exec` | `rpa.shell.execute` |
