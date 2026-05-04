# services/wallet/emergency_service.py
# Emergency liquidation service.
# When user needs money urgently, this service:
#   1. Calculates how much cash is needed beyond current balance
#   2. Ranks holdings by lowest potential (sell worst performers first)
#   3. Sells minimum stocks needed to cover the required amount
#   4. Leaves best-performing positions intact
#   5. Returns cash to wallet
#   6. Transfers to linked bank account if configured
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.models import (
    Trade, Asset, PaperWallet, WalletTransaction,
    TradeStatus, TransactionType, RiskMode,
)
from services.market_data.fetcher import fetch_latest_price
from services.wallet.charges import compute_charges, compute_round_trip

logger = logging.getLogger(__name__)


class EmergencyService:

    async def emergency_liquidate(
        self,
        db:              AsyncSession,
        amount_needed:   float,
        reason:          str = "emergency",
    ) -> dict:
        """
        Intelligently liquidate minimum stocks to raise the required amount.

        Args:
            amount_needed: total cash needed (including what's already in wallet)
            reason:        reason for emergency (stored in transaction log)

        Returns:
            dict with:
              - cash_before, cash_after
              - sold: list of stocks sold with prices and net proceeds
              - kept: list of stocks kept with reason
              - shortfall: if couldn't raise full amount (0 = fully covered)
              - transfer_ready: amount available for bank transfer
        """
        # Get wallet
        wallet_result = await db.execute(select(PaperWallet).limit(1))
        wallet = wallet_result.scalar_one_or_none()
        if wallet is None:
            return {"error": "Wallet not found"}

        cash_before    = round(wallet.cash_balance, 2)
        cash_needed    = round(amount_needed - cash_before, 2)

        if cash_needed <= 0:
            # Already have enough cash
            return {
                "cash_before":     cash_before,
                "cash_after":      cash_before,
                "amount_needed":   amount_needed,
                "already_covered": True,
                "sold":            [],
                "kept":            [],
                "shortfall":       0.0,
                "transfer_ready":  round(min(amount_needed, cash_before), 2),
                "message":         f"Wallet already has ₹{cash_before:.0f}. No stocks need to be sold."
            }

        # Get all open positions
        positions_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        positions = positions_result.all()

        if not positions:
            return {
                "error":         "No open positions to liquidate",
                "cash_available": cash_before,
                "amount_needed":  amount_needed,
                "shortfall":      round(cash_needed, 2),
                "message":        (
                    f"Need ₹{amount_needed:.0f} but only have ₹{cash_before:.0f} cash "
                    f"and no open positions. Add funds via /wallet/topup."
                )
            }

        # Score and rank each position — sell lowest potential first
        scored = []
        for trade, asset in positions:
            price = fetch_latest_price(asset.symbol)
            if price is None:
                price = trade.entry_price

            pnl_pct      = (price - trade.entry_price) / trade.entry_price * 100
            current_value = price * trade.quantity
            charges       = compute_charges(trade.quantity, price, is_buy=False)
            net_proceeds  = round(current_value - charges.total, 2)

            # Sell score: lower = sell first
            # Factors:
            #   - Losing positions (pnl_pct < 0) score lower → sell first
            #   - Near stop-loss → sell first (would be auto-sold soon anyway)
            #   - Low current value → sell first (frees less capital, less waste)
            near_stop     = price <= trade.stop_loss * 1.03  # within 3% of stop
            sell_score    = (
                pnl_pct * 0.5           # negative P&L = lower score = sell sooner
                + (0 if near_stop else 20)  # near stop = sell sooner
                + (current_value / 1000)    # higher value positions = keep longer
            )

            scored.append({
                "trade":         trade,
                "asset":         asset,
                "current_price": price,
                "pnl_pct":       round(pnl_pct, 2),
                "current_value": round(current_value, 2),
                "net_proceeds":  net_proceeds,
                "sell_score":    sell_score,
                "near_stop":     near_stop,
                "charges":       round(charges.total, 2),
            })

        # Sort: lowest score first (worst performers sell first)
        scored.sort(key=lambda x: x["sell_score"])

        # Sell minimum needed to cover cash_needed
        sold         = []
        kept         = []
        cash_raised  = 0.0

        for item in scored:
            if cash_raised >= cash_needed:
                # Already raised enough — keep this position
                kept.append({
                    "symbol":        item["asset"].symbol,
                    "quantity":      item["trade"].quantity,
                    "entry_price":   item["trade"].entry_price,
                    "current_price": item["current_price"],
                    "pnl_pct":       item["pnl_pct"],
                    "reason":        "kept — sufficient cash raised from other positions"
                })
                continue

            # Sell this position
            trade  = item["trade"]
            asset  = item["asset"]
            price  = item["current_price"]

            trade.exit_price   = price
            trade.exit_time    = datetime.now(timezone.utc)
            trade.status       = TradeStatus.closed
            trade.realized_pnl = round((price - trade.entry_price) * trade.quantity - item["charges"], 2)
            trade.notes        = f"emergency_liquidation: {reason}"

            # Update wallet
            invested_release    = trade.positional_capital_used or trade.intraday_capital_used or 0.0
            wallet.cash_balance = round(wallet.cash_balance + item["net_proceeds"], 2)
            wallet.invested_balance = round(
                max(0.0, wallet.invested_balance - invested_release), 2
            )
            wallet.realized_pnl = round(wallet.realized_pnl + trade.realized_pnl, 2)

            # Transaction log
            db.add(WalletTransaction(
                wallet_id     = wallet.id,
                type          = TransactionType.trade_close,
                amount        = item["net_proceeds"],
                balance_after = wallet.cash_balance,
                description   = (
                    f"EMERGENCY SELL {trade.quantity} {asset.symbol} "
                    f"@ ₹{price:.2f} | P&L ₹{trade.realized_pnl:+.2f} "
                    f"| Charges ₹{item['charges']:.2f} | Reason: {reason}"
                ),
            ))

            cash_raised += item["net_proceeds"]
            sold.append({
                "symbol":       asset.symbol,
                "quantity":     trade.quantity,
                "entry_price":  trade.entry_price,
                "exit_price":   price,
                "pnl_pct":      item["pnl_pct"],
                "gross":        round(price * trade.quantity, 2),
                "charges":      item["charges"],
                "net_proceeds": item["net_proceeds"],
                "reason":       (
                    "near stop-loss (would have been auto-sold soon)"
                    if item["near_stop"]
                    else f"underperforming ({item['pnl_pct']:+.1f}% return)"
                    if item["pnl_pct"] < 0
                    else f"lowest potential ({item['pnl_pct']:+.1f}% return)"
                )
            })

        # Recalibrate wallet risk mode
        wallet.risk_mode = wallet.compute_risk_mode()
        if wallet.cash_balance < 500:
            wallet.risk_mode = RiskMode.conservative

        await db.flush()

        cash_after   = round(wallet.cash_balance, 2)
        shortfall    = round(max(0.0, amount_needed - cash_after), 2)
        transfer_amt = round(min(amount_needed, cash_after), 2)

        logger.warning(
            f"Emergency liquidation: needed ₹{amount_needed:.0f} | "
            f"raised ₹{cash_raised:.0f} from {len(sold)} positions | "
            f"shortfall ₹{shortfall:.0f}"
        )

        response = {
            "cash_before":    cash_before,
            "cash_after":     cash_after,
            "amount_needed":  amount_needed,
            "cash_raised":    round(cash_raised, 2),
            "shortfall":      shortfall,
            "transfer_ready": transfer_amt,
            "sold":           sold,
            "kept":           kept,
            "positions_sold": len(sold),
            "positions_kept": len(kept),
            "message": (
                f"Sold {len(sold)} position(s), raised ₹{cash_raised:.0f}. "
                f"Wallet now has ₹{cash_after:.0f}. "
                + (f"Ready to transfer ₹{transfer_amt:.0f} to your bank account."
                   if shortfall == 0
                   else f"Could only raise ₹{cash_after:.0f} of ₹{amount_needed:.0f} needed. "
                        f"Shortfall: ₹{shortfall:.0f}")
            )
        }

        # Add bank transfer info if account is linked
        bank = await self._get_linked_bank(db)
        if bank:
            response["bank_account"] = {
                "linked":       True,
                "bank_name":    bank["bank_name"],
                "account_last4":bank["account_last4"],
                "ifsc":         bank["ifsc"],
                "transfer_note":(
                    f"In live trading: ₹{transfer_amt:.0f} would be transferred "
                    f"to {bank['bank_name']} ...{bank['account_last4']} "
                    f"within 1 business day via NEFT/IMPS."
                )
            }
        else:
            response["bank_account"] = {
                "linked":       False,
                "transfer_note":(
                    "No bank account linked. Link your account via "
                    "POST /emergency/link-bank to enable direct transfers."
                )
            }

        return response

    async def link_bank_account(
        self,
        db:           AsyncSession,
        bank_name:    str,
        account_no:   str,
        ifsc:         str,
        account_name: str,
    ) -> dict:
        """
        Store bank account details for future direct transfers.
        In paper trading: stored but no actual transfer happens.
        In live trading: used to route Zerodha/broker withdrawals.

        Account number is masked — only last 4 digits stored visibly.
        Full number stored encrypted (placeholder for now).
        """
        if len(account_no) < 8:
            return {"error": "Invalid account number"}
        if len(ifsc) != 11:
            return {"error": "Invalid IFSC code (must be 11 characters)"}

        wallet = (await db.execute(select(PaperWallet).limit(1))).scalar_one_or_none()
        if wallet is None:
            return {"error": "Wallet not found"}

        # Store in wallet notes field (extend model later for proper encryption)
        # Format: BANK|bank_name|last4|ifsc|account_name
        last4 = account_no[-4:]
        wallet.notes = f"BANK|{bank_name}|{last4}|{ifsc.upper()}|{account_name}"
        await db.flush()

        logger.info(f"Bank account linked: {bank_name} ...{last4} IFSC:{ifsc.upper()}")

        return {
            "linked":       True,
            "bank_name":    bank_name,
            "account_last4":last4,
            "ifsc":         ifsc.upper(),
            "account_name": account_name,
            "message":      (
                f"Bank account linked: {bank_name} ending ...{last4}. "
                f"In paper trading mode, no actual transfers happen. "
                f"When you switch to live trading via Zerodha, "
                f"emergency withdrawals will transfer directly to this account."
            )
        }

    async def get_liquidation_preview(
        self,
        db:            AsyncSession,
        amount_needed: float,
    ) -> dict:
        """
        Preview what would be sold WITHOUT actually selling.
        Shows exactly which stocks and how much cash would be raised.
        Use this before calling emergency_liquidate.
        """
        wallet = (await db.execute(select(PaperWallet).limit(1))).scalar_one_or_none()
        if wallet is None:
            return {"error": "Wallet not found"}

        cash_before = round(wallet.cash_balance, 2)
        cash_needed = round(amount_needed - cash_before, 2)

        positions_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        positions = positions_result.all()

        holdings_value = 0.0
        preview_items  = []

        for trade, asset in positions:
            price         = fetch_latest_price(asset.symbol) or trade.entry_price
            pnl_pct       = (price - trade.entry_price) / trade.entry_price * 100
            current_value = price * trade.quantity
            charges       = compute_charges(trade.quantity, price, is_buy=False)
            net_proceeds  = current_value - charges.total
            near_stop     = price <= trade.stop_loss * 1.03
            sell_score    = (
                pnl_pct * 0.5
                + (0 if near_stop else 20)
                + (current_value / 1000)
            )
            holdings_value += current_value
            preview_items.append({
                "symbol":       asset.symbol,
                "quantity":     trade.quantity,
                "entry_price":  trade.entry_price,
                "current_price":round(price, 2),
                "pnl_pct":      round(pnl_pct, 2),
                "net_proceeds": round(net_proceeds, 2),
                "sell_score":   sell_score,
                "would_sell":   False,  # set below
            })

        preview_items.sort(key=lambda x: x["sell_score"])

        # Mark which would be sold
        cash_raised = 0.0
        for item in preview_items:
            if cash_raised < cash_needed:
                item["would_sell"] = True
                cash_raised += item["net_proceeds"]
            else:
                item["would_sell"] = False

        return {
            "amount_needed":    amount_needed,
            "cash_in_wallet":   cash_before,
            "cash_from_stocks": round(cash_raised, 2),
            "total_available":  round(cash_before + cash_raised, 2),
            "shortfall":        round(max(0, amount_needed - cash_before - cash_raised), 2),
            "holdings_value":   round(holdings_value, 2),
            "positions":        preview_items,
            "note":             "This is a preview only. Call POST /emergency/liquidate to execute."
        }

    async def _get_linked_bank(self, db: AsyncSession) -> Optional[dict]:
        """Parse linked bank account from wallet notes."""
        wallet = (await db.execute(select(PaperWallet).limit(1))).scalar_one_or_none()
        if not wallet or not wallet.notes or not wallet.notes.startswith("BANK|"):
            return None
        try:
            _, bank_name, last4, ifsc, account_name = wallet.notes.split("|")
            return {"bank_name": bank_name, "account_last4": last4,
                    "ifsc": ifsc, "account_name": account_name}
        except Exception:
            return None


_service: Optional[EmergencyService] = None

def get_emergency_service() -> EmergencyService:
    global _service
    if _service is None:
        _service = EmergencyService()
    return _service
