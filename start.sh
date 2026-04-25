#!/bin/bash
# =============================================================================
# AlgoTrade Self-Healing Startup Script
# Run this every trading day morning: ./start.sh
# It handles everything automatically — no manual steps needed.
# =============================================================================
set -euo pipefail

ROOT="/Users/abhaydandge/Projects/trading-platform"
BACKEND="$ROOT/apps/backend"
API_KEY="abhay-algotrade-2025"
API_URL="http://localhost:8000"
LOG_FILE="$ROOT/logs/startup.log"

# Trap Ctrl+C and run stop.sh automatically
# This means pressing Ctrl+C in this terminal stops everything cleanly
trap 'echo ""; echo "Caught Ctrl+C — stopping AlgoTrade..."; "$ROOT/stop.sh"; exit 0' INT TERM

mkdir -p "$ROOT/logs"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "================================================"
echo " AlgoTrade Startup — $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================"

# ── Helper functions ─────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $1"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $1"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠️  $1"; }
fail() { echo "[$(date '+%H:%M:%S')] ❌ $1"; }

wait_for() {
    local name=$1 cmd=$2 retries=${3:-20} delay=${4:-2}
    log "Waiting for $name..."
    for i in $(seq 1 $retries); do
        if eval "$cmd" &>/dev/null; then
            ok "$name is ready"
            return 0
        fi
        sleep $delay
    done
    fail "$name did not start after $((retries * delay))s"
    return 1
}

api() { curl -sf -H "X-API-Key: $API_KEY" "$API_URL$1"; }

# ── Step 1: Docker services ───────────────────────────────────────────────────
log "Starting Docker services..."
cd "$ROOT"
docker-compose up -d

# Wait for Postgres
wait_for "Postgres" \
    "docker exec trading-platform-postgres-1 pg_isready -U trading_user -d trading_db" \
    30 2

# Wait for Redis
wait_for "Redis" \
    "docker exec trading-platform-redis-1 redis-cli ping" \
    20 2

# ── Step 2: Backend ───────────────────────────────────────────────────────────
log "Activating Python venv..."
cd "$BACKEND"
source venv/bin/activate

# Run migrations (safe to run multiple times)
log "Running DB migrations..."
alembic upgrade head
ok "Migrations applied"

# ── Step 3: Seed DB if empty ─────────────────────────────────────────────────
log "Checking asset seed..."
python3 << 'PYEOF'
import asyncio, sys
sys.path.insert(0, '.')

async def ensure_seeded():
    from core.database import AsyncSessionLocal, init_db
    from core.models import Asset, PaperWallet
    from sqlalchemy import select, func

    await init_db()

    async with AsyncSessionLocal() as db:
        # Seed assets if empty
        count = await db.scalar(select(func.count()).select_from(Asset))
        if count == 0:
            print("DB empty — seeding assets...")
            from services.market_data.assets import seed_assets
            n = await seed_assets(db)
            await db.commit()
            print(f"Seeded {n} assets")
        else:
            print(f"Assets OK: {count} in DB")

        # Create wallet if missing
        wallet = await db.scalar(select(PaperWallet).limit(1))
        if wallet is None:
            from core.models import PaperWallet
            w = PaperWallet()
            db.add(w)
            await db.commit()
            print("Wallet created")
        else:
            print(f"Wallet OK: cash=₹{wallet.cash_balance:.0f} equity=₹{wallet.total_equity:.0f}")

asyncio.run(ensure_seeded())
PYEOF

# ── Step 4: Start uvicorn ─────────────────────────────────────────────────────
log "Starting FastAPI backend..."
# Kill any existing uvicorn on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sleep 1

uvicorn main:app --port 8000 --host 0.0.0.0 \
    --log-level warning \
    --access-log \
    > "$ROOT/logs/uvicorn.log" 2>&1 &
UVICORN_PID=$!
echo $UVICORN_PID > "$ROOT/logs/uvicorn.pid"

# Wait for API to respond
wait_for "FastAPI" \
    "curl -sf http://localhost:8000/health" \
    20 2

# ── Step 5: Self-healing checks ───────────────────────────────────────────────
log "Running self-healing checks..."

