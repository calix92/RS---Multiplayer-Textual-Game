#!/bin/bash

echo "Watching project..."

while inotifywait -r -e create,modify,close_write,move,delete .; do
    echo "Change detected → rebuilding Docker..."
    docker compose build
done
