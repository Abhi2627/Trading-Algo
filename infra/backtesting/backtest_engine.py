# infra/backtesting/backtest_engine.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend'))

import pandas as pd
import numpy as np
from dataclasses import dataclass
from transaction_costs import get_cost_model
from performance_metrics import Trade, PerformanceCalculator
from services.market_data.fetcher import fetch_historical
from services.market_data.features import compute_features, detect_market_regime
from models.rl.agent import get_rl_agent
from models.transformer.forecaster import get_forecaster
from models.sentiment.sentiment_service import get_sentiment_service
from models.ensemble.ensemble import get_ensemble_engine


@dataclass
class BacktestConfig:
    symbols:          list
    start_date:       str
    end_date:         str
    initial_capital:  float = 100000.0
    max_position_pct: float = 0.10
    min_confidence:   float = 0.50
    stop_loss_pct:    float = 0.05
    take_profit_pct:  float = 0.09
    is_largecap:      bool  = True
    warmup_days:      int   = 60


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
        all_data = {}
        for sym in self.cfg.symbols:
            df = fetch_historical(sym, period_days=730)
            if df is not None and len(df) >= self.cfg.warmup_days:
                all_data[sym] = df
                print(f"  {sym}: {len(df)} rows")
            else:
                print(f"  {sym}: SKIPPED")

        start = pd.Timestamp(self.cfg.start_date)
        end   = pd.Timestamp(self.cfg.end_date)
        dates = pd.bdate_range(start=start, end=end)

        print(f"\nRunning {start.date()} to {end.date()} ({len(dates)} days)")

        rl_agent   = get_rl_agent()
        forecaster = get_forecaster()
        sentiment  = get_sentiment_service()
        ensemble   = get_ensemble_engine()

        for i, today in enumerate(dates):
            self._fill_pending(all_data, today)
            self._check_exits(all_data, today)

            for sym, df in all_data.items():
                if sym in self.positions:
                    continue
                hist = df[df.index <= today]
                if len(hist) < self.cfg.warmup_days:
                    continue
                features_df = compute_features(hist)
                if features_df is None or len(features_df) < 2:
                    continue
                latest    = features_df.iloc[-1].to_dict()
                regime    = detect_market_regime(hist)
                hist_feats = [r.to_dict() for _, r in features_df.tail(60).iterrows()]
                rl_out   = rl_agent.predict(latest)
                tf_out   = forecaster.predict(hist_feats)
                sent_out = {"score": 0.0, "label": "neutral"}
                result   = ensemble.blend(rl_output=rl_out, transformer_output=tf_out,
                               sentiment_output=sent_out, market_regime=regime)
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
            if low <= pos["stop"]:
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
