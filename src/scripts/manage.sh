#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/logs"

PREFECT_PID_FILE="$RUN_DIR/prefect.pid"
FASTAPI_PID_FILE="$RUN_DIR/fastapi.pid"
GRPC_PID_FILE="$RUN_DIR/grpc.pid"

PREFECT_LOG_FILE="$LOG_DIR/prefect.log"
FASTAPI_LOG_FILE="$LOG_DIR/fastapi.log"
GRPC_LOG_FILE="$LOG_DIR/grpc.log"

PREFECT_HOST="${PREFECT_HOST:-0.0.0.0}"
PREFECT_PORT="${PREFECT_PORT:-4200}"
FASTAPI_HOST="${FASTAPI_HOST:-0.0.0.0}"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
GRPC_HOST="${GRPC_HOST:-0.0.0.0}"
GRPC_PORT="${GRPC_PORT:-50051}"

export PREFECT_API_URL="${PREFECT_API_URL:-http://127.0.0.1:${PREFECT_PORT}/api}"
export PREFECT_API_DATABASE_CONNECTION_URL="${PREFECT_API_DATABASE_CONNECTION_URL:-postgresql+asyncpg://postgres:postgres@postgres:5432/prefect}"
export PREFECT_LOGGING_LEVEL="${PREFECT_LOGGING_LEVEL:-INFO}"

RABBIT_QUEUE_NAME="${RABBIT_QUEUE_NAME:-my_queue}"
RABBIT_EXCHANGE_NAME="${RABBIT_EXCHANGE_NAME:-my_exchange}"
RABBIT_ROUTING_KEY="${RABBIT_ROUTING_KEY:-my_routing_key}"
RABBIT_SHOVEL_NAME="${RABBIT_SHOVEL_NAME:-my-shovel}"
RABBIT_SHOVEL_DEST_QUEUE="${RABBIT_SHOVEL_DEST_QUEUE:-another_queue}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    . "$ROOT_DIR/.env"
    set +a
fi

log() {
    printf '\033[34m%s\033[0m\n' "$*"
}

ok() {
    printf '\033[32m%s\033[0m\n' "$*"
}

warn() {
    printf '\033[33m%s\033[0m\n' "$*"
}

err() {
    printf '\033[31m%s\033[0m\n' "$*" >&2
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        err "Command not found: $1"
        exit 1
    }
}

read_pid() {
    pid_file="$1"
    if [ -f "$pid_file" ]; then
        cat "$pid_file"
    fi
}

