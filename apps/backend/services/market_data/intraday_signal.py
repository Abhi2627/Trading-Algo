# services/market_data/intraday_signal.py
# Intraday signal engine — VWAP breakout + momentum strategy.
#
# Setup conditions (all must be true to enter):
#   1. Price crosses ABOVE VWAP (momentum shift)
#   2. RSI between 45-65 (not overbought, not oversold — momentum zone)
#   3. Volume spike > 1.5x average (institutional participation)
#   4. EMA9 > EMA21 (short-term uptrend)
#   5. 5-bar momentum > 0 (price going up recently)
#
# Exit conditions (whichever triggers first):
#   1. Stop-loss: entry - 1.5x ATR (tight, intraday)
#   2. Take-profit: entry + 3x ATR (2:1 RR)
#   3. Trailing: once +1.5x ATR profit, trail 1x ATR below peak
#   4. Force close: 3:15 PM IST (mandatory)
#   5. VWAP breakdown: price crosses back below VWAP
#
import logging
from dataclasses import dataclass
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Strategy parameters
RSI_MIN            = 45.0   # not oversold
RSI_MAX            = 65.0   # not overbought/chasing
VOL_SPIKE_MIN      = 1.5    # volume must be 1.5x average
ATR_SL_MULT        = 1.5    # SL = 1.5x ATR below entry
ATR_TP_MULT        = 3.0    # TP = 3x ATR above entry (2:1 RR)
ATR_TRAIL_TRIGGER  = 1.5    # trailing activates at +1.5x ATR profit
ATR_TRAIL_DIST     = 1.0    # trail 1x ATR below peak
MIN_CONFIDENCE     = 0.65   # intraday uses lower bar than positional
INTRADAY_MAX_HEAT  = 0.10   # max 10% portfolio heat for intraday


@dataclass
class IntradaySignal:
    symbol:       str
    action:       str          # 'buy' or 'hold'
    confidence:   float
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    atr:          float
    vwap:         float
    rsi:          float
    vol_spike:    float
    close_vs_vwap: float
    reason:       str          # why signal fired or was rejected


