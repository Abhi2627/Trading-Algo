import React, { useState, useMemo } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Play, RotateCcw, TrendingUp, TrendingDown, Target,
  CheckCircle, XCircle, ChevronDown, ChevronUp, BarChart2,
  Zap, Clock, Shield
} from 'lucide-react';
import api from '../lib/api';

// ─── types ──────────────────────────────────────────────────────────────────

interface BacktestMetrics {
  total_return_pct:  number;
  cagr_pct:          number;
  sharpe:            number;
  sortino:           number;
  calmar:            number;
  max_drawdown_pct:  number;
  win_rate_pct:      number;
  profit_factor:     number;
  avg_win_pct:       number;
  avg_loss_pct:      number;
  total_trades:      number;
  winning_trades:    number;
  losing_trades:     number;
  is_live_ready:     boolean;
}

interface BacktestTrade {
  symbol:     string;
  entry_date: string;
  exit_date:  string;
  entry_price: number;
  exit_price:  number;
  pnl:         number;
  pnl_pct:     number;
  exit_reason: string;
}

interface BacktestResult {
  success:       boolean;
  trades:        BacktestTrade[];
  trade_count:   number;
  equity_curve:  Array<{ date: string; equity: number }>;
  metrics:       BacktestMetrics | null;
  message:       string;
}

interface Preset {
  name:            string;
  description:     string;
  min_confidence:  number;
  stop_loss_pct:   number;
  take_profit_pct: number;
  time_exit_days:  number;
  symbols:         string[];
}

// ─── helpers ─────────────────────────────────────────────────────────────────

const fmt = (v: number, decimals = 2) => v.toFixed(decimals);
const pct  = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;

const MetricCard: React.FC<{
  label: string; value: string; sub?: string;
  color?: 'green' | 'red' | 'amber' | 'default'; icon?: React.ReactNode;
}> = ({ label, value, sub, color = 'default', icon }) => {
  const c = { green: 'text-green', red: 'text-red', amber: 'text-amber', default: 'text-text-primary' }[color];
  return (
    <div className="bg-background-elevated rounded-xl p-4 flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-text-muted uppercase tracking-wider">{label}</span>
        {icon && <span className="text-text-muted opacity-50">{icon}</span>}
      </div>
      <span className={`text-xl font-black font-mono ${c}`}>{value}</span>
      {sub && <span className="text-[10px] text-text-muted">{sub}</span>}
    </div>
  );
};

