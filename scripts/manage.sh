#!/usr/bin/env sh
set -eu

APP_MODULE="${APP_MODULE:-app.main:app}"
UVICORN_HOST="${UVICORN_HOST:-0.0.0.0}"
UVICORN_PORT="${UVICORN_PORT:-8000}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
RUN_DIR="${RUN_DIR:-./.run}"
LOG_DIR="${LOG_DIR:-./logs}"
PID_FILE="${RUN_DIR}/app.pid"

info()  { printf '\033[34m%s\033[0m\n' "$*"; }
ok()    { printf '\033[32m%s\033[0m\n' "$*"; }
warn()  { printf '\033[33m%s\033[0m\n' "$*"; }
err()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }

cmd_run() {
    info "Starting application in foreground..."
    exec uvicorn "$APP_MODULE" \
        --host "$UVICORN_HOST" \
        --port "$UVICORN_PORT" \
        --workers "$UVICORN_WORKERS"
}

cmd_start() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            warn "Application already running (PID $pid)"
            return 0
        fi
        rm -f "$PID_FILE"
    fi

    info "Starting application in background..."
    nohup uvicorn "$APP_MODULE" \
        --host "$UVICORN_HOST" \
        --port "$UVICORN_PORT" \
        --workers "$UVICORN_WORKERS" \
        >> "$LOG_DIR/app.log" 2>&1 &
    echo $! > "$PID_FILE"
    ok "Application started (PID $(cat "$PID_FILE"))"
}

cmd_stop() {
    if [ ! -f "$PID_FILE" ]; then
        warn "Application is not running"
        return 0
    fi
    pid=$(cat "$PID_FILE")
    if ! kill -0 "$pid" 2>/dev/null; then
        warn "Application is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 0
    fi
    info "Stopping application (PID $pid)..."
    kill -TERM "$pid" 2>/dev/null || true
    i=0
    while [ "$i" -lt 30 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            ok "Application stopped"
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done
    warn "Graceful shutdown timeout, killing..."
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    ok "Application killed"
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            ok "Application: running (PID $pid)"
        else
            warn "Application: stopped (stale PID file)"
        fi
    else
        info "Application: stopped"
    fi
}

cmd_migrate() {
    info "Applying database migrations..."
    alembic upgrade head
    ok "Migrations applied"
}

cmd_init_rabbitmq() {
    info "Initializing RabbitMQ..."
    python -c "
import asyncio
from app.infrastructure.clients.stream import stream_client
asyncio.run(stream_client.initialize_rabbit())
"
    ok "RabbitMQ initialized"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  run            Start in foreground
  start          Start in background
  stop           Stop application
  restart        Restart application
  status         Show status
  migrate        Apply database migrations
  init-rabbitmq  Initialize RabbitMQ entities
  help           Show this help
EOF
}

case "${1:-help}" in
    run)            cmd_run ;;
    start)          cmd_start ;;
    stop)           cmd_stop ;;
    restart)        cmd_restart ;;
    status)         cmd_status ;;
    migrate)        cmd_migrate ;;
    init-rabbitmq)  cmd_init_rabbitmq ;;
    help|--help|-h) usage ;;
    *)              err "Unknown command: $1"; usage; exit 1 ;;
esac
