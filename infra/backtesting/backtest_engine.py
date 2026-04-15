# infra/backtesting/backtest_engine.py
import sys, os

# Must load .env before any backend import — config.py reads env at import time
_env = os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend', '.env')
if os.path.exists(_env):
    from dotenv import load_dotenv
    load_dotenv(_env, override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend'))

import pandas as pd
import numpy as np
from dataclasses import dataclass
from transaction_costs import get_cost_model
from performance_metrics import Trade, PerformanceCalculator
from services.market_data.fetcher import fetch_historical
from services.market_data.features import compute_features, detect_market_regime


def _rule_based_signal(features: dict, regime: str) -> dict:
    """
    Technical signal v3 — calibrated for NSE large-caps.
    Target: 30+ trades per year, 3:1 RR ratio.

    Strategy: EMA trend-following with momentum confirmation.
    Entry when trend is established, momentum is positive, not overbought.
    """
    rsi        = features.get('rsi_14')             or 50.0
    ema50_200  = features.get('ema50_above_ema200') or 0
    close_ema50= features.get('close_vs_ema50')     or 0.0
    adx        = features.get('adx')                or 0.0
    vol_ratio  = features.get('volume_ratio')        or 1.0
    macd       = features.get('macd_line')           or 0.0
    macd_above = features.get('macd_above_signal')   or 0
    obv_above  = features.get('obv_above_ma')        or 0

    # Skip highly volatile regime only
    if regime == 'volatile':
        return {'action': 'hold', 'confidence': 0.0}

    # Core conditions
    rsi_ok     = 1.0 if 40 <= rsi <= 68   else 0.0   # wider RSI range
    trend_ok   = 1.0 if ema50_200 == 1    else 0.0   # golden cross required
    price_ok   = 1.0 if close_ema50 > -0.02 else 0.0  # allow slight dip below EMA50
    adx_ok     = 1.0 if adx >= 20         else 0.0   # ADX >= 20 (any trend)
    macd_ok    = 1.0 if macd_above == 1   else 0.0   # MACD cross is enough
    vol_ok     = 1.0 if vol_ratio >= 0.8  else 0.5   # relaxed volume
    obv_ok     = 1.0 if obv_above == 1    else 0.5   # OBV above MA preferred

    # Minimum requirements: trend + not overbought + MACD cross
    must_pass = (trend_ok == 1.0 and rsi_ok == 1.0 and macd_ok == 1.0)
    if not must_pass:
        return {'action': 'hold', 'confidence': 0.0}

    # Weighted score
    score = (
        rsi_ok    * 0.20 +
        trend_ok  * 0.25 +
        price_ok  * 0.15 +
        adx_ok    * 0.15 +
        macd_ok   * 0.10 +
        vol_ok    * 0.08 +
        obv_ok    * 0.07
    )

    if regime == 'trending':
        score = min(score * 1.1, 1.0)

    return {
        'action':     'buy' if score >= 0.50 else 'hold',
        'confidence': round(score, 4),
    }


@dataclass
class BacktestConfig:
    symbols:          list
    start_date:       str
    end_date:         str
    initial_capital:  float = 100000.0
    max_position_pct: float = 0.10
    min_confidence:   float = 0.50
    stop_loss_pct:    float = 0.07
    take_profit_pct:  float = 0.21
    is_largecap:      bool  = True
    warmup_days:      int   = 250
    max_open_positions: int = 12


class BacktestEngine:
    def __init__(self, config: BacktestConfig):
        self.cfg  = config
        self.costs = get_cost_model()
        self.cash  = config.initial_capital
        self.positions = {}
        self.completed = []
        self.equity_history = {}
        self.pending_entries = {}

    def run(self) -> dict:
        print(f"Downloading data for {len(self.cfg.symbols)} symbols...")
        all_data     = {}
        all_features = {}  # precompute full features for each symbol
        for sym in self.cfg.symbols:
            df = fetch_historical(sym, period_days=1825)  # 5 years
            if df is None:
                print(f"  {sym}: SKIPPED (download failed)")
                continue
            features_df = compute_features(df)
            if features_df is None or len(features_df) < 50:
                print(f"  {sym}: SKIPPED (insufficient features)")
                continue
            all_data[sym]     = df
            all_features[sym] = features_df
            print(f"  {sym}: {len(df)} rows, {len(features_df)} valid feature rows")
            print(f"    features: {features_df.index[0].date()} to {features_df.index[-1].date()}")

        if not all_data:
            raise ValueError("No valid data downloaded")

        start = pd.Timestamp(self.cfg.start_date)
        end   = pd.Timestamp(self.cfg.end_date)
        dates = pd.bdate_range(start=start, end=end)

        print(f"\nRunning {start.date()} to {end.date()} ({len(dates)} days)")

        for i, today in enumerate(dates):
            self._fill_pending(all_data, today)
            self._check_exits(all_data, today)

            for sym in all_data:
                if sym in self.positions:
                    continue
                # Respect max concurrent positions
                if len(self.positions) >= self.cfg.max_open_positions:
                    break

                # Use precomputed features sliced to today — no lookahead
                features_df = all_features[sym]
                feat_today  = features_df[features_df.index <= today]
                if len(feat_today) < 10:
                    continue  # not enough history yet

                latest = feat_today.iloc[-1].to_dict()
                # Replace NaN with 0 to be safe
                latest = {k: (v if isinstance(v, (int, float)) and not np.isnan(v) else 0.0)
                          for k, v in latest.items()}

                hist   = all_data[sym][all_data[sym].index <= today]
                regime = detect_market_regime(hist)
                result = _rule_based_signal(latest, regime)

                if result["action"] == "buy" and result["confidence"] >= self.cfg.min_confidence:
                    price = float(hist["close"].iloc[-1])
                    size  = min(self.cash * self.cfg.max_position_pct * result["confidence"],
                                self.cash * 0.95)
                    if size < price:
                        continue
                    qty = int(size // price)
                    self.pending_entries[sym] = {
                        "qty": qty, "ref_price": price,
                        "confidence": result["confidence"], "regime": regime,
                        "stop":   round(price * (1 - self.cfg.stop_loss_pct), 2),
                        "target": round(price * (1 + self.cfg.take_profit_pct), 2),
                    }

            self.equity_history[today] = self._equity(all_data, today)
            if (i + 1) % 50 == 0:
                eq  = self.equity_history[today]
                ret = (eq - self.cfg.initial_capital) / self.cfg.initial_capital * 100
                print(f"  {today.date()}: Rs.{eq:,.0f} ({ret:+.1f}%) {len(self.completed)} trades")

        self._close_all(all_data, dates[-1])
        equity_series = pd.Series(self.equity_history)
        equity_series.index = pd.DatetimeIndex(equity_series.index)
        print(f"\nDone. {len(self.completed)} trades.")
        return {"trades": self.completed, "equity_curve": equity_series, "config": self.cfg}

    def _fill_pending(self, all_data, today):
        filled = []
        for sym, order in self.pending_entries.items():
            td = all_data.get(sym, pd.DataFrame())
            td = td[td.index == today]
            if td.empty:
                continue
            fill   = float(td["open"].iloc[0])
            value  = fill * order["qty"]
            cost   = self.costs.compute(value, is_buy=True, is_largecap=self.cfg.is_largecap)
            if value + cost.total > self.cash:
                continue
            self.cash -= (value + cost.total)
            self.positions[sym] = {
                "qty": order["qty"], "entry_price": fill, "entry_date": today,
                "stop": order["stop"], "target": order["target"],
                "highest_since_entry": fill,
                "confidence": order["confidence"], "regime": order["regime"],
                "entry_cost": cost.total,
            }
            filled.append(sym)
        for s in filled:
            del self.pending_entries[s]

    def _check_exits(self, all_data, today):
        to_close = []
        for sym, pos in self.positions.items():
            df = all_data.get(sym)
            if df is None:
                continue
            td = df[df.index == today]
            if td.empty:
                continue
            low, high = float(td["low"].iloc[0]), float(td["high"].iloc[0])

            # Update trailing stop tracker
            pos["highest_since_entry"] = max(pos["highest_since_entry"], high)
            trailing_stop = pos["highest_since_entry"] * 0.90  # 10% trail

            if low <= trailing_stop:
                to_close.append((sym, trailing_stop, "trailing_stop", today))
            elif low <= pos["stop"]:
                to_close.append((sym, pos["stop"], "stop_loss", today))
            elif high >= pos["target"]:
                to_close.append((sym, pos["target"], "take_profit", today))
        for args in to_close:
            self._close(*args)

    def _close(self, sym, exit_price, reason, exit_date):
        pos   = self.positions.pop(sym)
        value = exit_price * pos["qty"]
        cost  = self.costs.compute(value, is_buy=False, is_largecap=self.cfg.is_largecap)
        tc    = pos["entry_cost"] + cost.total
        pnl   = (exit_price - pos["entry_price"]) * pos["qty"] - tc
        pct   = pnl / (pos["entry_price"] * pos["qty"])
        self.cash += (value - cost.total)
        self.completed.append(Trade(
            symbol=sym, entry_date=pos["entry_date"], exit_date=exit_date,
            entry_price=pos["entry_price"], exit_price=exit_price,
            quantity=pos["qty"], side="long",
            pnl=round(pnl,2), pnl_pct=round(pct,6), cost=round(tc,2),
            signal_confidence=pos["confidence"], market_regime=pos["regime"],
        ))

    def _close_all(self, all_data, last):
        for sym in list(self.positions.keys()):
            df = all_data.get(sym)
            if df is None:
                continue
            d = df[df.index <= last]
            if d.empty:
                continue
            self._close(sym, float(d["close"].iloc[-1]), "end_of_backtest", last)

    def _equity(self, all_data, today):
        inv = sum(
            float(df[df.index <= today]["close"].iloc[-1]) * pos["qty"]
            for sym, pos in self.positions.items()
            if (df := all_data.get(sym)) is not None and not df[df.index <= today].empty
        )
        return self.cash + inv
