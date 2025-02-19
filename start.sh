#!/bin/bash

# Terminal 1 - Start FastAPI
# memray run -o fastapi_profile.bin -m uvicorn app.main:app --reload
uvicorn app.main:app --reload &
FASTAPI_PID=$!

# Function to check if FastAPI is fully loaded
wait_for_fastapi() {
    while ! nc -z localhost 8000; do
        echo "Waiting for FastAPI to start..."
        sleep 1
    done
    echo "FastAPI is up and running!"
}

# Wait for FastAPI to start
wait_for_fastapi

# Terminal 2 - Start gRPC server
python3 -m app.grpc.grpc_server &
GRPC_PID=$!

# Terminal 3 - Start Taskiq worker
taskiq worker --workers 1 --reload app.background_tasks.worker:broker app.background_tasks.tasks &
TASKIQ_PID=$!

# Save PIDs of the processes to a file
echo "FASTAPI_PID=$FASTAPI_PID" > .pids
echo "TASKIQ_PID=$TASKIQ_PID" >> .pids
echo "GRPC_PID=$GRPC_PID" >> .pids

echo "FastAPI, gRPC, and Taskiq worker have been started."
