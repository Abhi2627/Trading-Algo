# infra/backtesting/transaction_costs.py
# Models the real cost of executing a trade on NSE via Zerodha.
# These costs are what separate a profitable backtest from a profitable live strategy.
# Every backtest MUST deduct these — ignoring costs is the #1 rookie mistake.

from dataclasses import dataclass


@dataclass
class TradeCost:
    brokerage:       float   # flat fee per order
    stt:             float   # Securities Transaction Tax
    exchange_charge: float   # NSE exchange fee
    sebi_charge:     float   # SEBI regulatory fee
    gst:             float   # GST on brokerage + exchange charge
    stamp_duty:      float   # state stamp duty (buy side only)
    total:           float   # sum of all above


class NSETransactionCosts:
    """
    Zerodha cost model for NSE equity delivery trades.
    All rates as of 2025. Update if rates change.

    Zerodha charges:
    - Brokerage:       ₹0 for delivery (ZERO brokerage)
    - STT:             0.1% on buy + sell (delivery)
    - Exchange charge: 0.00297% of turnover
    - SEBI charge:     ₹10 per crore (0.000001 of turnover)
    - GST:             18% on (brokerage + exchange charge)
    - Stamp duty:      0.015% on buy side only

    For intraday (MIS):
    - Brokerage:       0.03% or ₹20 per order, whichever is lower
    - STT:             0.025% on sell side only
    - Rest same as delivery
    """

    # Delivery rates
    BROKERAGE_DELIVERY   = 0.0          # zero brokerage
    STT_DELIVERY         = 0.001        # 0.1% on buy + sell
    EXCHANGE_CHARGE      = 0.0000297    # 0.00297%
    SEBI_CHARGE          = 0.000001     # ₹10 per crore = 0.000001
    GST_RATE             = 0.18         # 18% on brokerage + exchange
    STAMP_DUTY_BUY       = 0.00015      # 0.015% on buy only

    # Intraday rates
    BROKERAGE_INTRADAY_PCT = 0.0003     # 0.03%
    BROKERAGE_INTRADAY_MAX = 20.0       # ₹20 cap per order
    STT_INTRADAY           = 0.00025    # 0.025% on sell only

    # Slippage assumptions (market impact)
    # Large-cap NSE stocks (Nifty 50): 0.05% per side
    # Mid-cap NSE stocks: 0.10% per side
    # Crypto: 0.15% per side
    SLIPPAGE_LARGECAP = 0.0005
    SLIPPAGE_MIDCAP   = 0.001
    SLIPPAGE_CRYPTO   = 0.0015

    def compute(
        self,
        trade_value: float,          # total rupee value of the trade
        is_buy:      bool  = True,
        is_intraday: bool  = False,
        is_largecap: bool  = True,   # affects slippage
    ) -> TradeCost:
        """Compute all-in cost for a single trade leg."""

        if is_intraday:
            raw_brokerage = min(
                trade_value * self.BROKERAGE_INTRADAY_PCT,
                self.BROKERAGE_INTRADAY_MAX,
            )
            stt = trade_value * self.STT_INTRADAY if not is_buy else 0.0
        else:
            raw_brokerage = trade_value * self.BROKERAGE_DELIVERY
            stt = trade_value * self.STT_DELIVERY

        exchange_charge = trade_value * self.EXCHANGE_CHARGE
        sebi_charge     = trade_value * self.SEBI_CHARGE
        gst             = (raw_brokerage + exchange_charge) * self.GST_RATE
        stamp_duty      = (trade_value * self.STAMP_DUTY_BUY) if is_buy else 0.0

        slippage_rate = (
            self.SLIPPAGE_LARGECAP if is_largecap
            else self.SLIPPAGE_MIDCAP
        )
        # Slippage is not a fee but a price impact cost
        # We model it as an additional cost on the trade value
        slippage_cost = trade_value * slippage_rate

        total = (
            raw_brokerage + stt + exchange_charge +
            sebi_charge + gst + stamp_duty + slippage_cost
        )

        return TradeCost(
            brokerage=round(raw_brokerage, 4),
            stt=round(stt, 4),
            exchange_charge=round(exchange_charge, 4),
            sebi_charge=round(sebi_charge, 4),
            gst=round(gst, 4),
            stamp_duty=round(stamp_duty, 4),
            total=round(total, 4),
        )

    def round_trip_cost_pct(self, is_largecap: bool = True) -> float:
        """
        Approximate total cost as a % of trade value for a full round trip
        (buy + sell). Use this for quick break-even analysis.

        For a trade to be profitable, the price move must exceed this.
        """
        # Approximate on a ₹100 trade
        buy  = self.compute(100.0, is_buy=True,  is_largecap=is_largecap)
        sell = self.compute(100.0, is_buy=False, is_largecap=is_largecap)
        return (buy.total + sell.total) / 100.0


def get_cost_model() -> NSETransactionCosts:
    return NSETransactionCosts()


if __name__ == "__main__":
    # Quick sanity check
    costs = NSETransactionCosts()
    print("=== NSE Transaction Cost Model ===")
    print(f"Large-cap round trip cost: {costs.round_trip_cost_pct(True):.4%}")
    print(f"Mid-cap round trip cost:   {costs.round_trip_cost_pct(False):.4%}")
    print()

    # Example: ₹10,000 buy of a large-cap stock
    cost = costs.compute(10000, is_buy=True, is_largecap=True)
    print(f"₹10,000 buy trade costs:")
    print(f"  Brokerage:       ₹{cost.brokerage:.2f}")
    print(f"  STT:             ₹{cost.stt:.2f}")
    print(f"  Exchange charge: ₹{cost.exchange_charge:.2f}")
    print(f"  SEBI charge:     ₹{cost.sebi_charge:.2f}")
    print(f"  GST:             ₹{cost.gst:.2f}")
    print(f"  Stamp duty:      ₹{cost.stamp_duty:.2f}")
    print(f"  Total:           ₹{cost.total:.2f} ({cost.total/10000:.4%})")
