import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { 
  TrendingUp, 
  Wallet as WalletIcon, 
  Banknote, 
  ArrowDownCircle,
  AlertCircle,
  AlertTriangle,
  Clock
} from 'lucide-react';
import { getWalletSummary, getTopPicks, getMarketStatus, TopPick } from '../lib/api';
import { queryKeys } from '../lib/queryKeys';
import StatCard from '../components/StatCard';
import SignalBadge from '../components/SignalBadge';
import LoadingSpinner from '../components/LoadingSpinner';

const formatINR = (value: number) => {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value);
};

const Dashboard: React.FC = () => {
  const navigate = useNavigate();

  const { 
    data: wallet, 
    isLoading: isWalletLoading, 
    isError: isWalletError 
  } = useQuery({
    queryKey: queryKeys.wallet,
    queryFn: getWalletSummary,
    refetchInterval: 5000,
  });

  const { data: topPicksData, isLoading: isSignalsLoading } = useQuery<TopPick[]>({
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
    refetchInterval: 30000,
  });

  const { data: marketStatus } = useQuery({
    queryKey: ['market-status'],
    queryFn: getMarketStatus,
    refetchInterval: 60 * 1000,
  });

  if (isWalletLoading || isSignalsLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (isWalletError) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center">
        <AlertCircle size={48} className="text-red mb-4" />
        <h2 className="text-xl font-bold mb-2">Failed to fetch data</h2>
        <p className="text-text-secondary">Make sure the backend is running at http://localhost:8000</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Market Status Banner */}
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
      {/* Top Row: Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          label="Total Equity"
          value={formatINR(wallet?.total_equity ?? 0)}
          icon={<WalletIcon size={20} />}
          trend="neutral"
        />
        <StatCard
          label="Cash Balance"
          value={formatINR(wallet?.cash_balance ?? 0)}
          icon={<Banknote size={20} />}
        />
        <StatCard
          label="Realized P&L"
          value={formatINR(wallet?.realised_pnl ?? 0)}
          trend={(wallet?.realised_pnl ?? 0) >= 0 ? 'up' : 'down'}
          icon={<TrendingUp size={20} />}
        />
        <StatCard
          label="Drawdown %"
          value={`${(wallet?.drawdown_pct ?? 0).toFixed(2)}%`}
          trend={(wallet?.drawdown_pct ?? 0) > 5 ? 'down' : 'up'}
          icon={<ArrowDownCircle size={20} />}
        />
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

      {/* Bottom Section: Positions & Risk */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Open Positions Table */}
        <div className="lg:col-span-2 bg-background-surface border border-border-default rounded-xl overflow-hidden">
          <div className="p-5 border-b border-border-default">
            <h2 className="font-bold">Open Positions</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-xs text-text-muted uppercase bg-background-elevated/50">
                <tr>
                  <th className="px-6 py-4 font-medium">Symbol</th>
                  <th className="px-6 py-4 font-medium text-right">Qty</th>
                  <th className="px-6 py-4 font-medium text-right">Entry</th>
                  <th className="px-6 py-4 font-medium text-right">Current</th>
                  <th className="px-6 py-4 font-medium text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {wallet?.open_positions.map((pos) => (
                  <tr key={pos.trade_id} className="hover:bg-background-elevated/30 transition-colors">
                    <td className="px-6 py-4 font-bold">{pos.symbol}</td>
                    <td className="px-6 py-4 text-right font-mono">{pos.quantity}</td>
                    <td className="px-6 py-4 text-right font-mono">{formatINR(pos.entry_price)}</td>
                    <td className="px-6 py-4 text-right font-mono">{formatINR(pos.current_price)}</td>
                    <td className={`px-6 py-4 text-right font-bold font-mono ${pos.unrealised_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                      {pos.unrealised_pnl >= 0 ? '+' : ''}{formatINR(pos.unrealised_pnl)}
                      <div className="text-[10px] opacity-80">{pos.pnl_pct.toFixed(2)}%</div>
                    </td>
                  </tr>
                ))}
                {(!wallet?.open_positions || wallet.open_positions.length === 0) && (
                  <tr>
                    <td colSpan={5} className="px-6 py-12 text-center text-text-muted italic">
                      No open positions
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Risk Mode Indicator */}
        <div className="bg-background-surface border border-border-default rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h2 className="font-bold mb-6">Risk Management</h2>
            <div className="flex flex-col items-center text-center p-8 bg-background-elevated rounded-2xl border border-border-subtle mb-6">
              <div className={`w-3 h-3 rounded-full mb-3 animate-pulse ${
                wallet?.risk_mode === 'normal' ? 'bg-green shadow-[0_0_12px_rgba(34,197,94,0.5)]' :
                wallet?.risk_mode === 'conservative' ? 'bg-amber shadow-[0_0_12px_rgba(245,158,11,0.5)]' :
                'bg-red shadow-[0_0_12px_rgba(239,68,68,0.5)]'
              }`} />
              <span className={`text-2xl font-black uppercase tracking-tighter ${
                wallet?.risk_mode === 'normal' ? 'text-green' :
                wallet?.risk_mode === 'conservative' ? 'text-amber' :
                'text-red'
              }`}>
                {wallet?.risk_mode} Mode
              </span>
              <p className="text-xs text-text-secondary mt-2">
                {wallet?.risk_mode === 'normal' ? 'All systems active — trading at full capacity' :
                 wallet?.risk_mode === 'conservative' ? 'Reduced position sizing — low cash balance' :
                 'Trading STOPPED — wallet empty or risk limit hit. Add funds and call /wallet/resume.'}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-xs font-medium">
              <span className="text-text-secondary">Daily Drawdown</span>
              <span className={(wallet?.drawdown_pct ?? 0) > 5 ? 'text-red' : 'text-text-primary'}>
                {(wallet?.drawdown_pct ?? 0).toFixed(2)}% / 10.00%
              </span>
            </div>
            <div className="w-full bg-background-elevated h-3 rounded-full overflow-hidden border border-border-default p-0.5">
              <div 
                className={`h-full rounded-full transition-all duration-1000 ${
                  (wallet?.drawdown_pct || 0) > 8 ? 'bg-red' :
                  (wallet?.drawdown_pct || 0) > 5 ? 'bg-amber' :
                  'bg-accent'
                }`}
                style={{ width: `${Math.min((wallet?.drawdown_pct || 0) * 10, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
