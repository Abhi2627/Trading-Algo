# services/chat/rag_retriever.py
# Retrieval-Augmented Generation context builder.
# Pulls relevant data from DB based on query intent so the LLM
# never has to guess — it only narrates what actually happened.
#
# Data sources (ranked by query type):
#   1. Trade history     — closed trades with P&L, exit reasons, days held
#   2. Signal outcomes   — model accuracy, what worked / didn't
#   3. Open positions    — current portfolio state
#   4. Daily reports     — LLM narratives from evening reports
#   5. Signal audit      — per-symbol model scores and technical indicators
import logging
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

logger = logging.getLogger(__name__)


async def retrieve_context(message: str, db: AsyncSession) -> dict:
    """
    Main entry point. Detects intent from message and retrieves
    the most relevant context from DB.

    Returns a context dict with 'type', 'summary', and raw data fields.
    """
    msg = message.lower()

    # Intent detection — order matters (more specific first)
    if _mentions_specific_stock(msg, db):
        symbol = await _extract_symbol(msg, db)
        if symbol:
            return await _stock_context(symbol, db)

    if any(w in msg for w in ["why did", "why was", "why is", "explain", "reason", "how did"]):
        symbol = await _extract_symbol(msg, db)
        if symbol:
            return await _stock_context(symbol, db)
        return await _recent_trades_context(db)

    if any(w in msg for w in ["loss", "losing", "lost", "down", "negative", "bad trade", "worst"]):
        return await _loss_analysis_context(db)

    if any(w in msg for w in ["profit", "gain", "winning", "best trade", "good trade", "up"]):
        return await _gain_analysis_context(db)

    if any(w in msg for w in ["portfolio", "wallet", "balance", "equity", "cash"]):
        return await _portfolio_context(db)

    if any(w in msg for w in ["accuracy", "win rate", "performance", "how well", "model", "signal"]):
        return await _performance_context(db)

    if any(w in msg for w in ["history", "past", "previous", "last", "recent trade"]):
        return await _recent_trades_context(db)

    if any(w in msg for w in ["report", "summary", "today", "yesterday", "daily"]):
        return await _report_context(db)

    # Default: portfolio + recent trades
    return await _portfolio_context(db)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

async def _stock_context(symbol: str, db: AsyncSession) -> dict:
    """Everything we know about a specific stock — signal, trades, outcomes."""
    from core.models import Signal, Asset, Trade, TradeStatus, SignalOutcome

    # Latest signal
    asset_result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        return {"type": "general", "message": f"No data found for {symbol}"}

    sig_result = await db.execute(
        select(Signal).where(Signal.asset_id == asset.id)
        .order_by(desc(Signal.created_at)).limit(1)
    )
    signal = sig_result.scalar_one_or_none()

    # All trades for this symbol (closed + open)
    trades_result = await db.execute(
        select(Trade).where(Trade.asset_id == asset.id)
        .order_by(desc(Trade.entry_time)).limit(5)
    )
    trades = trades_result.scalars().all()

    # Signal outcomes for this symbol
    outcomes_result = await db.execute(
        select(SignalOutcome)
        .where(SignalOutcome.symbol == symbol)
        .order_by(desc(SignalOutcome.opened_at)).limit(5)
    )
    outcomes = outcomes_result.scalars().all()

    trade_history = []
    for t in trades:
        trade_history.append({
            "status":      t.status.value,
            "entry_price": t.entry_price,
            "exit_price":  t.exit_price,
            "quantity":    t.quantity,
            "realized_pnl": round(t.realized_pnl or 0, 2),
            "pnl_pct":     round(((t.exit_price or t.entry_price) - t.entry_price)
                                  / t.entry_price * 100, 2) if t.entry_price else 0,
            "exit_reason": t.exit_reason,
            "days_held":   round((
                (t.exit_time or __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc)) - t.entry_time
            ).total_seconds() / 86400, 1) if t.entry_time else None,
            "stop_loss":   t.stop_loss,
            "take_profit": t.take_profit,
        })

    outcome_summary = []
    for o in outcomes:
        outcome_summary.append({
            "outcome":     o.outcome.value if hasattr(o.outcome, 'value') else str(o.outcome),
            "pnl_pct":     round((o.pnl_pct or 0) * 100, 2),
            "exit_reason": o.exit_reason,
            "days_held":   o.days_held,
            "confidence":  round(o.signal_confidence * 100, 1),
        })

    indicators = signal.technical_indicators or {} if signal else {}

    return {
        "type":           "stock_deep_dive",
        "symbol":         symbol,
        "name":           asset.name,

        # Latest signal
        "latest_signal": {
            "action":     signal.action.value if signal else "none",
            "confidence": f"{signal.confidence:.0%}" if signal else "N/A",
            "regime":     signal.market_regime if signal else "unknown",
            "rl_score":   round(signal.rl_score, 3) if signal else None,
            "transformer_score": round(signal.transformer_score, 3) if signal else None,
            "sentiment_score":   round(signal.sentiment_score, 3) if signal else None,
            "rsi":        indicators.get("rsi_14"),
            "adx":        indicators.get("adx"),
            "close_vs_ema50": indicators.get("close_vs_ema50"),
            "generated_at": signal.created_at.isoformat() if signal else None,
        } if signal else None,

        "trade_history":   trade_history,
        "outcome_history": outcome_summary,
    }


