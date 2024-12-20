#!/bin/bash

set -e

# Запуск FastAPI
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 2>&1 &

# Запуск Flet
flet run --web --port 5030 frontend 2>&1 & 

# Запуск Celery рабочего процесса с 4 воркерами
celery -A backend.core.tasks worker -l INFO -c 8 -E 2>&1 &

# Запуск Celery планировщика задач (Beat)
celery -A backend.core.tasks beat -l INFO 2>&1 &

# Запуск Flower
celery -A backend.core.tasks flower --port=8888 2>&1 &

echo "Приложения запущены!"

wait