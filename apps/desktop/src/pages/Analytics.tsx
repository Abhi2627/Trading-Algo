import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp, TrendingDown, Target, Award,
  Clock, BarChart2, Zap, AlertCircle, RefreshCw
} from 'lucide-react';
import { getAnalytics, AnalyticsData } from '../lib/api';
import LoadingSpinner from '../components/LoadingSpinner';

const pct = (n: number, decimals = 1) =>
  `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`;

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

const KPI: React.FC<{
  label: string;
  value: string;
  sub?: string;
  color?: 'green' | 'red' | 'amber' | 'accent' | 'default';
  icon?: React.ReactNode;
}> = ({ label, value, sub, color = 'default', icon }) => {
  const colorMap = {
    green:   'text-green',
    red:     'text-red',
    amber:   'text-amber',
    accent:  'text-accent',
    default: 'text-text-primary',
  };
  return (
    <div className="bg-background-surface border border-border-default rounded-xl p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-text-muted uppercase tracking-wider">{label}</span>
        {icon && <span className="text-text-muted opacity-60">{icon}</span>}
      </div>
      <span className={`text-2xl font-black font-mono ${colorMap[color]}`}>{value}</span>
      {sub && <span className="text-xs text-text-muted">{sub}</span>}
    </div>
  );
};

const BarRow: React.FC<{
  label: string;
  value: number;
  max: number;
  count: number;
  winRate?: number;
  avgPnl?: number;
}> = ({ label, value, max, count, winRate, avgPnl }) => {
  const width = clamp((value / max) * 100, 4, 100);
  const isPositive = (avgPnl ?? 0) >= 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-28 text-right text-text-secondary text-xs font-mono shrink-0 capitalize">
        {label.replace(/_/g, ' ')}
      </span>
      <div className="flex-1 bg-background-elevated rounded-full h-2 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${isPositive ? 'bg-green' : 'bg-red'}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono text-xs text-text-muted">{count}</span>
      {winRate !== undefined && (
        <span className={`w-12 text-right font-mono text-xs font-bold ${winRate >= 50 ? 'text-green' : 'text-red'}`}>
          {winRate.toFixed(0)}%
        </span>
      )}
      {avgPnl !== undefined && (
        <span className={`w-14 text-right font-mono text-xs ${avgPnl >= 0 ? 'text-green' : 'text-red'}`}>
          {pct(avgPnl)}
        </span>
      )}
    </div>
  );
};

const EquityCurve: React.FC<{ data: AnalyticsData['equity_curve'] }> = ({ data }) => {
  const result = useMemo(() => {
    if (!data.length) return null;
    const W = 600, H = 120, PAD = 8;
    const xs = data.map((_, i) => PAD + (i / (data.length - 1 || 1)) * (W - PAD * 2));
    const ys = data.map(d => d.cumulative_pnl);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const range = maxY - minY || 1;
    const toY = (v: number) => PAD + ((maxY - v) / range) * (H - PAD * 2);
    const pts = data.map((d, i) => `${xs[i].toFixed(1)},${toY(d.cumulative_pnl).toFixed(1)}`);
    const area = `M ${pts[0]} ${pts.slice(1).map(p => `L ${p}`).join(' ')} L ${xs[xs.length-1].toFixed(1)},${H} L ${xs[0].toFixed(1)},${H} Z`;
    const line = `M ${pts[0]} ${pts.slice(1).map(p => `L ${p}`).join(' ')}`;
    return { area, line, xs, H, toY, minY, maxY };
  }, [data]);

  if (!result) {
    return (
      <div className="h-32 flex items-center justify-center text-text-muted text-sm italic">
        No trade data yet — equity curve appears after first closed trade
      </div>
    );
  }

  const { area, line, xs, H, toY, minY, maxY } = result;
  const last = data[data.length - 1];
  const isPositive = last.cumulative_pnl >= 0;

  return (
    <div className="relative">
      <svg viewBox={`0 0 600 ${H}`} className="w-full h-32" preserveAspectRatio="none">
        <defs>
          <linearGradient id="curveGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity="0.3" />
            <stop offset="100%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {minY < 0 && maxY > 0 && (
          <line x1="8" y1={toY(0).toFixed(1)} x2="592" y2={toY(0).toFixed(1)}
            stroke="#6b7280" strokeWidth="0.5" strokeDasharray="4,4" />
        )}
        <path d={area} fill="url(#curveGrad)" />
        <path d={line} fill="none" stroke={isPositive ? '#22c55e' : '#ef4444'}
          strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx={xs[xs.length - 1].toFixed(1)} cy={toY(last.cumulative_pnl).toFixed(1)}
          r="3" fill={isPositive ? '#22c55e' : '#ef4444'} />
      </svg>
      <div className="flex justify-between text-xs font-mono text-text-muted mt-1">
        <span>{data[0]?.date}</span>
        <span className={`font-bold ${isPositive ? 'text-green' : 'text-red'}`}>
          {last.cumulative_pnl >= 0 ? '+' : ''}&#8377;{last.cumulative_pnl.toFixed(2)}
        </span>
        <span>{last.date}</span>
      </div>
    </div>
  );
};

