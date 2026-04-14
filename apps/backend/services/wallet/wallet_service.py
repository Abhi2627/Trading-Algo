# services/wallet/wallet_service.py
import logging
from datetime import datetime, timezone, date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.models import (
    PaperWallet, WalletTransaction, Trade, Signal, Asset,
    TransactionType, TradeStatus, TradeType, TradeAction, RiskMode,
)
from services.wallet.risk_manager import get_risk_manager
from services.market_data.fetcher import fetch_latest_price

logger = logging.getLogger(__name__)


class WalletService:
    """All wallet operations: balance, trades, P&L, monthly top-up."""

    # ------------------------------------------------------------------ #
    # Wallet retrieval / creation
    # ------------------------------------------------------------------ #

    async def get_or_create(self, db: AsyncSession) -> PaperWallet:
        """Return existing wallet or create one with default settings."""
        result = await db.execute(select(PaperWallet).limit(1))
        wallet = result.scalar_one_or_none()
        if wallet is None:
            wallet = PaperWallet()
            db.add(wallet)
            await db.flush()
            logger.info(f"Created new wallet: equity=₹{wallet.total_equity}")
        return wallet

    async def get_summary(self, db: AsyncSession) -> dict:
        """Return wallet snapshot including all open position P&L."""
        wallet = await self.get_or_create(db)

        # Fetch open trades and compute unrealised P&L
        open_trades_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        rows = open_trades_result.all()

        positions = []
        total_unrealised = 0.0
        for trade, asset in rows:
            current_price = fetch_latest_price(asset.symbol) or trade.entry_price
            pnl = (current_price - trade.entry_price) * trade.quantity
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
            total_unrealised += pnl
            positions.append({
                "symbol":        asset.symbol,
                "name":          asset.name,
                "quantity":      trade.quantity,
                "entry_price":   trade.entry_price,
                "current_price": round(current_price, 2),
                "unrealised_pnl":round(pnl, 2),
                "pnl_pct":       round(pnl_pct * 100, 2),
                "stop_loss":     trade.stop_loss,
                "take_profit":   trade.take_profit,
                "trade_type":    trade.trade_type.value,
                "entry_time":    trade.entry_time.isoformat(),
                "trade_id":      str(trade.id),
            })

        # Do NOT mutate wallet here — summary is read-only
        # Pass computed unrealised into drawdown calculation directly
        effective_equity  = wallet.cash_balance + wallet.invested_balance + total_unrealised
        peak              = wallet.peak_equity if wallet.peak_equity > 0 else effective_equity
        drawdown          = max(0.0, (peak - effective_equity) / peak)
        intraday_alloc    = effective_equity * 0.25
        positional_alloc  = effective_equity * 0.75

        budget = get_risk_manager().check_daily_budget(effective_equity)
        daily_loss = await self._daily_realised_loss(db)

        return {
            "cash_balance":     round(wallet.cash_balance, 2),
            "invested_balance": round(wallet.invested_balance, 2),
            "unrealised_pnl":   round(total_unrealised, 2),
            "realised_pnl":     round(wallet.realized_pnl, 2),
            "total_equity":     round(effective_equity, 2),
            "peak_equity":      round(peak, 2),
            "drawdown_pct":     round(drawdown, 4),
            "risk_mode":        wallet.risk_mode.value,
            "monthly_topup":    wallet.monthly_topup,
            "intraday_allocation":   round(intraday_alloc, 2),
            "positional_allocation": round(positional_alloc, 2),
            "daily_budget": {
                "profit_target":         budget["profit_target"],
                "loss_limit":            budget["loss_limit"],
                "loss_used_today":       round(daily_loss, 2),
                "remaining_loss_budget": round(budget["loss_limit"] - daily_loss, 2),
            },
            "open_positions": positions,
            "open_count":     len(positions),
        }

    # ------------------------------------------------------------------ #
    # Trade execution
    # ------------------------------------------------------------------ #

    async def open_trade(
        self,
        db:          AsyncSession,
        signal_id:   str,
        asset_symbol: str,
        is_intraday: bool = False,
    ) -> dict:
        """
        Execute a paper BUY based on the latest signal.
        Runs risk checks, sizes the position, debits wallet.
        """
        wallet = await self.get_or_create(db)
        rm     = get_risk_manager()

        # Resolve asset and signal
        asset_result = await db.execute(
            select(Asset).where(Asset.symbol == asset_symbol)
        )
        asset = asset_result.scalar_one_or_none()
        if asset is None:
            return {"error": f"Asset {asset_symbol} not found"}

        signal_result = await db.execute(
            select(Signal).where(Signal.id == signal_id)
        )
        signal = signal_result.scalar_one_or_none()
        if signal is None:
            return {"error": f"Signal {signal_id} not found"}

        current_price = fetch_latest_price(asset_symbol)
        if current_price is None:
            return {"error": "Could not fetch current price"}

        # Count open trades
        open_count_result = await db.execute(
            select(func.count(Trade.id)).where(Trade.status == TradeStatus.open)
        )
        open_count = open_count_result.scalar() or 0

        daily_loss = await self._daily_realised_loss(db)
        budget     = rm.check_daily_budget(wallet.total_equity)

        decision = rm.check(
            total_equity=wallet.total_equity,
            cash_balance=wallet.cash_balance,
            current_price=current_price,
            confidence=signal.confidence,
            risk_mode=wallet.risk_mode,
            daily_loss_used=daily_loss,
            daily_loss_limit=budget["loss_limit"],
            is_intraday=is_intraday,
            existing_open_trades=open_count,
        )

        if not decision.approved:
            return {"approved": False, "reason": decision.reason}

        # Debit cash
        wallet.cash_balance     -= decision.position_size
        wallet.invested_balance += decision.position_size
        if wallet.total_equity > wallet.peak_equity:
            wallet.peak_equity = wallet.total_equity
        wallet.risk_mode = wallet.compute_risk_mode()

        # Create trade record
        trade = Trade(
            signal_id=signal.id,
            asset_id=asset.id,
            action=TradeAction.buy,
            quantity=decision.quantity,
            entry_price=current_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            status=TradeStatus.open,
            trade_type=TradeType.intraday if is_intraday else TradeType.positional,
            intraday_capital_used=decision.position_size if is_intraday else None,
            positional_capital_used=decision.position_size if not is_intraday else None,
        )
        db.add(trade)

        # Log transaction
        db.add(WalletTransaction(
            wallet_id=wallet.id,
            type=TransactionType.trade_open,
            amount=-decision.position_size,
            balance_after=wallet.cash_balance,
            description=f"BUY {decision.quantity} {asset_symbol} @ ₹{current_price}",
        ))

        await db.flush()
        logger.info(f"Trade opened: {asset_symbol} qty={decision.quantity} @ ₹{current_price}")

        return {
            "approved":      True,
            "trade_id":      str(trade.id),
            "symbol":        asset_symbol,
            "quantity":      decision.quantity,
            "entry_price":   current_price,
            "position_size": decision.position_size,
            "stop_loss":     decision.stop_loss,
            "take_profit":   decision.take_profit,
            "cash_remaining":round(wallet.cash_balance, 2),
        }

    async def close_trade(
        self,
        db:       AsyncSession,
        trade_id: str,
        reason:   str = "manual",
    ) -> dict:
        """Close an open trade, realise P&L, credit wallet."""
        wallet = await self.get_or_create(db)

        trade_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.id == trade_id)
        )
        row = trade_result.one_or_none()
        if row is None:
            return {"error": f"Trade {trade_id} not found"}

        trade, asset = row
        if trade.status != TradeStatus.open:
            return {"error": f"Trade {trade_id} is already {trade.status.value}"}

        exit_price = fetch_latest_price(asset.symbol) or trade.entry_price
        pnl        = (exit_price - trade.entry_price) * trade.quantity
        proceeds   = exit_price * trade.quantity

        # Update trade
        trade.exit_price   = exit_price
        trade.exit_time    = datetime.now(timezone.utc)
        trade.status       = TradeStatus.closed
        trade.realized_pnl = round(pnl, 2)
        trade.notes        = reason

        # Update wallet
        wallet.cash_balance     += proceeds
        wallet.invested_balance  = max(0.0, wallet.invested_balance - trade.capital_used)
        wallet.realized_pnl     += pnl
        if wallet.total_equity > wallet.peak_equity:
            wallet.peak_equity = wallet.total_equity
        wallet.risk_mode = wallet.compute_risk_mode()

        db.add(WalletTransaction(
            wallet_id=wallet.id,
            type=TransactionType.trade_close,
            amount=proceeds,
            balance_after=wallet.cash_balance,
            description=f"SELL {trade.quantity} {asset.symbol} @ ₹{exit_price} (P&L: ₹{pnl:+.2f})",
        ))

        await db.flush()
        logger.info(f"Trade closed: {asset.symbol} pnl=₹{pnl:+.2f}")

        return {
            "trade_id":    str(trade.id),
            "symbol":      asset.symbol,
            "exit_price":  exit_price,
            "realized_pnl":round(pnl, 2),
            "pnl_pct":     round((exit_price - trade.entry_price) / trade.entry_price * 100, 2),
            "total_equity":round(wallet.total_equity, 2),
            "risk_mode":   wallet.risk_mode.value,
        }

    # ------------------------------------------------------------------ #
    # Monthly top-up
    # ------------------------------------------------------------------ #

    async def apply_monthly_topup(self, db: AsyncSession) -> dict:
        """Add monthly top-up to wallet. Call from Celery beat on month start."""
        wallet = await self.get_or_create(db)
        amount = wallet.monthly_topup
        wallet.cash_balance += amount

        db.add(WalletTransaction(
            wallet_id=wallet.id,
            type=TransactionType.topup,
            amount=amount,
            balance_after=wallet.cash_balance,
            description=f"Monthly top-up: ₹{amount}",
        ))
        await db.flush()
        logger.info(f"Monthly top-up applied: ₹{amount}")
        return {"topup_applied": amount, "new_cash_balance": round(wallet.cash_balance, 2)}

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _daily_realised_loss(self, db: AsyncSession) -> float:
        """Sum of negative realised P&L from trades closed today."""
        today = date.today()
        result = await db.execute(
            select(func.coalesce(func.sum(Trade.realized_pnl), 0.0))
            .where(
                Trade.status == TradeStatus.closed,
                Trade.realized_pnl < 0,
                func.date(Trade.exit_time) == today,
            )
        )
        loss = result.scalar() or 0.0
        return abs(float(loss))


_service: Optional[WalletService] = None

def get_wallet_service() -> WalletService:
    global _service
    if _service is None:
        _service = WalletService()
    return _service
