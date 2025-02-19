#!/bin/bash

if [ -f .pids ]; then
    source .pids
    kill $FASTAPI_PID $TASKIQ_PID $GRPC_PID
    rm .pids
    echo "Processes stoped."
else
    echo "File .pids not found. Processes are not active."
fi
