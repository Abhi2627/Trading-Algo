# test/test_health.py — Phase 1 smoke tests
# Run: pytest test/test_health.py -v
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from core.config import settings


@pytest.mark.asyncio
async def test_health_no_auth():
    """Health endpoint must be publicly accessible."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "env" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_secure_health_rejected_without_key():
    """Secure endpoint must reject requests with no API key."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/secure-health")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_secure_health_rejected_with_wrong_key():
    """Secure endpoint must reject wrong API keys."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/secure-health", headers={"X-API-Key": "definitely-wrong-key"}
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_secure_health_accepted_with_correct_key():
    """Secure endpoint must accept the correct API key from .env."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/secure-health", headers={"X-API-Key": settings.API_KEY}
        )
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


def test_models_import():
    """All ORM models must import cleanly — catches circular import issues."""
    from core.models import (
        Asset, PaperWallet, WalletTransaction,
        Signal, Trade, DailyReport, PredictionOutcome,
    )
    assert Asset.__tablename__ == "asset"
    assert PaperWallet.__tablename__ == "paper_wallet"
    assert WalletTransaction.__tablename__ == "wallet_transaction"
    assert Signal.__tablename__ == "signal"
    assert Trade.__tablename__ == "trade"
    assert DailyReport.__tablename__ == "daily_report"
    assert PredictionOutcome.__tablename__ == "prediction_outcome"


def test_wallet_total_equity():
    """total_equity must sum cash + invested + unrealized correctly."""
    from core.models import PaperWallet
    wallet = PaperWallet(
        cash_balance=6000.0,
        invested_balance=3000.0,
        unrealized_pnl=500.0,
        peak_equity=10000.0,
    )
    assert wallet.total_equity == pytest.approx(9500.0)


def test_wallet_drawdown_normal():
    """7% drawdown must resolve to normal risk mode."""
    from core.models import PaperWallet, RiskMode
    wallet = PaperWallet(
        cash_balance=7000.0,
        invested_balance=2000.0,
        unrealized_pnl=300.0,   # total_equity = 9300
        peak_equity=10000.0,    # drawdown = 7%
    )
    assert wallet.drawdown_pct == pytest.approx(0.07)
    assert wallet.compute_risk_mode() == RiskMode.normal


def test_wallet_drawdown_conservative():
    """13% drawdown must resolve to conservative risk mode."""
    from core.models import PaperWallet, RiskMode
    wallet = PaperWallet(
        cash_balance=5000.0,
        invested_balance=3500.0,
        unrealized_pnl=200.0,   # total_equity = 8700
        peak_equity=10000.0,    # drawdown = 13%
    )
    assert wallet.compute_risk_mode() == RiskMode.conservative


def test_wallet_drawdown_halted():
    """22% drawdown must resolve to halted risk mode."""
    from core.models import PaperWallet, RiskMode
    wallet = PaperWallet(
        cash_balance=4000.0,
        invested_balance=3600.0,
        unrealized_pnl=200.0,   # total_equity = 7800
        peak_equity=10000.0,    # drawdown = 22%
    )
    assert wallet.compute_risk_mode() == RiskMode.halted


def test_wallet_allocations():
    """Intraday must be 25%, positional 75% of total equity."""
    from core.models import PaperWallet
    wallet = PaperWallet(
        cash_balance=8000.0,
        invested_balance=2000.0,
        unrealized_pnl=0.0,     # total_equity = 10000
        peak_equity=10000.0,
    )
    assert wallet.intraday_allocation == pytest.approx(2500.0)
    assert wallet.positional_allocation == pytest.approx(7500.0)
