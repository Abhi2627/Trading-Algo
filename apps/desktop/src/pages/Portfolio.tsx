import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip, 
  ResponsiveContainer 
} from 'recharts';
import { 
  getWalletSummary, 
  closeTrade,
  getTradeHistory,
  WalletSummary,
  Position,
  TradeHistory,
  TradeHistoryItem
} from '../lib/api';
import { queryKeys } from '../lib/queryKeys';
import StatCard from '../components/StatCard';
import LoadingSpinner from '../components/LoadingSpinner';
import { 
  Wallet, 
  TrendingUp, 
  ArrowDownCircle, 
  Target, 
  ShieldAlert,
  Info
} from 'lucide-react';

const formatINR = (v: number) =>
  new Intl.NumberFormat('en-IN', { 
    style: 'currency', 
    currency: 'INR',
    maximumFractionDigits: 0 
  }).format(v);

const Portfolio: React.FC = () => {
  const queryClient = useQueryClient();

  const { data: wallet, isLoading, isError } = useQuery<WalletSummary>({
    queryKey: queryKeys.wallet,
    queryFn: getWalletSummary,
    refetchInterval: 5000,
  });

  const { data: history } = useQuery<TradeHistory>({
    queryKey: queryKeys.tradeHistory,
    queryFn: () => getTradeHistory(50),
  });

  const closeMutation = useMutation({
    mutationFn: (tradeId: string) => closeTrade(tradeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.wallet });
    },
  });

  // Generate 30 mock data points for equity curve
  const chartData = Array.from({ length: 30 }, (_, i) => {
    const base = 100000;
    const randomVariation = Math.sin(i / 5) * 5000 + (Math.random() - 0.5) * 2000;
    const equity = i === 29 && wallet ? wallet.total_equity : base + (i * 1000) + randomVariation;
    return {
      date: `Day ${i + 1}`,
      equity,
    };
  });

  if (isLoading) return <div className="h-full flex items-center justify-center"><LoadingSpinner size="lg" /></div>;
  if (isError || !wallet) return <div className="p-8 text-center text-red">Failed to load portfolio data.</div>;

  return (
    <div className="space-y-8">
      {/* Top: Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatCard
          label="Total Equity"
          value={formatINR(wallet.total_equity)}
          icon={<Wallet size={20} />}
        />
        <StatCard
          label="Realised P&L"
          value={formatINR(wallet.realised_pnl)}
          trend={wallet.realised_pnl >= 0 ? 'up' : 'down'}
          icon={<TrendingUp size={20} />}
        />
        <StatCard
          label="Unrealised P&L"
          value={formatINR(wallet.unrealised_pnl)}
          trend={wallet.unrealised_pnl >= 0 ? 'up' : 'down'}
          icon={<ArrowDownCircle size={20} />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        {/* Middle left: Open Positions */}
        <div className="lg:col-span-3 space-y-4">
          <div className="bg-background-surface border border-border-default rounded-xl overflow-hidden">
            <div className="p-5 border-b border-border-default flex justify-between items-center">
              <h2 className="font-bold flex items-center gap-2">
                <Target size={18} className="text-accent" />
                Open Positions
              </h2>
              <span className="text-xs bg-background-elevated px-2 py-1 rounded text-text-muted font-mono">
                {wallet.open_count} ACTIVE
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-[10px] text-text-muted uppercase bg-background-elevated/50 font-bold tracking-wider">
                  <tr>
                    <th className="px-6 py-4">Asset</th>
                    <th className="px-6 py-4">Type</th>
                    <th className="px-6 py-4 text-right">Entry / Current</th>
                    <th className="px-6 py-4 text-right">Stop / Target</th>
                    <th className="px-6 py-4 text-right">P&L</th>
                    <th className="px-6 py-4 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-default text-sm">
                  {wallet.open_positions.map((pos: Position) => (
                    <tr key={pos.trade_id} className="hover:bg-background-elevated/30 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-bold text-text-primary">{pos.symbol}</div>
                        <div className="text-[10px] text-text-muted">{pos.name}</div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`text-[10px] px-2 py-0.5 rounded font-black uppercase ${
                          pos.trade_type === 'intraday' ? 'bg-amber/10 text-amber' : 'bg-indigo/10 text-indigo-400'
                        }`}>
                          {pos.trade_type}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right font-mono">
                        <div className="text-text-secondary">{formatINR(pos.entry_price)}</div>
                        <div className="text-text-primary font-bold">{formatINR(pos.current_price)}</div>
                      </td>
                      <td className="px-6 py-4 text-right font-mono text-xs">
                        <div className="text-red/80">SL: {formatINR(pos.stop_loss)}</div>
                        <div className="text-green/80">TP: {formatINR(pos.take_profit)}</div>
                      </td>
                      <td className={`px-6 py-4 text-right font-bold font-mono ${pos.unrealised_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                        <div>{pos.unrealised_pnl >= 0 ? '+' : ''}{formatINR(pos.unrealised_pnl)}</div>
                        <div className="text-[10px] opacity-80">{pos.pnl_pct.toFixed(2)}%</div>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <button
                          onClick={() => closeMutation.mutate(pos.trade_id)}
                          disabled={closeMutation.isPending && closeMutation.variables === pos.trade_id}
                          className="bg-red/10 hover:bg-red text-red hover:text-white border border-red/20 px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                        >
                          {closeMutation.isPending && closeMutation.variables === pos.trade_id ? 'Closing...' : 'Close'}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {wallet.open_positions.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-6 py-20 text-center text-text-muted italic">
                        No open positions. Generate signals and execute trades.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Middle right: Daily Budget */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-background-surface border border-border-default rounded-xl p-6">
            <h2 className="font-bold mb-6 flex items-center gap-2">
              <ShieldAlert size={18} className="text-amber" />
              Daily Risk Budget
            </h2>
            
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-background-elevated p-4 rounded-xl border border-border-default">
                  <div className="text-[10px] text-text-muted uppercase font-bold mb-1">Profit Target</div>
                  <div className="text-lg font-bold text-green">{formatINR(wallet.daily_budget.profit_target)}</div>
                </div>
                <div className="bg-background-elevated p-4 rounded-xl border border-border-default">
                  <div className="text-[10px] text-text-muted uppercase font-bold mb-1">Loss Limit</div>
                  <div className="text-lg font-bold text-red">{formatINR(wallet.daily_budget.loss_limit)}</div>
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex justify-between text-xs font-bold">
                  <span className="text-text-secondary uppercase">Loss Used Today</span>
                  <span className={wallet.daily_budget.loss_used_today / wallet.daily_budget.loss_limit > 0.8 ? 'text-red' : 'text-text-primary'}>
                    {formatINR(wallet.daily_budget.loss_used_today)} / {formatINR(wallet.daily_budget.loss_limit)}
                  </span>
                </div>
                <div className="h-2 w-full bg-background-elevated rounded-full overflow-hidden">
                  <div 
                    className={`h-full transition-all duration-1000 rounded-full ${
                      wallet.daily_budget.loss_used_today / wallet.daily_budget.loss_limit > 0.8 ? 'bg-red' :
                      wallet.daily_budget.loss_used_today / wallet.daily_budget.loss_limit > 0.5 ? 'bg-amber' : 'bg-green'
                    }`}
                    style={{ width: `${Math.min((wallet.daily_budget.loss_used_today / wallet.daily_budget.loss_limit) * 100, 100)}%` }}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between p-4 bg-background-elevated rounded-xl border border-border-default">
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full animate-pulse ${
                    wallet.risk_mode === 'normal' ? 'bg-green' :
                    wallet.risk_mode === 'conservative' ? 'bg-amber' : 'bg-red'
                  }`} />
                  <span className="text-sm font-bold uppercase tracking-tighter">
                    {wallet.risk_mode} Risk Mode
                  </span>
                </div>
                <span className="text-[10px] font-bold text-text-muted uppercase">System Status</span>
              </div>
            </div>
          </div>

          <div className="bg-accent/5 border border-accent/20 rounded-xl p-5 flex items-start gap-4">
            <Info className="text-accent flex-shrink-0" size={20} />
            <div>
              <div className="text-sm font-bold text-text-primary mb-1">Monthly Topup</div>
              <p className="text-xs text-text-secondary leading-relaxed">
                {formatINR(wallet.monthly_topup)} will be added to your cash balance on the 1st of every month automatically.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Trade History */}
      <div className="bg-background-surface border border-border-default rounded-xl overflow-hidden">
        <div className="p-5 border-b border-border-default">
          <h2 className="font-bold flex items-center gap-2">
            <TrendingUp size={18} className="text-indigo-400" />
            Trade History
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-[10px] text-text-muted uppercase bg-background-elevated/50 font-bold tracking-wider">
              <tr>
                <th className="px-6 py-4">Symbol</th>
                <th className="px-6 py-4">Action</th>
                <th className="px-6 py-4 text-right">Entry</th>
                <th className="px-6 py-4 text-right">Exit</th>
                <th className="px-6 py-4 text-right">P&L</th>
                <th className="px-6 py-4 text-right">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default text-sm">
              {history?.trades.map((item: TradeHistoryItem, idx: number) => (
                <tr key={idx} className="hover:bg-background-elevated/30 transition-colors">
                  <td className="px-6 py-4 font-bold text-text-primary">{item.symbol}</td>
                  <td className="px-6 py-4">
                    <span className="text-[10px] px-2 py-0.5 rounded font-black uppercase bg-indigo/10 text-indigo-400">
                      {item.action}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right font-mono">{formatINR(item.entry_price)}</td>
                  <td className="px-6 py-4 text-right font-mono">{formatINR(item.exit_price)}</td>
                  <td className={`px-6 py-4 text-right font-bold font-mono ${item.realized_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                    {item.realized_pnl >= 0 ? '+' : ''}{formatINR(item.realized_pnl)}
                  </td>
                  <td className="px-6 py-4 text-right text-text-muted text-xs">
                    {item.exit_time ? new Date(item.exit_time).toLocaleDateString() : 'N/A'}
                  </td>
                </tr>
              ))}
              {(!history || history.trades.length === 0) && (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-text-muted italic">
                    No completed trades yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bottom: Equity Chart */}
      <div className="bg-background-surface border border-border-default rounded-xl p-6">
        <div className="flex justify-between items-center mb-8">
          <h2 className="font-bold">Equity Curve</h2>
          <span className="text-xs text-text-muted italic">(simulated — will use real data after trades)</span>
        </div>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <XAxis 
                dataKey="date" 
                hide 
              />
              <YAxis 
                domain={['auto', 'auto']}
                tickFormatter={(val) => `₹${val/1000}k`}
                stroke="#475569"
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip 
                contentStyle={{ backgroundColor: '#111118', border: '1px solid #1e1e2e', borderRadius: '8px' }}
                itemStyle={{ color: '#6366f1', fontWeight: 'bold' }}
                formatter={(val: any) => [formatINR(Number(val)), 'Equity']}
                labelStyle={{ color: '#94a3b8', fontSize: '10px', textTransform: 'uppercase', fontWeight: 'bold' }}
              />
              <Area 
                type="monotone" 
                dataKey="equity" 
                stroke="#6366f1" 
                strokeWidth={3}
                fillOpacity={1} 
                fill="url(#colorEquity)" 
                animationDuration={2000}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

export default Portfolio;
