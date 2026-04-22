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

# Full Nifty 50 — 50 symbols for better transformer training
SYMBOLS = [
    # Original 20
    'NSE:RELIANCE',  'NSE:TCS',        'NSE:HDFCBANK',
    'NSE:INFY',      'NSE:ICICIBANK',  'NSE:SBIN',
    'NSE:BHARTIARTL','NSE:KOTAKBANK',  'NSE:LT',
    'NSE:AXISBANK',  'NSE:MARUTI',     'NSE:WIPRO',
    'NSE:HINDUNILVR','NSE:SUNPHARMA',  'NSE:TITAN',
    'NSE:BAJFINANCE','NSE:ASIANPAINT', 'NSE:ITC',
    'NSE:ONGC',      'NSE:ULTRACEMCO',
    # New 30 to complete Nifty 50
    'NSE:NESTLEIND', 'NSE:ADANIENT',   'NSE:ADANIPORTS',
    'NSE:POWERGRID', 'NSE:NTPC',       'NSE:TECHM',
    'NSE:HCLTECH',   'NSE:BAJAJFINSV', 'NSE:JSWSTEEL',
    'NSE:TATAMOTORS','NSE:TATACONSUM', 'NSE:TATASTEEL',
    'NSE:GRASIM',    'NSE:DIVISLAB',   'NSE:DRREDDY',
    'NSE:EICHERMOT', 'NSE:HEROMOTOCO', 'NSE:HINDALCO',
    'NSE:INDUSINDBK','NSE:APOLLOHOSP', 'NSE:BPCL',
    'NSE:BRITANNIA', 'NSE:CIPLA',      'NSE:COALINDIA',
    'NSE:SBILIFE',   'NSE:HDFCLIFE',   'NSE:UPL',
    'NSE:SHREECEM',  'NSE:M&M',        'NSE:BAJAJ-AUTO',
]

OUTPUT_DIR = Path('/tmp/trading_ohlcv_v3')
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Downloading 5-year OHLCV for {len(SYMBOLS)} symbols...")
successful = []
failed     = []

for sym in SYMBOLS:
    df = fetch_historical(sym, period_days=1825)
    if df is None or len(df) < 200:
        print(f"  {sym}: FAILED")
        failed.append(sym)
        continue
    safe = sym.replace(':', '_')
    df.to_csv(OUTPUT_DIR / f"{safe}.csv")
    successful.append(sym)
    print(f"  {sym}: {len(df)} rows")

with open(OUTPUT_DIR / 'meta.json', 'w') as f:
    json.dump({"symbols": successful, "count": len(successful)}, f, indent=2)

print(f"\nDone. {len(successful)}/{len(SYMBOLS)} symbols saved to {OUTPUT_DIR}")
if failed:
    print(f"Failed: {failed}")
print(f"\nNext steps:")
print(f"1. Go to kaggle.com/datasets -> New Dataset")
print(f"2. Upload folder: {OUTPUT_DIR}")
print(f"3. Name it: trading-platform-ohlcv-v3")
print(f"4. Then run 02_feature_engineering.py on Kaggle with this new dataset")