const WinDonut: React.FC<{ winRate: number; total: number }> = ({ winRate, total }) => {
  const r = 36, cx = 44, cy = 44, circ = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="88" height="88" viewBox="0 0 88 88">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle cx={cx} cy={cy} r={r} fill="none"
          stroke={winRate >= 50 ? '#22c55e' : '#ef4444'} strokeWidth="8"
          strokeDasharray={`${(winRate / 100) * circ} ${circ}`}
          strokeDashoffset={circ * 0.25} strokeLinecap="round"
          className="transition-all duration-1000" />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
          fontSize="14" fontWeight="900" fontFamily="monospace"
          fill={winRate >= 50 ? '#22c55e' : '#ef4444'}>
          {winRate.toFixed(0)}%
        </text>
      </svg>
      <span className="text-xs text-text-muted">{total} trades</span>
    </div>
  );
};

const Analytics: React.FC = () => {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['analytics'],
    queryFn: getAnalytics,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <div className="h-full flex items-center justify-center"><LoadingSpinner size="lg" /></div>;

  if (isError) return (
    <div className="h-full flex flex-col items-center justify-center text-center gap-4">
      <AlertCircle size={48} className="text-red" />
      <p className="text-text-muted">Failed to load analytics</p>
      <button onClick={() => refetch()} className="text-accent text-sm font-bold hover:underline">Retry</button>
    </div>
  );

  const d = data!;
  const noData = d.total_trades === 0;
  const exitMax  = Math.max(...Object.values(d.by_exit_reason).map(v => v.count), 1);
  const regMax   = Math.max(...Object.values(d.by_regime).map(v => v.count), 1);
  const confMax  = Math.max(...Object.values(d.by_confidence).map(v => v.count), 1);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Signal Analytics</h1>
          <p className="text-sm text-text-muted mt-1">
            Performance breakdown from closed trades · powered by signal_outcome table
          </p>
        </div>
        <button onClick={() => refetch()} disabled={isFetching}
          className="flex items-center gap-2 text-xs font-bold text-text-muted hover:text-accent transition-colors disabled:opacity-50">
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {noData ? (
        <div className="bg-background-surface border border-dashed border-border-default rounded-xl p-16 text-center">
          <BarChart2 size={48} className="text-text-muted mx-auto mb-4 opacity-40" />
          <h2 className="font-bold text-text-primary mb-2">No closed trades yet</h2>
          <p className="text-sm text-text-muted max-w-sm mx-auto">
            Analytics populate automatically after trades close via stop-loss, take-profit, or time exit.
            HDFCLIFE's time-exit will produce the first data point today.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KPI label="Win Rate" value={`${d.win_rate.toFixed(1)}%`}
              sub={`${d.win_count}W · ${d.loss_count}L`}
              color={d.win_rate >= 50 ? 'green' : 'red'} icon={<Target size={16} />} />
            <KPI label="Profit Factor"
              value={d.profit_factor >= 999 ? '\u221e' : d.profit_factor.toFixed(2)}
              sub="wins \u00f7 losses"
              color={d.profit_factor >= 1.5 ? 'green' : d.profit_factor >= 1 ? 'amber' : 'red'}
              icon={<Zap size={16} />} />
            <KPI label="Avg P&L" value={pct(d.avg_pnl_pct)}
              sub={`W: ${pct(d.avg_win_pct)} · L: ${pct(d.avg_loss_pct)}`}
              color={d.avg_pnl_pct >= 0 ? 'green' : 'red'} icon={<TrendingUp size={16} />} />
            <KPI label="Avg Hold Time" value={`${d.avg_days_held.toFixed(1)}d`}
              sub={`across ${d.total_trades} trades`} icon={<Clock size={16} />} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <div className="lg:col-span-3 bg-background-surface border border-border-default rounded-xl p-6">
              <h2 className="font-bold text-text-primary mb-4 flex items-center gap-2">
                <TrendingUp size={16} className="text-accent" /> Equity Curve
              </h2>
              <EquityCurve data={d.equity_curve} />
            </div>
            <div className="bg-background-surface border border-border-default rounded-xl p-6 flex flex-col items-center justify-center gap-3">
              <h2 className="font-bold text-text-primary text-sm">Win Rate</h2>
              <WinDonut winRate={d.win_rate} total={d.total_trades} />
              <div className="text-center space-y-1">
                <div className="text-xs text-text-muted">Target: <span className="text-accent font-bold">&ge;55%</span></div>
                <div className={`text-xs font-bold ${d.win_rate >= 55 ? 'text-green' : 'text-amber'}`}>
                  {d.win_rate >= 55 ? '\u2705 On track for live' : '\u26a0 Below Zerodha threshold'}
                </div>
              </div>
            </div>
          </div>

          {(d.best_trade || d.worst_trade) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {d.best_trade && (
                <div className="bg-green/5 border border-green/20 rounded-xl p-5 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full bg-green/20 flex items-center justify-center shrink-0">
                    <Award size={18} className="text-green" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-text-muted font-bold uppercase tracking-wider mb-1">Best Trade</div>
                    <div className="font-bold text-text-primary truncate">{d.best_trade.symbol.split(':').pop()}</div>
                    <div className="text-xs text-text-muted">
                      {d.best_trade.exit_reason?.replace(/_/g, ' ')} &middot; {d.best_trade.days_held?.toFixed(1)}d held
                    </div>
                  </div>
                  <span className="text-xl font-black text-green font-mono shrink-0">{pct(d.best_trade.pnl_pct)}</span>
                </div>
              )}
              {d.worst_trade && (
                <div className="bg-red/5 border border-red/20 rounded-xl p-5 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full bg-red/20 flex items-center justify-center shrink-0">
                    <TrendingDown size={18} className="text-red" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-text-muted font-bold uppercase tracking-wider mb-1">Worst Trade</div>
                    <div className="font-bold text-text-primary truncate">{d.worst_trade.symbol.split(':').pop()}</div>
                    <div className="text-xs text-text-muted">
                      {d.worst_trade.exit_reason?.replace(/_/g, ' ')} &middot; {d.worst_trade.days_held?.toFixed(1)}d held
                    </div>
                  </div>
                  <span className="text-xl font-black text-red font-mono shrink-0">{pct(d.worst_trade.pnl_pct)}</span>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="bg-background-surface border border-border-default rounded-xl p-5">
              <h3 className="font-bold text-text-primary text-sm mb-4 flex items-center gap-2">
                <BarChart2 size={14} className="text-accent" /> Exit Reason
              </h3>
              <div className="space-y-3">
                <div className="flex text-[10px] font-bold text-text-muted uppercase tracking-wider justify-end gap-2">
                  <span className="w-10 text-right">Count</span>
                  <span className="w-12 text-right">Win%</span>
                  <span className="w-14 text-right">Avg P&L</span>
                </div>
                {Object.entries(d.by_exit_reason).map(([k, v]) => (
                  <BarRow key={k} label={k} value={v.count} max={exitMax}
                    count={v.count} winRate={v.win_rate} avgPnl={v.avg_pnl_pct} />
                ))}
                {!Object.keys(d.by_exit_reason).length && <p className="text-xs text-text-muted italic text-center py-4">No data</p>}
              </div>
            </div>

            <div className="bg-background-surface border border-border-default rounded-xl p-5">
              <h3 className="font-bold text-text-primary text-sm mb-4 flex items-center gap-2">
                <Zap size={14} className="text-accent" /> Market Regime
              </h3>
              <div className="space-y-3">
                <div className="flex text-[10px] font-bold text-text-muted uppercase tracking-wider justify-end gap-2">
                  <span className="w-10 text-right">Count</span>
                  <span className="w-12 text-right">Win%</span>
                </div>
                {Object.entries(d.by_regime).map(([k, v]) => (
                  <BarRow key={k} label={k} value={v.count} max={regMax} count={v.count} winRate={v.win_rate} />
                ))}
                {!Object.keys(d.by_regime).length && <p className="text-xs text-text-muted italic text-center py-4">No data</p>}
              </div>
            </div>

            <div className="bg-background-surface border border-border-default rounded-xl p-5">
              <h3 className="font-bold text-text-primary text-sm mb-4 flex items-center gap-2">
                <Target size={14} className="text-accent" /> Confidence Bucket
              </h3>
              <div className="space-y-3">
                <div className="flex text-[10px] font-bold text-text-muted uppercase tracking-wider justify-end gap-2">
                  <span className="w-10 text-right">Count</span>
                  <span className="w-12 text-right">Win%</span>
                  <span className="w-14 text-right">Avg P&L</span>
                </div>
                {Object.entries(d.by_confidence).map(([k, v]) => (
                  <BarRow key={k} label={k} value={v.count} max={confMax}
                    count={v.count} winRate={v.win_rate} avgPnl={v.avg_pnl_pct} />
                ))}
                {!Object.keys(d.by_confidence).length && <p className="text-xs text-text-muted italic text-center py-4">No data</p>}
              </div>
              <p className="text-[10px] text-text-muted mt-4 border-t border-border-default pt-3">
                Higher confidence should &rarr; higher win rate. If not, model calibration needs work.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default Analytics;
