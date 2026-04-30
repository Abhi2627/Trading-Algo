# scripts/seed_if_empty.py
# Run on container startup to seed assets and wallet if DB is empty.
# Called from docker-compose.prod.yml backend command.
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def seed():
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
            db.add(PaperWallet())
            await db.commit()
            print("Wallet created: ₹2,000 starting capital")
        else:
            print(f"Wallet OK: cash=₹{wallet.cash_balance:.0f} equity=₹{wallet.total_equity:.0f}")


asyncio.run(seed())