is_running() {
    pid_file="$1"
    pid="$(read_pid "$pid_file" 2>/dev/null || true)"
    [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null
}

wait_for_port() {
    host="$1"
    port="$2"
    timeout="${3:-30}"
    start_ts="$(date +%s)"

    while ! nc -z "$host" "$port" >/dev/null 2>&1; do
        now_ts="$(date +%s)"
        if [ $((now_ts - start_ts)) -ge "$timeout" ]; then
            err "Timeout waiting for $host:$port"
            return 1
        fi
        sleep 1
    done
}

start_process() {
    name="$1"
    pid_file="$2"
    log_file="$3"
    shift 3

    if is_running "$pid_file"; then
        warn "$name already running (PID $(read_pid "$pid_file"))"
        return 0
    fi

    log "Starting $name..."
    (
        cd "$ROOT_DIR"
        "$@"
    ) >>"$log_file" 2>&1 &
    pid=$!
    echo "$pid" > "$pid_file"
    ok "$name started (PID $pid)"
}

stop_process() {
    name="$1"
    pid_file="$2"

    if ! is_running "$pid_file"; then
        warn "$name is not running"
        rm -f "$pid_file"
        return 0
    fi

    pid="$(read_pid "$pid_file")"
    log "Stopping $name (PID $pid)..."
    kill -TERM "$pid" 2>/dev/null || true

    i=0
    while [ "$i" -lt 20 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
            ok "$name stopped"
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done

    warn "$name did not stop gracefully, killing..."
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$pid_file"
    ok "$name killed"
}

status_process() {
    name="$1"
    pid_file="$2"

    if is_running "$pid_file"; then
        echo "$name: running (PID $(read_pid "$pid_file"))"
    else
        echo "$name: stopped"
    fi
}

migrate() {
    if [ ! -f "$ROOT_DIR/alembic.ini" ]; then
        warn "alembic.ini not found, skipping migrations"
        return 0
    fi

    require_cmd poetry
    log "Running database migrations..."
    (
        cd "$ROOT_DIR"
        poetry run alembic upgrade head
    )
    ok "Migrations applied"
}

init_rabbitmq() {
    require_cmd rabbitmqctl
    require_cmd rabbitmqadmin

    log "Waiting for RabbitMQ startup..."
    until rabbitmqctl await_startup >/dev/null 2>&1; do
        sleep 1
    done

    log "Declaring RabbitMQ objects..."
    rabbitmqadmin declare queue name="$RABBIT_QUEUE_NAME" durable=true
    rabbitmqadmin declare exchange name="$RABBIT_EXCHANGE_NAME" type=direct
    rabbitmqadmin declare binding \
        source="$RABBIT_EXCHANGE_NAME" \
        destination="$RABBIT_QUEUE_NAME" \
        routing_key="$RABBIT_ROUTING_KEY"

    rabbitmqctl set_policy \
        shard_policy \
        "^sharded\\." \
        '{"shards-per-node":2}' \
        --apply-to queues || true

    rabbitmqctl set_parameter shovel "$RABBIT_SHOVEL_NAME" \
        "{\"src-uri\":\"amqp://\",\"src-queue\":\"$RABBIT_QUEUE_NAME\",\"dest-uri\":\"amqp://\",\"dest-queue\":\"$RABBIT_SHOVEL_DEST_QUEUE\"}" || true

    ok "RabbitMQ initialized"
}

start_all() {
    require_cmd poetry
    require_cmd nc

    migrate

    start_process \
        "Prefect Server" \
        "$PREFECT_PID_FILE" \
        "$PREFECT_LOG_FILE" \
        poetry run prefect server start --host "$PREFECT_HOST" --port "$PREFECT_PORT"

    wait_for_port 127.0.0.1 "$PREFECT_PORT" 60

    start_process \
        "FastAPI" \
        "$FASTAPI_PID_FILE" \
        "$FASTAPI_LOG_FILE" \
        poetry run uvicorn app.main:app --host "$FASTAPI_HOST" --port "$FASTAPI_PORT"

    wait_for_port 127.0.0.1 "$FASTAPI_PORT" 60

    start_process \
        "gRPC Server" \
        "$GRPC_PID_FILE" \
        "$GRPC_LOG_FILE" \
        poetry run python -m app.grpc.grpc_server

    ok "All services started"
    status_all
}

stop_all() {
    stop_process "gRPC Server" "$GRPC_PID_FILE"
    stop_process "FastAPI" "$FASTAPI_PID_FILE"
    stop_process "Prefect Server" "$PREFECT_PID_FILE"
}

status_all() {
    status_process "Prefect Server" "$PREFECT_PID_FILE"
    status_process "FastAPI" "$FASTAPI_PID_FILE"
    status_process "gRPC Server" "$GRPC_PID_FILE"
}

run_foreground() {
    start_all

    on_exit() {
        warn "Signal received, stopping services..."
        stop_all
        exit 0
    }

    trap 'on_exit' INT TERM

    pref_pid="$(read_pid "$PREFECT_PID_FILE" 2>/dev/null || true)"
    api_pid="$(read_pid "$FASTAPI_PID_FILE" 2>/dev/null || true)"
    grpc_pid="$(read_pid "$GRPC_PID_FILE" 2>/dev/null || true)"

    while :; do
        failed=0

        if [ -n "${pref_pid:-}" ] && ! kill -0 "$pref_pid" 2>/dev/null; then
            err "Prefect Server exited"
            failed=1
        fi

        if [ -n "${api_pid:-}" ] && ! kill -0 "$api_pid" 2>/dev/null; then
            err "FastAPI exited"
            failed=1
        fi

        if [ -n "${grpc_pid:-}" ] && ! kill -0 "$grpc_pid" 2>/dev/null; then
            err "gRPC Server exited"
            failed=1
        fi

        if [ "$failed" -ne 0 ]; then
            stop_all
            exit 1
        fi

        sleep 2
    done
}

restart_all() {
    stop_all
    start_all
}

usage() {
    cat <<'EOF'
Usage: ./scripts/manage.sh <command>

Commands:
  start           Start all services in background
  stop            Stop all services
  restart         Restart all services
  status          Show services status
  migrate         Apply alembic migrations
  init-rabbitmq   Initialize RabbitMQ entities
  run             Start all services and keep container/process alive
EOF
}

main() {
    case "${1:-}" in
        start)
            start_all
            ;;
        stop)
            stop_all
            ;;
        restart)
            restart_all
            ;;
        status)
            status_all
            ;;
        migrate)
            migrate
            ;;
        init-rabbitmq)
            init_rabbitmq
            ;;
        run)
            run_foreground
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
