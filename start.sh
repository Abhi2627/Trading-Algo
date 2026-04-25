#!/bin/bash
# =============================================================================
# AlgoTrade Self-Healing Startup Script
# Usage: ./start.sh
# Everything runs automatically. Open a second VS Code terminal and run:
#   tail -f logs/celery.log    to watch live trading
# =============================================================================
set -euo pipefail

ROOT="/Users/abhaydandge/Projects/trading-platform"
BACKEND="$ROOT/apps/backend"
API_KEY="abhay-algotrade-2025"
API_URL="http://localhost:8000"

mkdir -p "$ROOT/logs"

log()  { echo "[$(date '+%H:%M:%S')] $1"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $1"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠️  $1"; }

trap 'echo ""; echo "Stopping AlgoTrade..."; "$ROOT/stop.sh"; exit 0' INT TERM

wait_for() {
    local name=$1 cmd=$2 retries=${3:-20} delay=${4:-2}
    log "Waiting for $name..."
    for i in $(seq 1 $retries); do
        if eval "$cmd" &>/dev/null; then ok "$name is ready"; return 0; fi
        sleep $delay
    done
    echo "❌ $name did not start"; return 1
}

# ── Step 1: Docker ────────────────────────────────────────────────────────────
log "Starting Docker..."
cd "$ROOT"
docker-compose up -d
wait_for "Postgres" "docker exec trading-platform-postgres-1 pg_isready -U trading_user -d trading_db" 30 2
wait_for "Redis"    "docker exec trading-platform-redis-1 redis-cli ping" 20 2

# ── Step 2: Backend setup ─────────────────────────────────────────────────────
cd "$BACKEND"
source venv/bin/activate

log "Running migrations..."
alembic upgrade head
ok "Migrations done"

# ── Step 3: Seed DB and wallet ────────────────────────────────────────────────
log "Checking seed..."
python3 << 'PYEOF'
import asyncio, sys
sys.path.insert(0, '.')
async def run():
    from core.database import AsyncSessionLocal, init_db
    from core.models import Asset, PaperWallet
    from sqlalchemy import select, func
    await init_db()
    async with AsyncSessionLocal() as db:
        count = await db.scalar(select(func.count()).select_from(Asset))
        if count == 0:
            from services.market_data.assets import seed_assets
            n = await seed_assets(db)
            await db.commit()
            print(f"Seeded {n} assets")
        else:
            print(f"Assets OK: {count}")
        wallet = await db.scalar(select(PaperWallet).limit(1))
        if wallet is None:
            db.add(PaperWallet())
            await db.commit()
            print("Wallet created")
        else:
            print(f"Wallet OK: cash=₹{wallet.cash_balance:.0f}")
asyncio.run(run())
PYEOF

# ── Step 4: Start uvicorn ─────────────────────────────────────────────────────
log "Starting FastAPI..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sleep 1
uvicorn main:app --port 8000 --host 0.0.0.0 --log-level warning \
    > "$ROOT/logs/uvicorn.log" 2>&1 &
echo $! > "$ROOT/logs/uvicorn.pid"
wait_for "FastAPI" "curl -sf http://localhost:8000/health" 20 2

# ── Step 5: Ollama check ──────────────────────────────────────────────────────
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama running"
else
    warn "Ollama down — starting..."
    ollama serve &>/dev/null & sleep 3
    curl -sf http://localhost:11434/api/tags &>/dev/null && ok "Ollama started" || warn "Ollama failed — sentiment will use fallback"
fi

# ── Step 6: Start Celery ──────────────────────────────────────────────────────
log "Starting Celery..."
pkill -f 'celery.*trading_platform' 2>/dev/null || true
sleep 1
celery -A workers.celery_app worker --loglevel=info --pool=solo \
    > "$ROOT/logs/celery.log" 2>&1 &
CELERY_PID=$!
echo $CELERY_PID > "$ROOT/logs/celery.pid"
sleep 4
kill -0 $CELERY_PID 2>/dev/null && ok "Celery running (PID $CELERY_PID)" || warn "Celery may have crashed"

# ── Step 7: Morning scan ──────────────────────────────────────────────────────
HOUR=$(date '+%H')
if [ "$HOUR" -ge 8 ] && [ "$HOUR" -le 10 ]; then
    log "Queueing morning scan..."
    python3 -c "
import sys; sys.path.insert(0, '.')
from workers.tasks.market_tasks import scan_all_assets
r = scan_all_assets.delay()
print(f'Scan queued: {r.id}')
"
fi

# ── Status summary ────────────────────────────────────────────────────────────
WALLET=$(curl -sf -H "X-API-Key: $API_KEY" "$API_URL/wallet/summary" 2>/dev/null || echo '{}')
EQUITY=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'₹{d.get(\"total_equity\",0):,.0f}')" 2>/dev/null || echo "unknown")
CASH=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'₹{d.get(\"cash_balance\",0):,.0f}')" 2>/dev/null || echo "unknown")
POSITIONS=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('open_count',0))" 2>/dev/null || echo "0")

echo ""
echo "================================================"
echo " AlgoTrade is RUNNING"
echo "================================================"
echo " Backend:        $API_URL"
echo " Wallet equity:  $EQUITY"
echo " Cash:           $CASH"
echo " Open positions: $POSITIONS"
echo ""
echo " ┌─────────────────────────────────────────┐"
echo " │ Watch live trading (in a new terminal): │"
echo " │   tail -f logs/celery.log               │"
echo " │                                         │"
echo " │ Stop everything:  Ctrl+C  or ./stop.sh  │"
echo " └─────────────────────────────────────────┘"
echo "================================================"
echo ""
echo "Watchdog active — press Ctrl+C to stop all services"

# ── Watchdog loop ─────────────────────────────────────────────────────────────
while true; do
    sleep 30

    # Restart uvicorn if crashed
    UVICORN_PID=$(cat "$ROOT/logs/uvicorn.pid" 2>/dev/null || echo "")
    if [ -n "$UVICORN_PID" ] && ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        warn "Uvicorn crashed — restarting..."
        uvicorn main:app --port 8000 --host 0.0.0.0 --log-level warning \
            >> "$ROOT/logs/uvicorn.log" 2>&1 &
        echo $! > "$ROOT/logs/uvicorn.pid"
        ok "Uvicorn restarted"
    fi

    # Restart Celery if crashed
    if ! kill -0 $CELERY_PID 2>/dev/null; then
        warn "Celery crashed — restarting..."
        celery -A workers.celery_app worker --loglevel=info --pool=solo \
            >> "$ROOT/logs/celery.log" 2>&1 &
        CELERY_PID=$!
        echo $CELERY_PID > "$ROOT/logs/celery.pid"
        ok "Celery restarted (PID $CELERY_PID)"
    fi
done
