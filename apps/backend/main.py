from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os

load_dotenv()

from core.database import close_db
from api.routes.assets import router as assets_router
from api.routes.signals import router as signals_router
from api.routes.wallet import router as wallet_router
from api.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Trading Platform API starting in {os.getenv('APP_ENV')} mode...")
    yield
    await close_db()
    print("Trading Platform API shut down.")

app = FastAPI(
    title="Trading Platform API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local dev — restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["system"])
async def health():
    return {
        "status":  "ok",
        "version": "0.1.0",
        "env":     os.getenv("APP_ENV", "development")
    }

@app.get("/", tags=["system"])
def read_root():
    return {"message": "Trading Platform API is running. Visit /docs for API reference."}

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(assets_router)
app.include_router(signals_router)
app.include_router(wallet_router)
app.include_router(chat_router)
