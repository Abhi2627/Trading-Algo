#!/bin/bash
echo "Starting AlgoTrade..."
cd /Users/abhaydandge/Projects/trading-platform

# Start Docker
docker-compose up -d
sleep 5

# Start backend
cd apps/backend
source venv/bin/activate
alembic upgrade head

# Seed if empty
python3 -c "
import asyncio, sys
sys.path.insert(0, '.')
async def setup():
    from core.database import AsyncSessionLocal
    from core.models import Asset
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as db:
        count = await db.scalar(select(func.count()).select_from(Asset))
        if count == 0:
            from services.market_data.assets import seed_assets
            n = await seed_assets(db)
            await db.commit()
            print(f'Seeded {n} assets')
        else:
            print(f'{count} assets already in DB')
asyncio.run(setup())
"

uvicorn main:app --reload --port 8000 --host 0.0.0.0 &
sleep 3

# Topup wallet if needed
python3 -c "
import httpx
r = httpx.post('http://localhost:8000/wallet/topup',
    headers={'X-API-Key': 'abhay-algotrade-2025'})
print('Wallet:', r.json())
"

# Start Celery
celery -A workers.celery_app worker --loglevel=info --pool=solo &

echo "AlgoTrade running. Backend: http://localhost:8000"
wait
