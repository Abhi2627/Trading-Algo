# Run locally to fetch 5-year data and prepare for Kaggle upload
# Usage: cd trading-platform && source apps/backend/venv/bin/activate && python infra/kaggle/01_upload_ohlcv.py

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend'))
_env = os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend', '.env')
from dotenv import load_dotenv
load_dotenv(_env, override=True)

import json
from pathlib import Path
from services.market_data.fetcher import fetch_historical

SYMBOLS = [
    'NSE:RELIANCE', 'NSE:TCS',        'NSE:HDFCBANK',
    'NSE:INFY',     'NSE:ICICIBANK',  'NSE:SBIN',
    'NSE:BHARTIARTL','NSE:KOTAKBANK', 'NSE:LT',
    'NSE:AXISBANK', 'NSE:MARUTI',     'NSE:WIPRO',
    'NSE:HINDUNILVR','NSE:SUNPHARMA', 'NSE:TITAN',
    'NSE:BAJFINANCE','NSE:ASIANPAINT','NSE:ITC',
    'NSE:ONGC',     'NSE:ULTRACEMCO',
]

OUTPUT_DIR = Path('/tmp/trading_ohlcv')
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Downloading 5-year OHLCV for {len(SYMBOLS)} symbols...")
successful = []
for sym in SYMBOLS:
    df = fetch_historical(sym, period_days=1825)
    if df is None or len(df) < 200:
        print(f"  {sym}: FAILED")
        continue
    safe = sym.replace(':', '_')
    df.to_csv(OUTPUT_DIR / f"{safe}.csv")
    successful.append(sym)
    print(f"  {sym}: {len(df)} rows -> {safe}.csv")

with open(OUTPUT_DIR / 'meta.json', 'w') as f:
    json.dump({"symbols": successful, "count": len(successful)}, f, indent=2)

print(f"\nDone. {len(successful)}/{len(SYMBOLS)} symbols saved to {OUTPUT_DIR}")
print("\nNext: upload /tmp/trading_ohlcv as a Kaggle dataset named: trading-platform-ohlcv-v2")
