import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import { 
  TrendingUp, 
  Search, 
  Clock, 
  AlertTriangle, 
  CheckCircle, 
  Info,
  ChevronRight,
  Activity,
  ShoppingCart,
  X
} from 'lucide-react';
import { 
  getAssets, 
  getLatestSignal, 
  generateSignal, 
  explainSignal,
  openTrade,
  getWalletSummary,
  getMarketStatus,
  Asset,
  Signal,
  AssetsResponse
} from '../lib/api';
import { queryKeys } from '../lib/queryKeys';
import SignalBadge from '../components/SignalBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import CandlestickChart from '../components/CandlestickChart';

const Signals: React.FC = () => {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState<string>('All');
  const [explanation, setExplanation] = useState<string | null>(null);
  const [isExplaining, setIsExplaining] = useState(false);

  // Index definitions — symbols belonging to each NSE index
  const INDEX_FILTERS: Record<string, string[]> = {
    'All': [],
    'Nifty 50': [
      'NSE:RELIANCE','NSE:TCS','NSE:HDFCBANK','NSE:INFY','NSE:ICICIBANK',
      'NSE:SBIN','NSE:BHARTIARTL','NSE:ITC','NSE:KOTAKBANK','NSE:LT',
      'NSE:AXISBANK','NSE:WIPRO','NSE:ULTRACEMCO','NSE:SUNPHARMA','NSE:TITAN',
      'NSE:BAJFINANCE','NSE:NESTLEIND','NSE:POWERGRID','NSE:NTPC','NSE:MARUTI',
      'NSE:TATAMOTORS','NSE:TECHM','NSE:HCLTECH','NSE:ONGC','NSE:BPCL',
      'NSE:HINDALCO','NSE:GRASIM','NSE:ADANIENT','NSE:ADANIPORTS','NSE:COALINDIA',
    ],
    'Bank Nifty': [
      'NSE:HDFCBANK','NSE:ICICIBANK','NSE:SBIN','NSE:KOTAKBANK','NSE:AXISBANK',
      'NSE:INDUSINDBK','NSE:BANDHANBNK','NSE:FEDERALBNK','NSE:IDFCFIRSTB','NSE:PNB',
      'NSE:BANKBARODA','NSE:CANBK',
    ],
    'IT': [
      'NSE:TCS','NSE:INFY','NSE:WIPRO','NSE:HCLTECH','NSE:TECHM',
      'NSE:MPHASIS','NSE:LTTS','NSE:PERSISTENT','NSE:COFORGE','NSE:OFSS',
    ],
    'Pharma': [
      'NSE:SUNPHARMA','NSE:DRREDDY','NSE:CIPLA','NSE:DIVISLAB','NSE:BIOCON',
      'NSE:LUPIN','NSE:AUROPHARMA','NSE:ALKEM','NSE:TORNTPHARM','NSE:IPCALAB',
    ],
    'Auto': [
      'NSE:MARUTI','NSE:TATAMOTORS','NSE:M&M','NSE:BAJAJ-AUTO','NSE:HEROMOTOCO',
      'NSE:EICHERMOT','NSE:TVSMOTOR','NSE:ASHOKLEY','NSE:BALKRISIND','NSE:BOSCHLTD',
    ],
    'FMCG': [
      'NSE:ITC','NSE:HINDUNILVR','NSE:NESTLEIND','NSE:BRITANNIA','NSE:DABUR',
      'NSE:GODREJCP','NSE:MARICO','NSE:COLPAL','NSE:TATACONSUM','NSE:VBL',
    ],
  };

  // Fetch all assets
  const { data: assetsData, isLoading: isAssetsLoading } = useQuery<AssetsResponse>({
    queryKey: queryKeys.assets,
    queryFn: () => getAssets(),
  });

  // Auto-select asset when navigated from dashboard with a symbol
  // location.key changes on every navigation even to the same route
  useEffect(() => {
    const symbol = (location.state as { symbol?: string } | null)?.symbol;
    if (!symbol || !assetsData?.assets) return;
    const asset = assetsData.assets.find((a: Asset) => a.symbol === symbol);
    if (asset) {
      setSelectedAsset(asset);
      setExplanation(null);
    }
  }, [location.key, assetsData]);

  // Fetch latest signal for selected asset
  const { 
    data: signal, 
    isLoading: isSignalLoading,
  } = useQuery<Signal>({
    queryKey: queryKeys.signal(selectedAsset?.symbol || ''),
    queryFn: () => getLatestSignal(selectedAsset!.symbol),
    enabled: !!selectedAsset,
    retry: false,  // don't retry 404s
  });

  // Auto-generate signal if none exists for selected asset
  useEffect(() => {
    if (!selectedAsset || isSignalLoading || signal) return;
    // No signal in DB for this asset — auto-generate
    generateMutation.mutate(selectedAsset.symbol);
  }, [selectedAsset?.symbol, isSignalLoading, signal]);

  // Generate signal mutation
  const generateMutation = useMutation({
    mutationFn: (symbol: string) => generateSignal(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.signal(selectedAsset?.symbol || '') });
      setExplanation(null);
    },
  });

  // Open trade mutation
  const tradeMutation = useMutation({
    mutationFn: (signalId: string) => openTrade(signalId, selectedAsset!.symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.wallet });
    },
  });

  // Wallet for position sizing preview
  const { data: wallet } = useQuery({
    queryKey: queryKeys.wallet,
    queryFn: getWalletSummary,
  });

  // Market status
  const { data: marketStatus } = useQuery({
    queryKey: ['market-status'],
    queryFn: getMarketStatus,
    refetchInterval: 60 * 1000, // refresh every minute
  });

  // Explain signal mutation (manual trigger)
  const handleExplain = async (signalId: string) => {
    setIsExplaining(true);
    try {
      const res = await explainSignal(signalId);
      setExplanation(res.explanation);
    } catch (err) {
      console.error(err);
    } finally {
      setIsExplaining(false);
    }
  };

  const filteredAssets = assetsData?.assets.filter((asset: Asset) => {
    const matchesSearch = asset.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         asset.name.toLowerCase().includes(searchQuery.toLowerCase());
    const indexSymbols = INDEX_FILTERS[activeIndex];
    const matchesIndex = activeIndex === 'All' || indexSymbols.includes(asset.symbol);
    return matchesSearch && matchesIndex;
  });

  const ScoreBar = ({ label, value }: { label: string, value: number }) => {
    const isPositive = value >= 0;
    const percentage = Math.min(Math.abs(value) * 100, 100);
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-[11px] font-medium uppercase tracking-wider text-text-secondary">
          <span>{label}</span>
          <span className={isPositive ? 'text-green' : 'text-red'}>{value.toFixed(2)}</span>
        </div>
        <div className="h-1.5 w-full bg-background-elevated rounded-full overflow-hidden flex">
          <div className="w-1/2 flex justify-end bg-background-surface">
            {!isPositive && <div className="bg-red h-full rounded-l-full" style={{ width: `${percentage}%` }} />}
          </div>
          <div className="w-1/2 flex justify-start bg-background-surface">
            {isPositive && <div className="bg-green h-full rounded-r-full" style={{ width: `${percentage}%` }} />}
          </div>
        </div>
      </div>
    );
  };

  const TechnicalIndicator = ({ label, value }: { label: string, value: number | string | null }) => {
    let color = 'text-amber';
    if (label === 'RSI' && value !== null) {
      const rsi = Number(value);
      if (rsi > 70) color = 'text-red';
      else if (rsi < 30) color = 'text-green';
    }
    return (
      <div className="bg-background-elevated p-3 rounded-lg border border-border-default">
        <div className="text-[10px] text-text-muted uppercase font-bold mb-1">{label}</div>
        <div className={`text-sm font-mono font-bold ${color}`}>{value ?? 'N/A'}</div>
      </div>
    );
  };

  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden -m-8">
      {/* Left Panel: Asset List */}
      <aside className="w-[320px] bg-background-surface border-r border-border-default flex flex-col">
        <div className="p-4 space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" size={16} />
            <input 
              type="text" 
              placeholder="Search assets..." 
              className="w-full bg-background-primary border border-border-default rounded-lg py-2 pl-10 pr-4 text-sm focus:outline-none focus:border-accent transition-colors"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Index filter pills */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none">
            {Object.keys(INDEX_FILTERS).map(idx => (
              <button
                key={idx}
                onClick={() => setActiveIndex(idx)}
                className={`shrink-0 px-3 py-1.5 text-xs font-bold rounded-full border transition-all ${
                  activeIndex === idx
                    ? 'bg-accent text-background border-accent'
                    : 'bg-background-elevated text-text-muted border-border-default hover:border-accent/50 hover:text-text-primary'
                }`}
              >
                {idx}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {isAssetsLoading ? (
            <div className="p-8 text-center"><LoadingSpinner size="sm" /></div>
          ) : (
            <div className="divide-y divide-border-default">
              {filteredAssets?.map((asset: Asset) => (
                <button
                  key={asset.symbol}
                  onClick={() => {
                    setSelectedAsset(asset);
                    setExplanation(null);
                  }}
                  className={`w-full p-4 flex items-center justify-between hover:bg-background-elevated transition-all text-left border-l-2 ${
                    selectedAsset?.symbol === asset.symbol ? 'border-accent bg-background-elevated' : 'border-transparent'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="font-bold text-text-primary truncate">{asset.symbol}</div>
                    <div className="text-xs text-text-muted truncate">{asset.name}</div>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                    asset.asset_type === 'equity' ? 'bg-accent/10 text-accent' : 
                    asset.asset_type === 'crypto' ? 'bg-amber/10 text-amber' : 'bg-teal-500/10 text-teal-500'
                  }`}>
                    {asset.asset_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* Right Panel: Content Area */}
      <main className="flex-1 overflow-y-auto custom-scrollbar bg-background-primary">
        {!selectedAsset ? (
          <div className="h-full flex flex-col items-center justify-center text-text-muted space-y-4">
            <Activity size={48} className="opacity-20" />
            <p>Select an asset to view signals</p>
          </div>
        ) : (
          <div className="p-8 max-w-4xl mx-auto space-y-8">
            {/* Market Status Banner */}
            {marketStatus && !marketStatus.is_open && (
              <div className="bg-amber/10 border border-amber/30 rounded-xl px-4 py-3 flex items-center gap-3">
                <AlertTriangle size={16} className="text-amber shrink-0" />
                <div className="text-sm">
                  <span className="font-bold text-amber">Market Closed</span>
                  <span className="text-text-muted ml-2">{marketStatus.reason}</span>
                  {marketStatus.next_open && (
                    <span className="text-text-muted ml-2">· Opens: {marketStatus.next_open}</span>
                  )}
                </div>
              </div>
            )}

            {/* Asset Header */}
            <div className="flex justify-between items-center">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <h1 className="text-3xl font-bold">{selectedAsset.name}</h1>
                  <span className="bg-background-elevated px-2 py-1 rounded text-xs font-mono border border-border-default uppercase">{selectedAsset.exchange}</span>
                </div>
                <div className="text-text-secondary font-mono">{selectedAsset.symbol}</div>
              </div>
              
              <button
                onClick={() => generateMutation.mutate(selectedAsset.symbol)}
                disabled={generateMutation.isPending}
                className="bg-accent hover:bg-accent-hover disabled:bg-accent/50 text-white px-6 py-2.5 rounded-lg font-bold flex items-center gap-2 transition-all shadow-lg shadow-accent/20"
              >
                {generateMutation.isPending ? <LoadingSpinner size="sm" /> : <TrendingUp size={18} />}
                {generateMutation.isPending ? 'Generating...' : 'Generate Signal'}
              </button>
            </div>

            {/* Notifications */}
            {generateMutation.isSuccess && (
              <div className="bg-green/10 border border-green/20 text-green p-4 rounded-xl flex items-center gap-3">
                <CheckCircle size={18} />
                <span className="text-sm font-medium">New signal generated successfully!</span>
              </div>
            )}
            {generateMutation.isError && (
              <div className="bg-red/10 border border-red/20 text-red p-4 rounded-xl flex items-center gap-3">
                <AlertTriangle size={18} />
                <span className="text-sm font-medium">Failed to generate signal. Please try again.</span>
              </div>
            )}

            {/* Candlestick Chart */}
            <CandlestickChart
              symbol={selectedAsset.symbol}
              entryPrice={wallet?.open_positions.find(p => p.symbol === selectedAsset.symbol)?.entry_price}
              stopLoss={wallet?.open_positions.find(p => p.symbol === selectedAsset.symbol)?.stop_loss}
              takeProfit={wallet?.open_positions.find(p => p.symbol === selectedAsset.symbol)?.take_profit}
            />

            {/* Signal Display */}
            <div className="space-y-6">
              {isSignalLoading ? (
                <div className="py-20 flex justify-center"><LoadingSpinner size="lg" /></div>
              ) : signal ? (
                <div className="bg-background-surface border border-border-default rounded-2xl overflow-hidden">
                  <div className="p-8 space-y-8">
                    <div className="flex justify-between items-start">
                      <div className="space-y-4">
                        <SignalBadge action={signal.action} confidence={signal.confidence} />
                        <div className="flex gap-2">
                          <span className="bg-background-elevated text-accent text-[10px] font-bold uppercase tracking-tighter px-2 py-1 rounded border border-border-default">
                            {signal.market_regime}
                          </span>
                          {signal.is_intraday && (
                            <span className="bg-background-elevated text-text-primary text-[10px] font-bold uppercase tracking-tighter px-2 py-1 rounded border border-border-default">
                              Intraday
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-text-muted text-[10px] font-bold uppercase mb-1">Generated At</div>
                        <div className="text-sm font-mono flex items-center gap-2 text-text-secondary">
                          <Clock size={14} />
                          {new Date(signal.created_at).toLocaleString()}
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-4">
                        <h3 className="text-xs font-bold text-text-muted uppercase tracking-widest">Model Scores</h3>
                        <div className="space-y-4">
                          <ScoreBar label="RL Score" value={signal.rl_score} />
                          <ScoreBar label="Transformer Score" value={signal.transformer_score} />
                          <ScoreBar label="Sentiment Score" value={signal.sentiment_score} />
                          <ScoreBar label="Ensemble Score" value={signal.ensemble_score} />
                        </div>
                      </div>

                      <div className="space-y-4">
                        <h3 className="text-xs font-bold text-text-muted uppercase tracking-widest">Technical Indicators</h3>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                          <TechnicalIndicator label="RSI" value={signal.technical_indicators?.rsi_14 != null ? Number(signal.technical_indicators.rsi_14).toFixed(1) : 'N/A'} />
                          <TechnicalIndicator label="ADX" value={signal.technical_indicators?.adx != null ? Number(signal.technical_indicators.adx).toFixed(1) : 'N/A'} />
                          <TechnicalIndicator label="Vol Ratio" value={signal.technical_indicators?.volume_ratio != null ? Number(signal.technical_indicators.volume_ratio).toFixed(2) : 'N/A'} />
                          <TechnicalIndicator label="ATR %" value={signal.technical_indicators?.atr_pct != null ? (Number(signal.technical_indicators.atr_pct) * 100).toFixed(2) + '%' : 'N/A'} />
                        </div>
                      </div>
                    </div>

                    <div className="pt-4 border-t border-border-default space-y-4">
                      {/* Open Trade button — only show for BUY signals above 60% */}
                      {signal.action === 'buy' && signal.confidence >= 0.60 && !marketStatus?.is_open && (
                        <div className="bg-amber/5 border border-amber/20 rounded-xl p-3 flex items-center gap-2 text-xs text-amber">
                          <AlertTriangle size={14} />
                          Market is closed. Trading resumes {marketStatus?.next_open ?? 'next trading day'}.
                        </div>
                      )}

                      {signal.action === 'buy' && signal.confidence >= 0.60 && marketStatus?.is_open && (
                        <div className="bg-green/5 border border-green/20 rounded-xl p-4">
                          <div className="flex items-center justify-between mb-3">
                            <div>
                              <div className="font-bold text-text-primary text-sm">Execute Paper Trade</div>
                              <div className="text-xs text-text-muted mt-0.5">
                                Position size: {wallet ? `₹${Math.floor(wallet.cash_balance * 0.10).toLocaleString('en-IN')} (10% of ₹${wallet.cash_balance.toLocaleString('en-IN')})` : '10% of balance'}
                              </div>
                            </div>
                            <button
                              onClick={() => tradeMutation.mutate(signal.signal_id)}
                              disabled={tradeMutation.isPending || tradeMutation.isSuccess}
                              className="bg-green hover:bg-green/80 disabled:bg-green/40 text-white px-5 py-2 rounded-lg font-bold flex items-center gap-2 text-sm transition-all"
                            >
                              {tradeMutation.isPending ? <LoadingSpinner size="sm" /> : <ShoppingCart size={15} />}
                              {tradeMutation.isPending ? 'Opening...' : tradeMutation.isSuccess ? 'Opened ✓' : 'Open Trade'}
                            </button>
                          </div>
                          {tradeMutation.isSuccess && tradeMutation.data && (
                            <div className="text-xs text-green font-medium">
                              Trade opened: {(tradeMutation.data as any).quantity} shares @ ₹{(tradeMutation.data as any).entry_price?.toFixed(2)}
                              &nbsp;· Stop: ₹{(tradeMutation.data as any).stop_loss?.toFixed(2)}
                              &nbsp;· Target: ₹{(tradeMutation.data as any).take_profit?.toFixed(2)}
                            </div>
                          )}
                          {tradeMutation.isError && (
                            <div className="text-xs text-red font-medium flex items-center gap-1">
                              <X size={12} /> Failed to open trade — check wallet balance
                            </div>
                          )}
                        </div>
                      )}

                      <button 
                        onClick={() => handleExplain(signal.signal_id)}
                        disabled={isExplaining}
                        className="flex items-center gap-2 text-accent hover:text-accent-hover font-bold text-sm transition-colors"
                      >
                        {isExplaining ? <LoadingSpinner size="sm" /> : <Info size={16} />}
                        Explain Signal with AI
                      </button>

                      {explanation && (
                        <div className="mt-4 bg-background-elevated p-6 rounded-xl border border-border-default text-sm text-text-secondary leading-relaxed animate-in fade-in slide-in-from-top-2">
                          <div className="font-bold text-text-primary mb-2 flex items-center gap-2">
                            <ChevronRight size={14} className="text-accent" />
                            AI Insights
                          </div>
                          {explanation}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="py-20 text-center space-y-4 bg-background-surface border border-dashed border-border-default rounded-2xl">
                  <Clock className="mx-auto text-text-muted opacity-20" size={48} />
                  <div className="text-text-secondary font-medium">No signal generated yet for {selectedAsset.symbol}</div>
                  <button 
                    onClick={() => generateMutation.mutate(selectedAsset.symbol)}
                    className="text-accent font-bold hover:underline"
                  >
                    Generate First Signal
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default Signals;
