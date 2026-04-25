#!/bin/bash
# Stop all AlgoTrade services
ROOT="/Users/abhaydandge/Projects/trading-platform"

echo "Stopping AlgoTrade..."

# Kill by PID files
for service in uvicorn celery; do
    PID_FILE="$ROOT/logs/$service.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat $PID_FILE)
        kill $PID 2>/dev/null && echo "Stopped $service (PID $PID)" || echo "$service already stopped"
        rm -f $PID_FILE
    fi
done

# Kill any remaining processes
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
pkill -f 'celery.*trading_platform' 2>/dev/null || true

# Stop Docker
cd "$ROOT"
docker-compose stop

echo "AlgoTrade stopped."
