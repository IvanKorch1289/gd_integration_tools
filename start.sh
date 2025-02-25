#!/bin/bash

# Устанавливаем переменные окружения
export PREFECT_API_URL="http://localhost:4200/api"
export PREFECT_API_DATABASE_CONNECTION_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/prefect"

# Функция проверки порта
check_port() {
    nc -z localhost $1
    return $?
}

# Остановка существующих процессов Prefect
echo "Stopping any existing Prefect processes..."
pkill -f "prefect server start"
pkill -f "prefect worker start"
sleep 2

# Запуск Prefect Server с PostgreSQL
if check_port 4200; then
    echo "Port 4200 is already in use. Killing existing processes..."
    pkill -f "prefect server start"
    sleep 2
fi

echo "Starting Prefect Server with PostgreSQL..."
prefect server start \
    --host 0.0.0.0 \
    --port 4200 \
    > prefect_server.log 2>&1 &
PREFECT_PID=$!

# Ожидание запуска сервера (увеличено время ожидания)
echo "Waiting for Prefect Server to start (10 seconds)..."
sleep 10

# Проверка доступности сервера
if ! check_port 4200; then
    echo "Prefect Server failed to start. Check prefect_server.log for details."
    exit 1
fi

# Создание Work Pool с проверкой существования
if ! prefect work-pool inspect "default" > /dev/null 2>&1; then
    echo "Creating Work Pool..."
    prefect work-pool create "default" --type process
else
    echo "Work Pool 'default' already exists. Skipping creation."
fi

# Запуск Worker
echo "Starting Prefect Worker..."
prefect worker start \
    --pool "default" \
    --limit 5 \
    > prefect_worker.log 2>&1 &
WORKER_PID=$!

# Ожидание запуска Worker
echo "Waiting for Prefect Worker to start (10 seconds)..."
sleep 10

# Запуск FastAPI
echo "Starting FastAPI..."
uvicorn app.main:app --reload > fastapi.log 2>&1 &
FASTAPI_PID=$!

# Ожидание запуска FastAPI
echo "Waiting for FastAPI to start (5 seconds)..."
sleep 5

# Запуск gRPC сервера
echo "Starting gRPC Server..."
python3 -m app.grpc.grpc_server > grpc_server.log 2>&1 &
GRPC_PID=$!

# Сохраняем PID в файл
echo "PREFECT_PID=$PREFECT_PID" > .pids
echo "WORKER_PID=$WORKER_PID" >> .pids
echo "FASTAPI_PID=$FASTAPI_PID" >> .pids
echo "GRPC_PID=$GRPC_PID" >> .pids

echo "All services started:"
echo "- Prefect UI: http://localhost:4200"
echo "- FastAPI:    http://localhost:8000"
echo "- gRPC:       localhost:50051"