const EquityCurve: React.FC<{ data: Array<{ date: string; equity: number }>; initial: number }> = ({ data, initial }) => {
  const result = useMemo(() => {
    if (!data?.length) return null;
    const W = 600, H = 120, PAD = 8;
    const xs = data.map((_, i) => PAD + (i / (data.length - 1 || 1)) * (W - PAD * 2));
    const ys = data.map(d => d.equity);
    const minY = Math.min(...ys, initial * 0.95);
    const maxY = Math.max(...ys, initial * 1.05);
    const range = maxY - minY || 1;
    const toY = (v: number) => PAD + ((maxY - v) / range) * (H - PAD * 2);
    const pts = data.map((d, i) => `${xs[i].toFixed(1)},${toY(d.equity).toFixed(1)}`);
    const line = `M ${pts[0]} ${pts.slice(1).map(p => `L ${p}`).join(' ')}`;
    const area = `${line} L ${xs[xs.length-1].toFixed(1)},${H} L ${xs[0].toFixed(1)},${H} Z`;
    const zeroY = toY(initial);
    return { line, area, xs, H, toY, zeroY };
  }, [data, initial]);

  if (!result) return <div className="h-32 flex items-center justify-center text-text-muted text-sm italic">No data</div>;

  const last = data[data.length - 1];
  const isPos = last.equity >= initial;
  const color = isPos ? '#22c55e' : '#ef4444';

  return (
    <div>
      <svg viewBox={`0 0 600 ${result.H}`} className="w-full h-32" preserveAspectRatio="none">
        <defs>
          <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <line x1="8" y1={result.zeroY.toFixed(1)} x2="592" y2={result.zeroY.toFixed(1)}
          stroke="#6b7280" strokeWidth="0.5" strokeDasharray="4,4" />
        <path d={result.area} fill="url(#btGrad)" />
        <path d={result.line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx={result.xs[result.xs.length-1].toFixed(1)}
          cy={result.toY(last.equity).toFixed(1)} r="3" fill={color} />
      </svg>
      <div className="flex justify-between text-xs font-mono text-text-muted mt-1">
        <span>{data[0]?.date}</span>
        <span style={{color}} className="font-bold">₹{last.equity.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
        <span>{last.date}</span>
      </div>
    </div>
  );
};

// ─── main page ───────────────────────────────────────────────────────────────

const ALL_SYMBOLS = [
  'NSE:RELIANCE', 'NSE:TCS', 'NSE:HDFCBANK', 'NSE:INFY', 'NSE:ICICIBANK',
  'NSE:SBIN', 'NSE:BHARTIARTL', 'NSE:ITC', 'NSE:KOTAKBANK', 'NSE:LT',
  'NSE:AXISBANK', 'NSE:WIPRO', 'NSE:ULTRACEMCO', 'NSE:SUNPHARMA', 'NSE:TITAN',
  'NSE:BAJFINANCE', 'NSE:MARUTI', 'NSE:ADANIENT', 'NSE:POWERGRID', 'NSE:NTPC',
];

const Backtest: React.FC = () => {
  const [symbols,        setSymbols]       = useState<string[]>(ALL_SYMBOLS.slice(0, 12));
  const [startDate,      setStartDate]     = useState('2022-01-01');
  const [endDate,        setEndDate]       = useState('2024-12-31');
  const [capital,        setCapital]       = useState(100000);
  const [minConf,        setMinConf]       = useState(0.70);
  const [slPct,          setSlPct]         = useState(0.03);
  const [tpPct,          setTpPct]         = useState(0.08);
  const [timeExit,       setTimeExit]      = useState(7);
  const [showTrades,     setShowTrades]    = useState(false);
  const [result,         setResult]        = useState<BacktestResult | null>(null);

  const { data: presetsData } = useQuery({
    queryKey: ['backtest-presets'],
    queryFn: async () => {
      const { data } = await api.get('/backtest/presets');
      return data;
    },
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post<BacktestResult>('/backtest/run', {
        symbols, start_date: startDate, end_date: endDate,
        initial_capital: capital, min_confidence: minConf,
        stop_loss_pct: slPct, take_profit_pct: tpPct,
        time_exit_days: timeExit,
      });
      return data;
    },
    onSuccess: (data) => setResult(data),
  });

  const applyPreset = (p: Preset) => {
    setMinConf(p.min_confidence);
    setSlPct(p.stop_loss_pct);
    setTpPct(p.take_profit_pct);
    setTimeExit(p.time_exit_days);
    setSymbols(p.symbols);
  };

  const toggleSymbol = (sym: string) => {
    setSymbols(prev =>
      prev.includes(sym) ? prev.filter(s => s !== sym) : [...prev, sym]
    );
  };

  const m = result?.metrics;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-text-primary">Backtesting</h1>
        <p className="text-sm text-text-muted mt-1">
          Validate strategy parameters against historical NSE data before going live
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Config panel */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-background-surface border border-border-default rounded-xl p-5 space-y-4">
            <h2 className="font-bold text-text-primary text-sm">Configuration</h2>

            {/* Presets */}
            {presetsData?.presets && (
              <div>
                <label className="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-2">Quick Presets</label>
                <div className="space-y-2">
                  {presetsData.presets.map((p: Preset) => (
                    <button key={p.name} onClick={() => applyPreset(p)}
                      className="w-full text-left px-3 py-2 rounded-lg bg-background-elevated hover:bg-background-elevated/80 transition-colors border border-border-default">
                      <div className="text-xs font-bold text-text-primary">{p.name}</div>
                      <div className="text-[10px] text-text-muted mt-0.5">{p.description}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Date range */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">Start</label>
                <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                  className="w-full bg-background-elevated border border-border-default rounded-lg px-2 py-1.5 text-xs text-text-primary font-mono" />
              </div>
              <div>
                <label className="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">End</label>
                <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                  className="w-full bg-background-elevated border border-border-default rounded-lg px-2 py-1.5 text-xs text-text-primary font-mono" />
              </div>
            </div>

            {/* Capital */}
            <div>
              <label className="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">Capital (₹)</label>
              <input type="number" value={capital} onChange={e => setCapital(+e.target.value)}
                className="w-full bg-background-elevated border border-border-default rounded-lg px-3 py-1.5 text-xs text-text-primary font-mono" />
            </div>

            {/* Strategy params */}
            {[
              { label: 'Min Confidence', val: minConf, set: setMinConf, step: 0.05, min: 0.5, max: 0.95, fmt: (v: number) => `${(v*100).toFixed(0)}%` },
              { label: 'Stop Loss %', val: slPct,  set: setSlPct,  step: 0.005, min: 0.01, max: 0.10, fmt: (v: number) => `${(v*100).toFixed(1)}%` },
              { label: 'Take Profit %', val: tpPct, set: setTpPct,  step: 0.01,  min: 0.02, max: 0.25, fmt: (v: number) => `${(v*100).toFixed(1)}%` },
              { label: 'Time Exit Days', val: timeExit, set: setTimeExit, step: 1, min: 1, max: 30, fmt: (v: number) => `${v}d` },
            ].map(({ label, val, set, step, min, max, fmt: f }) => (
              <div key={label}>
                <div className="flex justify-between mb-1">
                  <label className="text-[10px] font-bold text-text-muted uppercase tracking-wider">{label}</label>
                  <span className="text-[10px] font-mono text-accent">{f(val)}</span>
                </div>
                <input type="range" value={val} step={step} min={min} max={max}
                  onChange={e => set(+e.target.value)}
                  className="w-full accent-accent" />
              </div>
            ))}

            {/* Run button */}
            <button onClick={() => mutation.mutate()}
              disabled={mutation.isPending || symbols.length === 0}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl
                bg-accent text-background font-bold text-sm
                hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed
                transition-all">
              {mutation.isPending ? (
                <>
                  <div className="w-4 h-4 border-2 border-background border-t-transparent rounded-full animate-spin" />
                  Running... (~60s)
                </>
              ) : (
                <>
                  <Play size={16} /> Run Backtest ({symbols.length} symbols)
                </>
              )}
            </button>

            {mutation.isError && (
              <p className="text-xs text-red text-center">Backtest failed — check server logs</p>
            )}
          </div>

          {/* Symbol selector */}
          <div className="bg-background-surface border border-border-default rounded-xl p-5">
            <h3 className="font-bold text-text-primary text-sm mb-3">
              Symbols <span className="text-text-muted font-normal">({symbols.length}/{ALL_SYMBOLS.length})</span>
            </h3>
            <div className="grid grid-cols-2 gap-1.5">
              {ALL_SYMBOLS.map(sym => {
                const ticker = sym.split(':')[1];
                const active = symbols.includes(sym);
                return (
                  <button key={sym} onClick={() => toggleSymbol(sym)}
                    className={`text-[10px] font-bold font-mono px-2 py-1.5 rounded-lg border transition-all text-left ${
                      active
                        ? 'bg-accent/20 border-accent/40 text-accent'
                        : 'bg-background-elevated border-border-default text-text-muted hover:border-accent/30'
                    }`}>
                    {ticker}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Results panel */}
        <div className="lg:col-span-2 space-y-4">
          {!result && !mutation.isPending && (
            <div className="bg-background-surface border border-dashed border-border-default rounded-xl p-16 text-center">
              <BarChart2 size={48} className="text-text-muted mx-auto mb-4 opacity-30" />
              <h2 className="font-bold text-text-primary mb-2">No backtest run yet</h2>
              <p className="text-sm text-text-muted max-w-sm mx-auto">
                Configure parameters and click Run Backtest to validate your strategy against historical data.
              </p>
            </div>
          )}

          {mutation.isPending && (
            <div className="bg-background-surface border border-border-default rounded-xl p-16 text-center">
              <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <h2 className="font-bold text-text-primary mb-2">Running backtest...</h2>
              <p className="text-sm text-text-muted">
                Fetching historical data and simulating {symbols.length} symbols from {startDate} to {endDate}
              </p>
              <p className="text-xs text-text-muted mt-2">This takes 30-120 seconds</p>
            </div>
          )}

          {result && (
            <>
              {/* Live-ready badge */}
              {m && (
                <div className={`flex items-center gap-3 px-5 py-4 rounded-xl border ${
                  m.is_live_ready
                    ? 'bg-green/10 border-green/30'
                    : 'bg-red/10 border-red/30'
                }`}>
                  {m.is_live_ready
                    ? <CheckCircle size={20} className="text-green shrink-0" />
                    : <XCircle size={20} className="text-red shrink-0" />}
                  <div>
                    <div className={`font-bold text-sm ${m.is_live_ready ? 'text-green' : 'text-red'}`}>
                      {m.is_live_ready ? '✅ Strategy is LIVE READY' : '⚠ Strategy NOT ready for live trading'}
                    </div>
                    <div className="text-xs text-text-muted mt-0.5">
                      {m.is_live_ready
                        ? 'Profit factor ≥ 1.5, Calmar ≥ 0.5, Win rate ≥ 50% — meets all thresholds'
                        : `PF=${m.profit_factor.toFixed(2)}, Calmar=${m.calmar.toFixed(2)}, WR=${m.win_rate_pct.toFixed(1)}% — needs improvement`}
                    </div>
                  </div>
                  <div className="ml-auto text-right">
                    <div className={`text-2xl font-black font-mono ${m.total_return_pct >= 0 ? 'text-green' : 'text-red'}`}>
                      {pct(m.total_return_pct)}
                    </div>
                    <div className="text-[10px] text-text-muted">total return</div>
                  </div>
                </div>
              )}

              {/* Metrics grid */}
              {m && (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <MetricCard label="CAGR" value={pct(m.cagr_pct)}
                    color={m.cagr_pct >= 10 ? 'green' : m.cagr_pct >= 0 ? 'default' : 'red'}
                    icon={<TrendingUp size={14} />} />
                  <MetricCard label="Sharpe" value={fmt(m.sharpe)}
                    sub="monthly" color={m.sharpe >= 1 ? 'green' : m.sharpe >= 0 ? 'amber' : 'red'}
                    icon={<Zap size={14} />} />
                  <MetricCard label="Profit Factor" value={fmt(m.profit_factor)}
                    color={m.profit_factor >= 1.5 ? 'green' : m.profit_factor >= 1 ? 'amber' : 'red'}
                    icon={<Target size={14} />} />
                  <MetricCard label="Max Drawdown" value={`-${fmt(m.max_drawdown_pct)}%`}
                    color={m.max_drawdown_pct < 10 ? 'green' : m.max_drawdown_pct < 20 ? 'amber' : 'red'}
                    icon={<TrendingDown size={14} />} />
                  <MetricCard label="Win Rate" value={`${fmt(m.win_rate_pct, 1)}%`}
                    sub={`${m.winning_trades}W · ${m.losing_trades}L`}
                    color={m.win_rate_pct >= 55 ? 'green' : m.win_rate_pct >= 45 ? 'amber' : 'red'} />
                  <MetricCard label="Sortino" value={fmt(m.sortino)}
                    color={m.sortino >= 1 ? 'green' : 'default'} icon={<Shield size={14} />} />
                  <MetricCard label="Calmar" value={fmt(m.calmar)}
                    color={m.calmar >= 0.5 ? 'green' : 'amber'} />
                  <MetricCard label="Trades" value={`${m.total_trades}`}
                    sub={`avg W: +${fmt(m.avg_win_pct)}% L: ${fmt(m.avg_loss_pct)}%`}
                    icon={<Clock size={14} />} />
                </div>
              )}

              {/* Equity curve */}
              {result.equity_curve?.length > 0 && (
                <div className="bg-background-surface border border-border-default rounded-xl p-5">
                  <h3 className="font-bold text-text-primary text-sm mb-4">Equity Curve</h3>
                  <EquityCurve data={result.equity_curve} initial={capital} />
                </div>
              )}

              {/* Trade log */}
              {result.trades?.length > 0 && (
                <div className="bg-background-surface border border-border-default rounded-xl overflow-hidden">
                  <button onClick={() => setShowTrades(v => !v)}
                    className="w-full px-5 py-4 flex items-center justify-between hover:bg-background-elevated/30 transition-colors">
                    <h3 className="font-bold text-text-primary text-sm">
                      Trade Log
                      <span className="text-text-muted font-normal ml-2">
                        ({result.trade_count} trades{result.trade_count > 200 ? ', showing first 200' : ''})
                      </span>
                    </h3>
                    {showTrades ? <ChevronUp size={16} className="text-text-muted" /> : <ChevronDown size={16} className="text-text-muted" />}
                  </button>
                  {showTrades && (
                    <div className="overflow-x-auto max-h-80 overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-background-elevated/50 sticky top-0">
                          <tr>
                            {['Symbol','Entry','Exit','Entry ₹','Exit ₹','P&L','Exit Reason'].map(h => (
                              <th key={h} className="px-3 py-2 text-left text-[10px] font-bold text-text-muted uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border-default">
                          {result.trades.map((t, i) => (
                            <tr key={i} className="hover:bg-background-elevated/20">
                              <td className="px-3 py-2 font-bold text-text-primary">{t.symbol?.split(':')[1]}</td>
                              <td className="px-3 py-2 font-mono text-text-muted">{t.entry_date}</td>
                              <td className="px-3 py-2 font-mono text-text-muted">{t.exit_date}</td>
                              <td className="px-3 py-2 font-mono text-text-secondary">₹{t.entry_price?.toFixed(2)}</td>
                              <td className="px-3 py-2 font-mono text-text-secondary">₹{t.exit_price?.toFixed(2)}</td>
                              <td className={`px-3 py-2 font-mono font-bold ${t.pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>
                                {pct(t.pnl_pct || 0)}
                              </td>
                              <td className="px-3 py-2 text-text-muted capitalize">
                                {t.exit_reason?.replace(/_/g, ' ')}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Reset */}
              <div className="flex justify-end">
                <button onClick={() => { setResult(null); mutation.reset(); }}
                  className="flex items-center gap-2 text-xs text-text-muted hover:text-accent transition-colors">
                  <RotateCcw size={12} /> Reset
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Backtest;
