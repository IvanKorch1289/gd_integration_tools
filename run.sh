#!/bin/bash

set -e

# Запуск Celery рабочего процесса с 4 воркерами
celery -A backend.core.background_tasks worker --loglevel=INFO  -P eventlet 2>&1 &

# Запуск Flower
celery -A backend.core.background_tasks flower --port=8888 2>&1 &

# Запуск FastAPI
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 2>&1 &

echo "Приложения запущены!"

wait