async def _portfolio_context(db: AsyncSession) -> dict:
    """Current wallet state + open positions with live P&L."""
    from core.models import PaperWallet, Trade, Asset, TradeStatus
    from services.market_data.fetcher import fetch_latest_price

    wallet_result = await db.execute(select(PaperWallet).limit(1))
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        return {"type": "portfolio", "message": "No wallet found"}

    open_result = await db.execute(
        select(Trade, Asset)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.status == TradeStatus.open)
    )
    positions = []
    for trade, asset in open_result.all():
        price = fetch_latest_price(asset.symbol) or trade.entry_price
        pnl   = (price - trade.entry_price) * trade.quantity
        positions.append({
            "symbol":      asset.symbol,
            "entry_price": trade.entry_price,
            "current_price": price,
            "quantity":    trade.quantity,
            "pnl":         round(pnl, 2),
            "pnl_pct":     round((price - trade.entry_price) / trade.entry_price * 100, 2),
            "stop_loss":   trade.stop_loss,
            "take_profit": trade.take_profit,
        })

    return {
        "type":            "portfolio",
        "total_equity":    round(wallet.total_equity, 2),
        "cash_balance":    round(wallet.cash_balance, 2),
        "invested":        round(wallet.invested_balance, 2),
        "unrealized_pnl":  round(wallet.unrealised_pnl, 2),
        "realized_pnl":    round(wallet.realised_pnl, 2),
        "drawdown_pct":    round(wallet.drawdown_pct * 100, 2),
        "risk_mode":       wallet.risk_mode.value,
        "open_positions":  positions,
        "position_count":  len(positions),
    }


async def _recent_trades_context(db: AsyncSession) -> dict:
    """Last 10 closed trades with full details."""
    from core.models import Trade, Asset, TradeStatus

    result = await db.execute(
        select(Trade, Asset)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.status == TradeStatus.closed)
        .order_by(desc(Trade.exit_time))
        .limit(10)
    )
    trades = []
    for trade, asset in result.all():
        trades.append({
            "symbol":      asset.symbol,
            "entry_price": trade.entry_price,
            "exit_price":  trade.exit_price,
            "quantity":    trade.quantity,
            "realized_pnl": round(trade.realized_pnl or 0, 2),
            "pnl_pct":     round(((trade.exit_price or trade.entry_price) - trade.entry_price)
                                  / trade.entry_price * 100, 2),
            "exit_reason": trade.exit_reason,
            "entry_time":  trade.entry_time.strftime("%Y-%m-%d") if trade.entry_time else None,
            "exit_time":   trade.exit_time.strftime("%Y-%m-%d") if trade.exit_time else None,
        })

    total_pnl = sum(t["realized_pnl"] for t in trades)
    wins      = [t for t in trades if t["realized_pnl"] > 0]

    return {
        "type":         "trade_history",
        "recent_trades": trades,
        "summary": {
            "total_trades": len(trades),
            "wins":         len(wins),
            "losses":       len(trades) - len(wins),
            "win_rate":     round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_pnl":    round(total_pnl, 2),
        },
    }


async def _loss_analysis_context(db: AsyncSession) -> dict:
    """Analyse losing trades — what went wrong and why."""
    from core.models import Trade, Asset, TradeStatus, SignalOutcome

    trades_result = await db.execute(
        select(Trade, Asset)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.status == TradeStatus.closed)
        .where(Trade.realized_pnl < 0)
        .order_by(Trade.realized_pnl.asc())  # worst first
        .limit(10)
    )
    losses = []
    for trade, asset in trades_result.all():
        losses.append({
            "symbol":      asset.symbol,
            "pnl":         round(trade.realized_pnl or 0, 2),
            "pnl_pct":     round(((trade.exit_price or trade.entry_price) - trade.entry_price)
                                  / trade.entry_price * 100, 2),
            "exit_reason": trade.exit_reason,
            "entry_time":  trade.entry_time.strftime("%Y-%m-%d") if trade.entry_time else None,
            "exit_time":   trade.exit_time.strftime("%Y-%m-%d") if trade.exit_time else None,
        })

    # Exit reason breakdown
    reason_counts: dict = {}
    for t in losses:
        r = t["exit_reason"] or "unknown"
        reason_counts[r] = reason_counts.get(r, 0) + 1

    return {
        "type":            "loss_analysis",
        "losing_trades":   losses,
        "total_lost":      round(sum(t["pnl"] for t in losses), 2),
        "exit_breakdown":  reason_counts,
        "worst_trade":     losses[0] if losses else None,
    }


