#!/bin/bash
set -e
echo "Starting AlgoTrade..."

# Start Docker services
docker-compose up -d
sleep 4

# Backend
cd apps/backend
source venv/bin/activate

# Run migrations + seed if empty
python3 -c "
import asyncio, sys, os
sys.path.insert(0, '.')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://trading_user:trading_pass@localhost:5432/trading_db')

async def setup():
    from core.database import init_db, AsyncSessionLocal
    from core.models import Asset
    from sqlalchemy import select, func
    await init_db()
    async with AsyncSessionLocal() as db:
        count = await db.scalar(select(func.count()).select_from(Asset))
        if count == 0:
            print('DB empty — seeding assets...')
            from services.market_data.assets import seed_assets
            inserted = await seed_assets(db)
            await db.commit()
            print(f'Seeded {inserted} assets')
        else:
            print(f'DB has {count} assets — skipping seed')

asyncio.run(setup())
"

echo "Starting uvicorn..."
uvicorn main:app --reload --port 8000 --host 0.0.0.0 &
UVICORN_PID=$!

sleep 3

# Topup wallet if zero balance
python3 -c "
import httpx, time
time.sleep(2)
r = httpx.post('http://localhost:8000/wallet/topup', headers={'X-API-Key': 'abhay-algotrade-2025'})
print('Wallet:', r.json())
"

echo "Starting Celery..."
celery -A workers.celery_app worker --loglevel=info --pool=solo &

echo ""
echo "AlgoTrade is running."
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

wait $UVICORN_PID
