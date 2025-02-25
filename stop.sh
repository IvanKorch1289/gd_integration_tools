#!/bin/bash

if [ ! -f .pids ]; then
    echo "No .pids file found. Nothing to stop."
    exit 1
fi

echo "Stopping services..."

# Читаем PID из файла
source .pids

# Останавливаем процессы
kill -TERM $FASTAPI_PID 2>/dev/null && echo "Stopped FastAPI"
kill -TERM $GRPC_PID 2>/dev/null && echo "Stopped gRPC Server"
kill -TERM $WORKER_PID 2>/dev/null && echo "Stopped Prefect Worker"
kill -TERM $PREFECT_PID 2>/dev/null && echo "Stopped Prefect Server"

# Удаляем файл PID
rm .pids

# Дополнительная очистка
pkill -f "uvicorn app.main:app"
pkill -f "prefect worker start"
pkill -f "prefect server start"
pkill -f "python3 -m app.grpc.grpc_server"

echo "All services stopped."
