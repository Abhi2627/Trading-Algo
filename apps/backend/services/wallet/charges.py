# services/wallet/charges.py
# NSE/BSE transaction charges for Indian equity trading.
# All rates as per SEBI/NSE/BSE circulars effective 2025.
#
# Charge breakdown per trade leg:
#   Brokerage     Flat ₹20 per order (Zerodha/Groww style)
#   STT           Securities Transaction Tax
#   Exchange fee  NSE transaction charge
#   SEBI fee      SEBI turnover fee
#   Stamp duty    State stamp duty (BUY only)
#   GST           18% on (brokerage + exchange fee + SEBI fee)
#
# These charges are deducted from realized P&L so paper trading
# reflects exactly what you would net in real trading.
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rates (NSE Equity Delivery, 2025)
# ---------------------------------------------------------------------------
BROKERAGE_PER_ORDER  = 20.0       # flat ₹20 per order
STT_DELIVERY_BUY     = 0.001      # 0.1%
STT_DELIVERY_SELL    = 0.001      # 0.1%
NSE_EXCHANGE_FEE     = 0.0000297  # 0.00297% (₹2.97 per lakh)
SEBI_FEE             = 0.000001   # ₹10 per crore
STAMP_DUTY_BUY       = 0.00015    # 0.015% (BUY only, max ₹1500)
STAMP_DUTY_MAX       = 1500.0
GST_RATE             = 0.18       # 18% on brokerage+exchange+sebi


@dataclass
class TradeCharges:
    brokerage:    float
    stt:          float
    exchange_fee: float
    sebi_fee:     float
    stamp_duty:   float
    gst:          float
    total:        float
    turnover:     float

    def as_dict(self) -> dict:
        return {
            "brokerage":    round(self.brokerage, 2),
            "stt":          round(self.stt, 4),
            "exchange_fee": round(self.exchange_fee, 4),
            "sebi_fee":     round(self.sebi_fee, 4),
            "stamp_duty":   round(self.stamp_duty, 4),
            "gst":          round(self.gst, 4),
            "total":        round(self.total, 2),
            "turnover":     round(self.turnover, 2),
        }


def compute_charges(quantity: int, price: float, is_buy: bool) -> TradeCharges:
    """
    Compute all NSE equity delivery charges for one trade leg.
    Args:
        quantity: number of shares
        price:    price per share in INR
        is_buy:   True for BUY, False for SELL
    """
    turnover     = quantity * price
    brokerage    = BROKERAGE_PER_ORDER
    stt          = turnover * (STT_DELIVERY_BUY if is_buy else STT_DELIVERY_SELL)
    exchange_fee = turnover * NSE_EXCHANGE_FEE
    sebi_fee     = turnover * SEBI_FEE
    stamp_duty   = min(turnover * STAMP_DUTY_BUY, STAMP_DUTY_MAX) if is_buy else 0.0
    gst          = (brokerage + exchange_fee + sebi_fee) * GST_RATE
    total        = brokerage + stt + exchange_fee + sebi_fee + stamp_duty + gst

    return TradeCharges(
        brokerage=brokerage,
        stt=round(stt, 4),
        exchange_fee=round(exchange_fee, 6),
        sebi_fee=round(sebi_fee, 6),
        stamp_duty=round(stamp_duty, 6),
        gst=round(gst, 4),
        total=round(total, 4),
        turnover=round(turnover, 2),
    )


def compute_round_trip(quantity: int, buy_price: float, sell_price: float) -> dict:
    """
    Total charges for a complete trade (buy + sell).
    Returns gross P&L, total charges, net P&L, and breakeven price.
    """
    buy_c  = compute_charges(quantity, buy_price,  is_buy=True)
    sell_c = compute_charges(quantity, sell_price, is_buy=False)

    total_charges = buy_c.total + sell_c.total
    gross_pnl     = (sell_price - buy_price) * quantity
    net_pnl       = gross_pnl - total_charges
    breakeven     = buy_price + (total_charges / quantity)

    return {
        "gross_pnl":      round(gross_pnl, 2),
        "total_charges":  round(total_charges, 2),
        "net_pnl":        round(net_pnl, 2),
        "breakeven_price":round(breakeven, 2),
        "charge_pct":     round(total_charges / (buy_price * quantity) * 100, 4),
        "buy_charges":    buy_c.as_dict(),
        "sell_charges":   sell_c.as_dict(),
    }


def charges_preview(quantity: int, entry: float, stop_loss: float, take_profit: float) -> dict:
    """
    Show projected net returns at TP and SL scenarios.
    Shown in the Open Trade UI so user knows real net returns.
    """
    tp = compute_round_trip(quantity, entry, take_profit)
    sl = compute_round_trip(quantity, entry, stop_loss)
    buy_only = compute_charges(quantity, entry, is_buy=True)

    return {
        "buy_charges_now": round(buy_only.total, 2),
        "take_profit": {
            "gross_pnl":     tp["gross_pnl"],
            "charges":       tp["total_charges"],
            "net_pnl":       tp["net_pnl"],
            "breakeven":     tp["breakeven_price"],
        },
        "stop_loss": {
            "gross_pnl":     sl["gross_pnl"],
            "charges":       sl["total_charges"],
            "net_pnl":       sl["net_pnl"],
        },
    }