def generate_intraday_signal(
    symbol: str,
    df_5min: pd.DataFrame,
) -> IntradaySignal:
    """
    Generate an intraday BUY signal from 5-min OHLCV data.
    Returns signal with action='buy' or action='hold'.
    """
    if df_5min is None or len(df_5min) < 20:
        return IntradaySignal(
            symbol=symbol, action='hold', confidence=0,
            entry_price=0, stop_loss=0, take_profit=0,
            atr=0, vwap=0, rsi=0, vol_spike=0, close_vs_vwap=0,
            reason="Insufficient 5-min data"
        )

    latest = df_5min.iloc[-1]
    prev   = df_5min.iloc[-2] if len(df_5min) >= 2 else latest

    price       = float(latest["close"])
    vwap        = float(latest["vwap"]) if not pd.isna(latest.get("vwap", float("nan"))) else 0
    rsi         = float(latest["rsi"])  if not pd.isna(latest.get("rsi",  float("nan"))) else 50
    vol_spike   = float(latest["vol_spike"]) if not pd.isna(latest.get("vol_spike", float("nan"))) else 1.0
    mom_5       = float(latest["mom_5"])     if not pd.isna(latest.get("mom_5", float("nan"))) else 0
    ema_cross   = float(latest["ema_cross"]) if not pd.isna(latest.get("ema_cross", float("nan"))) else 0
    atr         = float(latest["atr"])       if not pd.isna(latest.get("atr", float("nan"))) else price * 0.005
    close_vs_vwap = float(latest["close_vs_vwap"]) if not pd.isna(latest.get("close_vs_vwap", float("nan"))) else 0

    # VWAP crossover: was below, now above
    prev_cvw = float(prev.get("close_vs_vwap", close_vs_vwap)) if not pd.isna(prev.get("close_vs_vwap", float("nan"))) else close_vs_vwap
    vwap_crossover = prev_cvw < 0 and close_vs_vwap > 0

    # Score each condition (0 or 1), confidence = weighted average
    conditions = {
        "vwap_above":    (close_vs_vwap > 0,    0.30),   # price above VWAP
        "vwap_cross":    (vwap_crossover,         0.20),   # just crossed above
        "rsi_zone":      (RSI_MIN <= rsi <= RSI_MAX, 0.20),
        "vol_spike":     (vol_spike >= VOL_SPIKE_MIN, 0.15),
        "ema_uptrend":   (ema_cross > 0,          0.10),
        "momentum_pos":  (mom_5 > 0,              0.05),
    }

    score = sum(w for cond, w in conditions.values() if cond)

    # All core conditions must pass (VWAP + RSI + volume)
    core_pass = (
        conditions["vwap_above"][0] and
        conditions["rsi_zone"][0] and
        conditions["vol_spike"][0]
    )

    if not core_pass or score < MIN_CONFIDENCE:
        failed = [name for name, (cond, _) in conditions.items() if not cond]
        return IntradaySignal(
            symbol=symbol, action='hold', confidence=score,
            entry_price=price, stop_loss=0, take_profit=0,
            atr=atr, vwap=vwap, rsi=rsi,
            vol_spike=vol_spike, close_vs_vwap=close_vs_vwap,
            reason=f"Conditions failed: {', '.join(failed)} (score={score:.0%})"
        )

    # Compute stops using ATR
    stop_loss   = round(price - ATR_SL_MULT * atr, 2)
    take_profit = round(price + ATR_TP_MULT * atr, 2)

    # Sanity: stop must be > 0.5% below entry, TP must be realistic
    sl_pct = (price - stop_loss) / price
    tp_pct = (take_profit - price) / price
    if sl_pct < 0.003 or tp_pct < 0.006:
        return IntradaySignal(
            symbol=symbol, action='hold', confidence=score,
            entry_price=price, stop_loss=0, take_profit=0,
            atr=atr, vwap=vwap, rsi=rsi,
            vol_spike=vol_spike, close_vs_vwap=close_vs_vwap,
            reason=f"ATR too small: SL={sl_pct:.2%} TP={tp_pct:.2%}"
        )

    passed = [name for name, (cond, _) in conditions.items() if cond]
    reason = (
        f"VWAP breakout: price={price:.2f} VWAP={vwap:.2f} "
        f"RSI={rsi:.1f} vol={vol_spike:.1f}x ATR={atr:.2f} "
        f"conditions=[{', '.join(passed)}]"
    )

    logger.info(f"Intraday BUY {symbol}: {reason}")

    return IntradaySignal(
        symbol        = symbol,
        action        = 'buy',
        confidence    = round(score, 3),
        entry_price   = price,
        stop_loss     = stop_loss,
        take_profit   = take_profit,
        atr           = round(atr, 4),
        vwap          = round(vwap, 2),
        rsi           = round(rsi, 1),
        vol_spike     = round(vol_spike, 2),
        close_vs_vwap = round(close_vs_vwap, 4),
        reason        = reason,
    )


def check_intraday_exit(
    entry_price: float,
    stop_loss:   float,
    take_profit: float,
    atr:         float,
    current_price: float,
    peak_price:  float,
) -> Optional[str]:
    """
    Check if an open intraday position should be closed.
    Returns exit reason string or None if hold.
    """
    # Hard stop
    if current_price <= stop_loss:
        return "intraday_stop_loss"

    # Hard take-profit
    if current_price >= take_profit:
        return "intraday_take_profit"

    # Trailing stop: activates once +1.5x ATR profit
    profit = current_price - entry_price
    if profit >= ATR_TRAIL_TRIGGER * atr:
        trail_stop = peak_price - ATR_TRAIL_DIST * atr
        if current_price <= trail_stop:
            return "intraday_trailing_stop"

    # VWAP breakdown — caller should pass current close_vs_vwap
    # handled in monitor task

    return None
