#!/bin/bash
# Stop all AlgoTrade services and close all related Terminal windows
ROOT="/Users/abhaydandge/Projects/trading-platform"

echo "Stopping AlgoTrade..."

# Kill by PID files
for service in uvicorn celery; do
    PID_FILE="$ROOT/logs/$service.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null && echo "Stopped $service (PID $PID)" || echo "$service already stopped"
        rm -f "$PID_FILE"
    fi
done

# Kill anything still on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Kill all Celery processes for this project
pkill -f 'celery.*trading_platform' 2>/dev/null || true

# Kill any uvicorn processes
pkill -f 'uvicorn main:app' 2>/dev/null || true

# Stop Docker
cd "$ROOT"
docker-compose stop

echo "AlgoTrade stopped."
echo ""
echo "Closing Terminal windows in 2 seconds..."
sleep 2

# Close all Terminal windows/tabs related to AlgoTrade
# This closes the Celery tab, the start.sh terminal, and any others
osascript << 'APPLESCRIPT'
tell application "Terminal"
    -- Close any window running celery, uvicorn, or start.sh
    set windowsToClose to {}
    repeat with w in windows
        repeat with t in tabs of w
            set tabCmd to custom title of t
            if tabCmd contains "celery" or tabCmd contains "start.sh" or tabCmd contains "algotrade" then
                set end of windowsToClose to {w, t}
            end if
        end repeat
    end repeat
    -- Close identified tabs
    repeat with pair in windowsToClose
        try
            close item 2 of pair
        end try
    end repeat
    -- If only one window remains, just clear it
    if (count of windows) is 1 then
        do script "clear && echo 'AlgoTrade stopped.'" in front window
    end if
end tell
APPLESCRIPT

# Force quit: close ALL terminal windows except the current one
# Only runs if above didn't fully clean up
if [ "$(osascript -e 'tell application "Terminal" to count windows')" -gt 1 ]; then
    osascript << 'APPLESCRIPT'
tell application "Terminal"
    set winCount to count of windows
    -- Close all but the last window (which is the one running stop.sh)
    repeat winCount - 1 times
        close window 1
    end repeat
end tell
APPLESCRIPT
fi

echo "Done. All services stopped and terminals closed."
