import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  TrendingUp, TrendingDown, AlertCircle, AlertTriangle, Clock,
  ChevronRight
} from 'lucide-react';
import { getWalletSummary, getTopPicks, getMarketStatus, TopPick } from '../lib/api';
import { queryKeys } from '../lib/queryKeys';
import SignalBadge from '../components/SignalBadge';
import LoadingSpinner from '../components/LoadingSpinner';

const fmt = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);

const fmtExact = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

const Dashboard: React.FC = () => {
  const navigate = useNavigate();

  const { 
    data: wallet, 
    isLoading: isWalletLoading, 
    isError: isWalletError,
    refetch: refetchWallet,
  } = useQuery({
    queryKey: queryKeys.wallet,
    queryFn: getWalletSummary,
    refetchInterval: 15000,
    placeholderData: (prev) => prev,
  });

  const { data: topPicksData, isLoading: isSignalsLoading, refetch: refetchSignals } = useQuery<TopPick[]>({
    queryKey: queryKeys.topPicks,
    queryFn: async () => {
      const res = await getTopPicks(10);
      const seen = new Set<string>();
      return res.picks.filter((pick: TopPick) => {
        const stockName = pick.symbol.split(':').pop() ?? pick.symbol;
        if (seen.has(stockName)) return false;
        seen.add(stockName);
        return true;
      }).slice(0, 5);
    },
    refetchInterval: 60000,
    placeholderData: (prev) => prev,
  });

  const { data: marketStatus, refetch: refetchMarket } = useQuery({
    queryKey: ['market-status'],
    queryFn: getMarketStatus,
    refetchInterval: 60 * 1000,
    placeholderData: (prev) => prev,
  });

  const refetchAll = () => {
    refetchWallet();
    refetchSignals();
    refetchMarket();
  };

  if (isWalletLoading || isSignalsLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (isWalletError) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center gap-4">
        <AlertCircle size={48} className="text-red" />
        <h2 className="text-xl font-bold">Failed to fetch data</h2>
        <p className="text-text-secondary text-sm">Make sure the backend is running</p>
        <button
          onClick={refetchAll}
          className="px-6 py-2.5 bg-accent text-background font-bold rounded-xl hover:bg-accent/90 transition-all"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Low Balance Alert */}
      {wallet?.alert && (
        <div className={`border rounded-xl px-4 py-3 flex items-start gap-3 ${
          wallet.alert.severity === 'critical'
            ? 'bg-red/10 border-red/30'
            : 'bg-amber/10 border-amber/30'
        }`}>
          <AlertTriangle size={16} className={wallet.alert.severity === 'critical' ? 'text-red shrink-0 mt-0.5' : 'text-amber shrink-0 mt-0.5'} />
          <div className="flex-1">
            <span className={`font-bold text-sm ${
              wallet.alert.severity === 'critical' ? 'text-red' : 'text-amber'
            }`}>
              {wallet.alert.severity === 'critical' ? 'Trading Stopped — ' : 'Low Balance — '}
            </span>
            <span className="text-sm text-text-muted">{wallet.alert.message}</span>
          </div>
          <button
            onClick={() => navigate('/portfolio')}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg shrink-0 ${
              wallet.alert.severity === 'critical'
                ? 'bg-red/20 text-red hover:bg-red/30'
                : 'bg-amber/20 text-amber hover:bg-amber/30'
            } transition-all`}
          >
            Add Funds
          </button>
        </div>
      )}
      {marketStatus && !marketStatus.is_open && (
        <div className="bg-amber/10 border border-amber/30 rounded-xl px-4 py-3 flex items-center gap-3">
          <AlertTriangle size={16} className="text-amber shrink-0" />
          <div className="text-sm flex-1">
            <span className="font-bold text-amber">Market Closed</span>
            <span className="text-text-muted ml-2">{marketStatus.reason}</span>
            {marketStatus.next_open && (
              <span className="text-text-muted ml-2">· Opens: {marketStatus.next_open}</span>
            )}
          </div>
          <span className="text-xs text-text-muted flex items-center gap-1">
            <Clock size={12} /> Signals from last trading day
          </span>
        </div>
      )}
      {/* ── Kite-style Portfolio Summary ───────────────────────────── */}
      <div className="bg-background-surface border border-border-default rounded-2xl p-6 space-y-5">

        {/* Row 1: Invested → Current Value */}
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-bold text-text-muted uppercase tracking-wider mb-1">Total Invested</p>
            <p className="text-2xl font-black font-mono text-text-primary">
              {fmt(wallet?.invested_balance ?? 0)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs font-bold text-text-muted uppercase tracking-wider mb-1">Current Value</p>
            <p className="text-2xl font-black font-mono text-text-primary">
              {fmt((wallet?.invested_balance ?? 0) + (wallet?.unrealised_pnl ?? 0))}
            </p>
          </div>
        </div>

        {/* Row 2: P&L hero */}
        {(() => {
          const totalPnl = (wallet?.unrealised_pnl ?? 0) + (wallet?.realised_pnl ?? 0);
          const invested = wallet?.invested_balance ?? 0;
          const totalPct = invested > 0 ? (totalPnl / invested) * 100 : 0;
          const isUp = totalPnl >= 0;
          return (
            <div className={`rounded-xl px-5 py-4 flex items-center justify-between ${
              isUp ? 'bg-green/10 border border-green/20' : 'bg-red/10 border border-red/20'
            }`}>
              <div className="flex items-center gap-3">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center ${
                  isUp ? 'bg-green/20' : 'bg-red/20'
                }`}>
                  {isUp
                    ? <TrendingUp size={18} className="text-green" />
                    : <TrendingDown size={18} className="text-red" />}
                </div>
                <div>
                  <p className="text-xs font-bold text-text-muted uppercase tracking-wider">Total P&amp;L</p>
                  <p className={`text-xl font-black font-mono ${
                    isUp ? 'text-green' : 'text-red'
                  }`}>
                    {isUp ? '+' : ''}{fmtExact(totalPnl)}
                  </p>
                </div>
              </div>
              <div className={`text-right`}>
                <span className={`text-2xl font-black font-mono ${
                  isUp ? 'text-green' : 'text-red'
                }`}>
                  {isUp ? '+' : ''}{totalPct.toFixed(2)}%
                </span>
                <p className="text-[10px] text-text-muted mt-0.5">overall return</p>
              </div>
            </div>
          );
        })()}

        {/* Row 3: pills — unrealised / realised / cash */}
        <div className="grid grid-cols-3 gap-3">
          {[{
            label: 'Unrealised',
            value: wallet?.unrealised_pnl ?? 0,
            sub: 'open positions',
          }, {
            label: 'Realised',
            value: wallet?.realised_pnl ?? 0,
            sub: 'closed trades',
          }, {
            label: 'Cash',
            value: wallet?.cash_balance ?? 0,
            sub: 'available',
            neutral: true,
          }].map(({ label, value, sub, neutral }) => {
            const isUp = value >= 0;
            const color = neutral ? 'text-accent' : isUp ? 'text-green' : 'text-red';
            return (
              <div key={label} className="bg-background-elevated rounded-xl p-3 text-center">
                <p className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-sm font-black font-mono ${color}`}>
                  {!neutral && (isUp ? '+' : '')}{fmt(value)}
                </p>
                <p className="text-[10px] text-text-muted mt-0.5">{sub}</p>
              </div>
            );
          })}
        </div>

        {/* Row 4: risk mode + tier */}
        <div className="flex items-center justify-between pt-1 border-t border-border-default">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full animate-pulse ${
              wallet?.risk_mode === 'normal' ? 'bg-green' :
              wallet?.risk_mode === 'conservative' ? 'bg-amber' : 'bg-red'
            }`} />
            <span className={`text-xs font-bold uppercase ${
              wallet?.risk_mode === 'normal' ? 'text-green' :
              wallet?.risk_mode === 'conservative' ? 'text-amber' : 'text-red'
            }`}>{wallet?.risk_mode} mode</span>
          </div>
          <span className="text-xs text-text-muted">
            Equity {fmt(wallet?.total_equity ?? 0)} · Peak {fmt(wallet?.peak_equity ?? 0)}
          </span>
        </div>
      </div>

      {/* Middle Section: Today's Top Picks */}
      <section>
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <TrendingUp className="text-accent" />
          Today's Top Picks
          {marketStatus && !marketStatus.is_open && (
            <span className="text-xs font-normal text-amber bg-amber/10 px-2 py-0.5 rounded-full border border-amber/30">
              Reference only — market closed
            </span>
          )}
        </h2>
        {!topPicksData || topPicksData.length === 0 ? (
          <div className="bg-background-surface border border-dashed border-border-default rounded-xl p-8 text-center text-text-muted">
            No top picks yet — Celery scan runs at 8:30 AM, or generate signals manually from the Signals page.
          </div>
        ) : (
        <div className="flex gap-4 overflow-x-auto pb-4 scrollbar-hide">
          {topPicksData.map((pick) => (
            <div 
              key={pick.signal_id}
              onClick={() => navigate('/signals', { state: { symbol: pick.symbol } })}
              className="min-w-[260px] bg-background-surface border border-green/30 rounded-xl p-5 cursor-pointer hover:border-accent transition-all group"
            >
              <div className="flex justify-between items-start mb-3">
                <div className="min-w-0 flex-1 mr-2">
                  <h3 className="font-bold text-lg group-hover:text-accent transition-colors truncate">
                    {pick.symbol.split(':').pop()}
                  </h3>
                  <span className="text-[10px] text-text-muted uppercase tracking-widest">
                    {pick.symbol.split(':')[0]} · {pick.market_regime}
                  </span>
                </div>
                <SignalBadge action={pick.action} confidence={pick.confidence / 100} size="sm" />
              </div>
              <div className="space-y-2">
                {pick.rsi != null && (
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">RSI</span>
                    <span className="font-mono text-amber">{pick.rsi.toFixed(1)}</span>
                  </div>
                )}
                <div className="flex justify-between text-xs">
                  <span className="text-text-secondary">Confidence</span>
                  <span className="font-mono text-green">{pick.confidence.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-background-elevated h-1.5 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-green rounded-full transition-all duration-500" 
                    style={{ width: `${pick.confidence}%` }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
        )}
      </section>

      {/* Positions + Risk */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Open Positions — Kite style */}
        <div className="lg:col-span-2 bg-background-surface border border-border-default rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-border-default flex items-center justify-between">
            <h2 className="font-bold">Open Positions</h2>
            <span className="text-xs text-text-muted">{wallet?.open_positions?.length ?? 0} position{(wallet?.open_positions?.length ?? 0) !== 1 ? 's' : ''}</span>
          </div>
          {(!wallet?.open_positions || wallet.open_positions.length === 0) ? (
            <div className="py-12 text-center text-text-muted italic text-sm">No open positions</div>
          ) : (
            <div className="divide-y divide-border-default">
              {wallet.open_positions.map((pos) => {
                const invested = pos.entry_price * pos.quantity;
                const current  = pos.current_price * pos.quantity;
                const isUp = pos.unrealised_pnl >= 0;
                return (
                  <div key={pos.trade_id} className="px-5 py-4 hover:bg-background-elevated/30 transition-colors">
                    <div className="flex items-start justify-between">
                      {/* Left: symbol + meta */}
                      <div>
                        <div className="font-bold text-text-primary">{pos.symbol.split(':').pop()}</div>
                        <div className="text-xs text-text-muted mt-0.5">
                          {pos.quantity} shares &middot; {pos.trade_type}
                        </div>
                      </div>
                      {/* Right: P&L */}
                      <div className="text-right">
                        <div className={`font-black font-mono text-base ${
                          isUp ? 'text-green' : 'text-red'
                        }`}>
                          {isUp ? '+' : ''}{fmtExact(pos.unrealised_pnl)}
                        </div>
                        <div className={`text-xs font-bold ${
                          isUp ? 'text-green' : 'text-red'
                        }`}>
                          {isUp ? '+' : ''}{pos.pnl_pct.toFixed(2)}%
                        </div>
                      </div>
                    </div>
                    {/* Invested → Current row */}
                    <div className="flex items-center gap-4 mt-2">
                      <div>
                        <span className="text-[10px] text-text-muted uppercase tracking-wider">Invested </span>
                        <span className="text-xs font-mono text-text-secondary">{fmt(invested)}</span>
                      </div>
                      <ChevronRight size={12} className="text-text-muted" />
                      <div>
                        <span className="text-[10px] text-text-muted uppercase tracking-wider">Current </span>
                        <span className="text-xs font-mono text-text-primary font-bold">{fmt(current)}</span>
                      </div>
                      <div className="ml-auto flex gap-3 text-[10px] text-text-muted">
                        <span>SL {fmt(pos.stop_loss)}</span>
                        <span>TP {fmt(pos.take_profit)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Risk panel */}
        <div className="bg-background-surface border border-border-default rounded-xl p-6 flex flex-col gap-5">
          <h2 className="font-bold">Risk</h2>
          <div className="flex flex-col items-center text-center p-6 bg-background-elevated rounded-xl border border-border-subtle">
            <div className={`w-2.5 h-2.5 rounded-full mb-2 animate-pulse ${
              wallet?.risk_mode === 'normal' ? 'bg-green shadow-[0_0_10px_rgba(34,197,94,0.5)]' :
              wallet?.risk_mode === 'conservative' ? 'bg-amber shadow-[0_0_10px_rgba(245,158,11,0.5)]' :
              'bg-red shadow-[0_0_10px_rgba(239,68,68,0.5)]'
            }`} />
            <span className={`text-lg font-black uppercase ${
              wallet?.risk_mode === 'normal' ? 'text-green' :
              wallet?.risk_mode === 'conservative' ? 'text-amber' : 'text-red'
            }`}>{wallet?.risk_mode}</span>
            <p className="text-xs text-text-muted mt-1">
              {wallet?.risk_mode === 'normal' ? 'Full capacity' :
               wallet?.risk_mode === 'conservative' ? 'Reduced sizing' :
               'Trading stopped'}
            </p>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-text-muted">Drawdown from peak</span>
                <span className={(wallet?.drawdown_pct ?? 0) > 0.05 ? 'text-red font-bold' : 'text-text-primary'}>
                  {((wallet?.drawdown_pct ?? 0) * 100).toFixed(2)}%
                </span>
              </div>
              <div className="w-full bg-background-elevated h-2 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all ${
                  (wallet?.drawdown_pct ?? 0) > 0.08 ? 'bg-red' :
                  (wallet?.drawdown_pct ?? 0) > 0.05 ? 'bg-amber' : 'bg-accent'
                }`} style={{ width: `${Math.min((wallet?.drawdown_pct ?? 0) * 500, 100)}%` }} />
              </div>
              <div className="text-[10px] text-text-muted mt-1">Halt at 20% · Conservative at 12%</div>
            </div>
            <div className="grid grid-cols-2 gap-2 pt-1">
              {[{
                label: 'Today loss budget',
                value: fmt(wallet?.daily_budget?.remaining_loss_budget ?? 0),
              }, {
                label: 'Profit target',
                value: fmt(wallet?.daily_budget?.profit_target ?? 0),
              }].map(({ label, value }) => (
                <div key={label} className="bg-background-elevated rounded-lg p-2.5">
                  <div className="text-[10px] text-text-muted uppercase tracking-wider">{label}</div>
                  <div className="text-xs font-bold font-mono text-text-primary mt-0.5">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
