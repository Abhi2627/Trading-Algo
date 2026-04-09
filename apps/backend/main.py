from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os

load_dotenv()

from core.database import close_db
from api.routes.assets import router as assets_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Trading Platform API starting in {os.getenv('APP_ENV')} mode...")
    # DB tables are managed by Alembic migrations, not create_all
    # Run: alembic upgrade head — before starting the app in production
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
    allow_origins=[
        "http://localhost:1420",   # Tauri desktop dev
        "http://localhost:3000",   # web dev fallback
        "http://localhost:8080",   # Flutter web dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key

@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "env": os.getenv("APP_ENV", "development")
    }

@app.get("/secure-health", tags=["system"])
async def secure_health(key: str = Security(verify_api_key)):
    return {"status": "ok", "authenticated": True}

@app.get("/", tags=["system"])
def read_root():
    return {"message": "Trading Platform API is running. Visit /docs for API reference."}

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(assets_router)
