# core/models.py — all SQLAlchemy ORM models
# Base is imported from core.database — never redefine it here.
import uuid
import enum
import datetime
from typing import List, Optional, Any

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String, Float, Integer, Boolean, DateTime, Date,
    JSON, Text, Enum as SAEnum, ForeignKey, Index
)
from core.database import Base


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _now() -> datetime.datetime:
    """Timezone-aware UTC now — replaces deprecated datetime.utcnow()."""
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class AssetType(enum.Enum):
    equity = "equity"
    mutual_fund = "mutual_fund"
    crypto = "crypto"
    forex = "forex"


class RiskMode(enum.Enum):
    normal = "normal"
    conservative = "conservative"
    halted = "halted"


class TransactionType(enum.Enum):
    topup = "topup"
    trade_open = "trade_open"
    trade_close = "trade_close"
    adjustment = "adjustment"


class SignalAction(enum.Enum):
    buy = "buy"
    sell = "sell"
    hold = "hold"


class TradeAction(enum.Enum):
    buy = "buy"
    sell = "sell"


class TradeStatus(enum.Enum):
    open = "open"
    closed = "closed"
    stopped = "stopped"
    expired = "expired"


class TradeType(enum.Enum):
    intraday = "intraday"
    positional = "positional"


class ReportType(enum.Enum):
    morning = "morning"
    evening = "evening"


class OutcomeResult(enum.Enum):
    correct = "correct"
    wrong = "wrong"
    pending = "pending"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String, index=True, nullable=False)  # e.g. "NSE:RELIANCE"
    name: Mapped[str] = mapped_column(String, nullable=False)
    exchange: Mapped[str] = mapped_column(String)                             # NSE / BSE / CRYPTO / FOREX
    asset_type: Mapped[AssetType] = mapped_column(SAEnum(AssetType))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    signals: Mapped[List["Signal"]] = relationship("Signal", back_populates="asset", cascade="all, delete-orphan")
    trades: Mapped[List["Trade"]] = relationship("Trade", back_populates="asset", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Asset symbol={self.symbol!r} type={self.asset_type.value}>"


class PaperWallet(Base):
    __tablename__ = "paper_wallet"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cash_balance: Mapped[float] = mapped_column(Float, default=2000.0)
    invested_balance: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float, default=2000.0)
    monthly_topup: Mapped[float] = mapped_column(Float, default=1000.0)
    risk_mode: Mapped[RiskMode] = mapped_column(SAEnum(RiskMode), default=RiskMode.normal)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)  # stores bank account info
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    transactions: Mapped[List["WalletTransaction"]] = relationship(
        "WalletTransaction", back_populates="wallet", cascade="all, delete-orphan"
    )

    # -------------------------------------------------------------------
    # Computed properties — the core compounding logic lives here
    # -------------------------------------------------------------------
    @property
    def total_equity(self) -> float:
        """
        The single number that compounds over time.
        cash + what's deployed in positions + floating P&L on open positions.
        All position sizing uses this, not the initial deposit.
        """
        return self.cash_balance + self.invested_balance + self.unrealized_pnl

    @property
    def drawdown_pct(self) -> float:
        """
        Current drawdown from peak equity as a fraction (0.0 to 1.0).
        0.12 means 12% below peak — triggers conservative mode.
        0.20 means 20% below peak — triggers halted mode.
        """
        if self.peak_equity == 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.total_equity) / self.peak_equity)

    @property
    def intraday_allocation(self) -> float:
        """25% of total equity reserved for intraday trades."""
        return self.total_equity * 0.25

    @property
    def positional_allocation(self) -> float:
        """75% of total equity reserved for positional trades."""
        return self.total_equity * 0.75

    def compute_risk_mode(self) -> RiskMode:
        """
        Derives the correct risk mode from current drawdown.
        Call this after any trade close and update self.risk_mode.
        """
        dd = self.drawdown_pct
        if dd >= 0.20:
            return RiskMode.halted
        if dd >= 0.12:
            return RiskMode.conservative
        return RiskMode.normal

    def __repr__(self) -> str:
        return (
            f"<PaperWallet equity=₹{self.total_equity:.2f} "
            f"cash=₹{self.cash_balance:.2f} mode={self.risk_mode.value}>"
        )


class WalletTransaction(Base):
    __tablename__ = "wallet_transaction"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper_wallet.id"))
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType))
    amount: Mapped[float] = mapped_column(Float)          # positive = credit, negative = debit
    balance_after: Mapped[float] = mapped_column(Float)   # cash_balance after this transaction
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    wallet: Mapped["PaperWallet"] = relationship("PaperWallet", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<WalletTransaction type={self.type.value} amount={self.amount:+.2f}>"


class Signal(Base):
    __tablename__ = "signal"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id"))
    action: Mapped[SignalAction] = mapped_column(SAEnum(SignalAction))
    confidence: Mapped[float] = mapped_column(Float)           # 0.0 – 1.0
    rl_score: Mapped[float] = mapped_column(Float)             # RL agent output (-1 to +1)
    transformer_score: Mapped[float] = mapped_column(Float)    # forecaster delta %
    sentiment_score: Mapped[float] = mapped_column(Float)      # NLP score (-1 to +1)
    ensemble_score: Mapped[float] = mapped_column(Float)       # final weighted blend
    market_regime: Mapped[str] = mapped_column(String)         # trending / ranging / volatile
    technical_indicators: Mapped[Any] = mapped_column(JSON)    # {rsi, macd, atr, ...}
    sentiment_sources: Mapped[Any] = mapped_column(JSON)       # [{headline, score, source}, ...]
    is_intraday: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="signals")
    trades: Mapped[List["Trade"]] = relationship(
        "Trade", back_populates="signal", cascade="all, delete-orphan"
    )
    prediction_outcomes: Mapped[List["PredictionOutcome"]] = relationship(
        "PredictionOutcome", back_populates="signal", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_signal_asset_created", "asset_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Signal {self.action.value.upper()} "
            f"confidence={self.confidence:.0%} regime={self.market_regime}>"
        )


