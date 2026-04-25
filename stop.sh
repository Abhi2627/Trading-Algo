#!/bin/bash
# Stop all AlgoTrade services cleanly
ROOT="/Users/abhaydandge/Projects/trading-platform"

echo "Stopping AlgoTrade..."

# Kill by PID files
for service in uvicorn celery; do
    PID_FILE="$ROOT/logs/$service.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null && echo "  Stopped $service (PID $PID)" || echo "  $service already stopped"
        rm -f "$PID_FILE"
    fi
done

# Kill anything still on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Kill all Celery and uvicorn processes for this project
pkill -f 'celery.*trading_platform' 2>/dev/null || true
pkill -f 'uvicorn main:app' 2>/dev/null || true

# Stop Docker
cd "$ROOT"
docker-compose stop

echo ""
echo "AlgoTrade stopped. You can close this terminal."
