#!/bin/bash

# Конфигурация
export PREFECT_API_URL="http://localhost:4200/api"
export PREFECT_API_DATABASE_CONNECTION_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/prefect"

# Функции проверки
check_port() {
    nc -z localhost $1
    return $?
}

wait_for_service() {
    local port=$1
    local timeout=$2
    local start_time=$(date +%s)
    
    while ! check_port $port; do
        if [ $(($(date +%s) - start_time)) -gt $timeout ]; then
            echo "Timeout waiting for port $port"
            exit 1
        fi
        sleep 1
    done
}

# Остановка существующих процессов
echo "Stopping existing services..."
pkill -f "prefect server start" || true
pkill -f "uvicorn app.main:app" || true
pkill -f "python3 -m app.grpc.grpc_server" || true
sleep 3

# Запуск Prefect Server
if check_port 4200; then
    echo "Port 4200 already in use. Killing conflicting processes..."
    pkill -f "prefect server start" || true
    sleep 2
fi

echo "Starting Prefect Server..."
prefect server start \
    --host 0.0.0.0 \
    --port 4200 \
    > prefect_server.log 2>&1 &

echo "Waiting for Prefect Server to start..."
wait_for_service 4200 30

# Запуск FastAPI
echo "Starting FastAPI..."
uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --reload \
    > fastapi.log 2>&1 &

# Запуск gRPC
echo "Starting gRPC Server..."
python3 -m app.grpc.grpc_server \
    > grpc_server.log 2>&1 &

# Сохранение PID
echo "Saving PIDs..."
pgrep -f "prefect server start" > .pids
pgrep -f "uvicorn app.main:app" >> .pids
pgrep -f "python3 -m app.grpc.grpc_server" >> .pids

echo "Services started:"
echo "- Prefect UI:  http://localhost:4200"
echo "- FastAPI:     http://localhost:8000"
echo "- gRPC Server: localhost:50051"