class Trade(Base):
    __tablename__ = "trade"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signal.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id"))
    action: Mapped[TradeAction] = mapped_column(SAEnum(TradeAction))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    status: Mapped[TradeStatus] = mapped_column(SAEnum(TradeStatus), default=TradeStatus.open, index=True)
    trade_type: Mapped[TradeType] = mapped_column(SAEnum(TradeType))
    entry_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    exit_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    intraday_capital_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    positional_capital_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    signal: Mapped["Signal"] = relationship("Signal", back_populates="trades")
    asset: Mapped["Asset"] = relationship("Asset", back_populates="trades")

    __table_args__ = (
        Index("ix_trade_status_type", "status", "trade_type"),
    )

    @property
    def unrealized_pnl(self) -> Optional[float]:
        """Only meaningful for open trades. Requires current_price injected externally."""
        return None  # computed in wallet service with live price

    @property
    def capital_used(self) -> float:
        """Total capital locked in this trade."""
        return (self.intraday_capital_used or 0.0) + (self.positional_capital_used or 0.0)

    def __repr__(self) -> str:
        return (
            f"<Trade {self.action.value.upper()} {self.quantity} "
            f"@ ₹{self.entry_price} status={self.status.value}>"
        )


class DailyReport(Base):
    __tablename__ = "daily_report"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    report_type: Mapped[ReportType] = mapped_column(SAEnum(ReportType))
    content: Mapped[Any] = mapped_column(JSON)                             # structured report data
    prediction_accuracy_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # plain-English report
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    prediction_outcomes: Mapped[List["PredictionOutcome"]] = relationship(
        "PredictionOutcome", back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_report_date_type", "report_date", "report_type"),
    )

    def __repr__(self) -> str:
        return f"<DailyReport {self.report_date} {self.report_type.value}>"


class SignalOutcome(Base):
    """
    Tracks every signal that led to an auto-executed trade.
    Populated at trade-open time; updated at trade-close time.
    Provides the ground truth for ML model retraining and strategy eval.

    Separate from PredictionOutcome (which is report-centric).
    This is trade-centric: one row per trade, self-contained.
    """
    __tablename__ = "signal_outcome"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signal.id"), index=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trade.id"), index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)         # denormalized for fast queries
    signal_action: Mapped[str] = mapped_column(String)              # buy / sell
    signal_confidence: Mapped[float] = mapped_column(Float)         # at time of signal
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # stop_loss / take_profit / time_exit / trailing_stop
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)      # (exit - entry) / entry
    days_held: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[OutcomeResult] = mapped_column(
        SAEnum(OutcomeResult), default=OutcomeResult.pending, index=True
    )  # correct = profitable close, wrong = stop-loss hit, pending = still open
    ensemble_score: Mapped[float] = mapped_column(Float)            # copy from signal for retraining
    market_regime: Mapped[str] = mapped_column(String)              # copy from signal
    opened_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_signal_outcome_symbol_opened", "symbol", "opened_at"),
        Index("ix_signal_outcome_outcome", "outcome"),
    )

    def __repr__(self) -> str:
        return (
            f"<SignalOutcome {self.symbol} {self.signal_action.upper()} "
            f"outcome={self.outcome.value} pnl={self.pnl_pct:+.2%}>"
            if self.pnl_pct is not None
            else f"<SignalOutcome {self.symbol} {self.signal_action.upper()} outcome={self.outcome.value}>"
        )


class PredictionOutcome(Base):
    __tablename__ = "prediction_outcome"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signal.id"))
    report_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("daily_report.id"), nullable=True)
    predicted_direction: Mapped[str] = mapped_column(String)               # up / down / sideways
    predicted_delta_pct: Mapped[float] = mapped_column(Float)              # e.g. +1.8
    actual_delta_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # filled at close
    outcome: Mapped[OutcomeResult] = mapped_column(SAEnum(OutcomeResult), default=OutcomeResult.pending)
    root_cause: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # classified by evening job
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    signal: Mapped["Signal"] = relationship("Signal", back_populates="prediction_outcomes")
    report: Mapped["DailyReport"] = relationship("DailyReport", back_populates="prediction_outcomes")

    def __repr__(self) -> str:
        return (
            f"<PredictionOutcome {self.outcome.value} "
            f"predicted={self.predicted_direction} Δ{self.predicted_delta_pct:+.1f}%>"
        )