async def _gain_analysis_context(db: AsyncSession) -> dict:
    """Best performing trades."""
    from core.models import Trade, Asset, TradeStatus

    result = await db.execute(
        select(Trade, Asset)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.status == TradeStatus.closed)
        .where(Trade.realized_pnl > 0)
        .order_by(desc(Trade.realized_pnl))
        .limit(10)
    )
    wins = []
    for trade, asset in result.all():
        wins.append({
            "symbol":      asset.symbol,
            "pnl":         round(trade.realized_pnl or 0, 2),
            "pnl_pct":     round(((trade.exit_price or trade.entry_price) - trade.entry_price)
                                  / trade.entry_price * 100, 2),
            "exit_reason": trade.exit_reason,
            "exit_time":   trade.exit_time.strftime("%Y-%m-%d") if trade.exit_time else None,
        })

    return {
        "type":         "gain_analysis",
        "winning_trades": wins,
        "total_earned": round(sum(t["pnl"] for t in wins), 2),
        "best_trade":   wins[0] if wins else None,
    }


async def _performance_context(db: AsyncSession) -> dict:
    """Signal accuracy, win rate, and model performance."""
    from core.models import SignalOutcome, Trade, TradeStatus
    from sqlalchemy import func

    # Overall trade stats
    closed_result = await db.execute(
        select(Trade)
        .where(Trade.status == TradeStatus.closed)
    )
    closed = closed_result.scalars().all()
    wins   = [t for t in closed if (t.realized_pnl or 0) > 0]

    # Signal outcome stats
    outcomes_result = await db.execute(
        select(SignalOutcome).where(SignalOutcome.outcome != 'pending')
    )
    outcomes = outcomes_result.scalars().all()

    by_regime: dict = {}
    for o in outcomes:
        regime = o.market_regime or "unknown"
        if regime not in by_regime:
            by_regime[regime] = {"total": 0, "correct": 0}
        by_regime[regime]["total"] += 1
        outcome_val = o.outcome.value if hasattr(o.outcome, 'value') else str(o.outcome)
        if outcome_val == "correct":
            by_regime[regime]["correct"] += 1

    regime_accuracy = {
        k: round(v["correct"] / v["total"] * 100, 1)
        for k, v in by_regime.items() if v["total"] > 0
    }

    return {
        "type":           "performance",
        "total_trades":   len(closed),
        "wins":           len(wins),
        "losses":         len(closed) - len(wins),
        "win_rate":       round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "total_pnl":      round(sum(t.realized_pnl or 0 for t in closed), 2),
        "avg_pnl":        round(sum(t.realized_pnl or 0 for t in closed) / len(closed), 2) if closed else 0,
        "signal_outcomes": len(outcomes),
        "regime_accuracy": regime_accuracy,
    }


async def _report_context(db: AsyncSession) -> dict:
    """Fetch the most recent daily report."""
    from core.models import DailyReport

    result = await db.execute(
        select(DailyReport)
        .order_by(desc(DailyReport.report_date))
        .limit(3)
    )
    reports = result.scalars().all()

    return {
        "type": "reports",
        "reports": [
            {
                "date":     r.report_date.isoformat(),
                "type":     r.report_type.value,
                "accuracy": r.prediction_accuracy_pct,
                "summary":  r.llm_narrative[:500] if r.llm_narrative else r.content[:500],
            }
            for r in reports
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mentions_specific_stock(msg: str, db) -> bool:
    """Quick check if message likely references a stock."""
    stock_keywords = ["nse:", "bse:", "stock", "share", "equity"]
    return any(k in msg for k in stock_keywords)


async def _extract_symbol(message: str, db: AsyncSession) -> Optional[str]:
    """Extract NSE/BSE symbol from message text."""
    from core.models import Asset
    result = await db.execute(select(Asset.symbol, Asset.name))
    assets = result.all()
    for symbol, name in assets:
        ticker = symbol.split(":")[-1].lower()
        name_first = name.lower().split()[0] if name else ""
        if ticker in message or (name_first and len(name_first) > 3 and name_first in message):
            return symbol
    return None
