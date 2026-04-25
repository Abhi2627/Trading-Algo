import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getOHLCV, Candle } from '../lib/api';
import { TrendingUp, TrendingDown, BarChart2 } from 'lucide-react';

interface Props {
  symbol: string;
  entryPrice?: number;  // show entry line if trade open
  stopLoss?:   number;
  takeProfit?: number;
}

const PERIODS = [
  { label: '1M',  days: 30  },
  { label: '3M',  days: 90  },
  { label: '6M',  days: 180 },
  { label: '1Y',  days: 365 },
];

const CandlestickChart: React.FC<Props> = ({ symbol, entryPrice, stopLoss, takeProfit }) => {
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const [period, setPeriod] = useState(90);
  const [tooltip, setTooltip] = useState<{ candle: Candle; x: number; y: number } | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['ohlcv', symbol, period],
    queryFn:  () => getOHLCV(symbol, period),
    staleTime: 5 * 60 * 1000,  // 5 min cache
  });

  const candles = data?.candles ?? [];

  // Latest price info
  const latest   = candles[candles.length - 1];
  const prev     = candles[candles.length - 2];
  const change   = latest && prev ? latest.close - prev.close : 0;
  const changePct = prev ? (change / prev.close) * 100 : 0;
  const isUp     = change >= 0;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || candles.length === 0) return;

    const ctx    = canvas.getContext('2d')!;
    const dpr    = window.devicePixelRatio || 1;
    const rect   = canvas.getBoundingClientRect();
    canvas.width  = rect.width  * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const W  = rect.width;
    const H  = rect.height;
    const PAD_TOP    = 20;
    const PAD_BOTTOM = 30;
    const PAD_LEFT   = 60;
    const PAD_RIGHT  = 16;
    const chartW = W - PAD_LEFT - PAD_RIGHT;
    const chartH = H - PAD_TOP - PAD_BOTTOM;

    // Price range
    const highs  = candles.map(c => c.high);
    const lows   = candles.map(c => c.low);
    const maxP   = Math.max(...highs);
    const minP   = Math.min(...lows);
    const range  = maxP - minP || 1;
    const pad    = range * 0.05;
    const priceH = maxP + pad;
    const priceL = minP - pad;
    const priceRange = priceH - priceL;

    const xScale = (i: number) => PAD_LEFT + (i / (candles.length - 1)) * chartW;
    const yScale = (p: number) => PAD_TOP + ((priceH - p) / priceRange) * chartH;

    // Background
    ctx.fillStyle = '#0A0A0F';
    ctx.fillRect(0, 0, W, H);

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth   = 1;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
      const y = PAD_TOP + (i / gridLines) * chartH;
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(W - PAD_RIGHT, y);
      ctx.stroke();

      // Price label
      const price = priceH - (i / gridLines) * priceRange;
      ctx.fillStyle   = 'rgba(255,255,255,0.4)';
      ctx.font        = '10px system-ui';
      ctx.textAlign   = 'right';
      ctx.fillText(`₹${price.toFixed(0)}`, PAD_LEFT - 6, y + 4);
    }

    // Entry / Stop / Target lines
    const drawHLine = (price: number, color: string, label: string, dashed = true) => {
      if (price < priceL || price > priceH) return;
      const y = yScale(price);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth   = 1;
      if (dashed) ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(W - PAD_RIGHT, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle  = color;
      ctx.font       = 'bold 9px system-ui';
      ctx.textAlign  = 'left';
      ctx.fillText(label, PAD_LEFT + 4, y - 3);
      ctx.restore();
    };

    if (entryPrice) drawHLine(entryPrice, '#7C3AED', `Entry ₹${entryPrice}`);
    if (stopLoss)   drawHLine(stopLoss,   '#EF4444', `SL ₹${stopLoss}`);
    if (takeProfit) drawHLine(takeProfit, '#22C55E', `TP ₹${takeProfit}`);

    // Candlesticks
    const candleW = Math.max(2, Math.min(12, chartW / candles.length - 1));

    candles.forEach((c, i) => {
      const x      = xScale(i);
      const openY  = yScale(c.open);
      const closeY = yScale(c.close);
      const highY  = yScale(c.high);
      const lowY   = yScale(c.low);
      const bullish = c.close >= c.open;
      const color   = bullish ? '#22C55E' : '#EF4444';

      // Wick
      ctx.strokeStyle = color;
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();

      // Body
      const bodyTop = Math.min(openY, closeY);
      const bodyH   = Math.max(1, Math.abs(closeY - openY));
      ctx.fillStyle = bullish ? '#22C55E' : '#EF4444';
      ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
    });

    // X-axis date labels (every ~15 candles)
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font      = '9px system-ui';
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(candles.length / 6));
    candles.forEach((c, i) => {
      if (i % step === 0) {
        const x = xScale(i);
        const d = new Date(c.date);
        ctx.fillText(
          d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
          x, H - 8,
        );
      }
    });

  }, [candles, entryPrice, stopLoss, takeProfit]);

  // Tooltip on mouse move
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (candles.length === 0) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    const x    = e.clientX - rect.left;
    const PAD_LEFT  = 60;
    const PAD_RIGHT = 16;
    const chartW    = rect.width - PAD_LEFT - PAD_RIGHT;
    const idx = Math.round(((x - PAD_LEFT) / chartW) * (candles.length - 1));
    if (idx >= 0 && idx < candles.length) {
      setTooltip({ candle: candles[idx], x: e.clientX, y: e.clientY });
    }
  };

  if (isLoading) return (
    <div className="flex items-center justify-center h-48 text-text-muted text-sm">
      <BarChart2 size={20} className="mr-2 animate-pulse" /> Loading chart...
    </div>
  );

  if (isError || candles.length === 0) return (
    <div className="flex items-center justify-center h-48 text-text-muted text-sm">
      Chart data unavailable
    </div>
  );

  return (
    <div className="bg-surface-card rounded-xl border border-border-default overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
        <div className="flex items-center gap-3">
          <span className="font-bold text-text-primary">{symbol.split(':')[1]}</span>
          {latest && (
            <>
              <span className="font-mono text-lg font-bold text-text-primary">
                ₹{latest.close.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
              <span className={`flex items-center gap-1 text-sm font-semibold ${
                isUp ? 'text-green' : 'text-red'
              }`}>
                {isUp ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {isUp ? '+' : ''}{change.toFixed(2)} ({changePct.toFixed(2)}%)
              </span>
            </>
          )}
        </div>

        {/* Period selector */}
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button
              key={p.days}
              onClick={() => setPeriod(p.days)}
              className={`px-2 py-1 rounded text-xs font-semibold transition-all ${
                period === p.days
                  ? 'bg-accent text-white'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Canvas */}
      <div className="relative">
        <canvas
          ref={canvasRef}
          className="w-full"
          style={{ height: 280 }}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setTooltip(null)}
        />

        {/* Tooltip */}
        {tooltip && (
          <div
            className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded-lg p-2 text-xs shadow-xl"
            style={{ left: tooltip.x + 12, top: tooltip.y - 60 }}
          >
            <div className="font-semibold text-text-primary mb-1">
              {new Date(tooltip.candle.date).toLocaleDateString('en-IN', {
                day: 'numeric', month: 'short', year: 'numeric'
              })}
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-text-muted">
              <span>O</span><span className="text-text-primary font-mono">₹{tooltip.candle.open.toFixed(2)}</span>
              <span>H</span><span className="text-green font-mono">₹{tooltip.candle.high.toFixed(2)}</span>
              <span>L</span><span className="text-red font-mono">₹{tooltip.candle.low.toFixed(2)}</span>
              <span>C</span><span className="font-mono" style={{ color: tooltip.candle.close >= tooltip.candle.open ? '#22C55E' : '#EF4444' }}>
                ₹{tooltip.candle.close.toFixed(2)}
              </span>
              <span>Vol</span><span className="text-text-primary font-mono">{(tooltip.candle.volume / 1e6).toFixed(2)}M</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CandlestickChart;
