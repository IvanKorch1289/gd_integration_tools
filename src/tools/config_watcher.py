import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = (ROOT_DIR / "config.yml").resolve()
MANAGE_SCRIPT = (ROOT_DIR / "scripts" / "manage.sh").resolve()
DEBOUNCE_SECONDS = 2.0


class ConfigEventHandler(FileSystemEventHandler):
    def __init__(self, config_path: Path, manage_script: Path, debounce_seconds: float = 2.0) -> None:
        self.config_path = config_path
        self.manage_script = manage_script
        self.debounce_seconds = debounce_seconds
        self._last_restart_at = 0.0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        src_path = Path(getattr(event, "src_path", "")).resolve()
        dest_path_raw = getattr(event, "dest_path", None)
        dest_path = Path(dest_path_raw).resolve() if dest_path_raw else None

        if src_path != self.config_path and dest_path != self.config_path:
            return

        now = time.monotonic()
        if now - self._last_restart_at < self.debounce_seconds:
            return

        self._last_restart_at = now
        self._restart_services()

    def _restart_services(self) -> None:
        print(f"[config-watcher] detected change in {self.config_path.name}, restarting services...")
        try:
            result = subprocess.run(
                ["/bin/sh", str(self.manage_script), "restart"],
                cwd=str(ROOT_DIR),
                check=False,
            )
            if result.returncode == 0:
                print("[config-watcher] restart completed successfully")
            else:
                print(
                    f"[config-watcher] restart failed with exit code {result.returncode}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"[config-watcher] restart error: {exc}", file=sys.stderr)


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"[config-watcher] config file not found: {CONFIG_PATH}", file=sys.stderr)
        return 1

    if not MANAGE_SCRIPT.exists():
        print(f"[config-watcher] manage script not found: {MANAGE_SCRIPT}", file=sys.stderr)
        return 1

    event_handler = ConfigEventHandler(
        config_path=CONFIG_PATH,
        manage_script=MANAGE_SCRIPT,
        debounce_seconds=DEBOUNCE_SECONDS,
    )

    observer = Observer()
    observer.schedule(event_handler, path=str(ROOT_DIR), recursive=False)
    observer.start()

    print(f"[config-watcher] watching {CONFIG_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[config-watcher] stopping watcher...")
        observer.stop()

    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
