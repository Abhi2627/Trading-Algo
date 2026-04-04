from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(
    title="Trading Platform API",
    version="0.1.0",
    docs_url="/docs"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420",  # Tauri dev port
                   "http://localhost:3000"],  # Next.js if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "0.1.0"}

@app.get("/secure-health", tags=["system"])
async def secure_health(key: str = Security(verify_api_key)):
    return {"status": "ok", "authenticated": True}

@app.get("/")
def read_root():
    return {"message": "API is running"}