# Check Ollama
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama running"
else
    warn "Ollama not running — starting it..."
    ollama serve &>/dev/null &
    sleep 3
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        ok "Ollama started"
    else
        warn "Ollama failed to start — sentiment will use fallback"
    fi
fi

# Verify signal pipeline works (quick smoke test)
python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')
try:
    from models.transformer.forecaster import get_forecaster
    f = get_forecaster()
    if f.is_ready:
        print("Transformer: ready")
    else:
        print("Transformer: NOT ready — check data/trained_models/")
except Exception as e:
    print(f"Transformer check failed: {e}")

try:
    from models.rl.agent import get_rl_agent
    a = get_rl_agent()
    print(f"RL Agent: ready ({a._model_path.name if hasattr(a, '_model_path') else 'loaded'})")
except Exception as e:
    print(f"RL Agent check failed: {e}")
PYEOF

# ── Step 6: Start Celery ─────────────────────────────────────────────────────
log "Starting Celery worker..."
pkill -f 'celery.*trading_platform' 2>/dev/null || true
sleep 1

# Start Celery in background, log to file
celery -A workers.celery_app worker \
    --loglevel=info \
    --pool=solo \
    > "$ROOT/logs/celery.log" 2>&1 &
CELERY_PID=$!
echo $CELERY_PID > "$ROOT/logs/celery.pid"

# Wait for Celery to connect
sleep 4
if kill -0 $CELERY_PID 2>/dev/null; then
    ok "Celery running (PID $CELERY_PID)"
    ok "To watch Celery live: tail -f $ROOT/logs/celery.log"
else
    warn "Celery may have crashed — check logs/celery.log"
fi

# ── Step 7: Morning tasks ─────────────────────────────────────────────────────
HOUR=$(date '+%H')
if [ "$HOUR" -ge 8 ] && [ "$HOUR" -le 10 ]; then
    log "Market hours — queueing morning scan..."
    python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')
from workers.tasks.market_tasks import scan_all_assets
result = scan_all_assets.delay()
print(f"Morning scan queued: {result.id}")
PYEOF
fi

# ── Step 8: Health summary ────────────────────────────────────────────────────
echo ""
echo "================================================"
echo " AlgoTrade is running"
echo "================================================"
echo " Backend:   $API_URL"
echo " API Docs:  $API_URL/docs"
echo " Logs:      $ROOT/logs/"
echo ""

# Show wallet status
WALLET=$(api /wallet/summary 2>/dev/null || echo '{}')
EQUITY=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"₹{d.get('total_equity',0):,.0f}\")" 2>/dev/null || echo "unknown")
CASH=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"₹{d.get('cash_balance',0):,.0f}\")" 2>/dev/null || echo "unknown")
POSITIONS=$(echo $WALLET | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('open_count',0))" 2>/dev/null || echo "0")

echo " Wallet equity:    $EQUITY"
echo " Cash available:   $CASH"
echo " Open positions:   $POSITIONS"
echo ""
echo " To stop:   ./stop.sh"
echo " To check:  curl $API_URL/health"
echo "================================================"

# ── Keep alive: restart crashed services ─────────────────────────────────────
log "Watchdog active — monitoring services..."
while true; do
    sleep 30

    # Restart uvicorn if crashed
    if ! kill -0 $UVICORN_PID 2>/dev/null; then
        warn "Uvicorn crashed — restarting..."
        uvicorn main:app --port 8000 --host 0.0.0.0 \
            --log-level warning \
            > "$ROOT/logs/uvicorn.log" 2>&1 &
        UVICORN_PID=$!
        echo $UVICORN_PID > "$ROOT/logs/uvicorn.pid"
        ok "Uvicorn restarted (PID $UVICORN_PID)"
    fi

    # Restart Celery if crashed
    if ! kill -0 $CELERY_PID 2>/dev/null; then
        warn "Celery crashed — restarting..."
        celery -A workers.celery_app worker \
            --loglevel=info \
            --pool=solo \
            > "$ROOT/logs/celery.log" 2>&1 &
        CELERY_PID=$!
        echo $CELERY_PID > "$ROOT/logs/celery.pid"
        ok "Celery restarted (PID $CELERY_PID)"
    fi
done
