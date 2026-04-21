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
  Activity
} from 'lucide-react';
import { 
  getAssets, 
  getLatestSignal, 
  generateSignal, 
  explainSignal,
  Asset,
  Signal,
  AssetsResponse
} from '../lib/api';
import { queryKeys } from '../lib/queryKeys';
import SignalBadge from '../components/SignalBadge';
import LoadingSpinner from '../components/LoadingSpinner';

const Signals: React.FC = () => {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'All' | 'Equity' | 'Crypto' | 'Forex'>('All');
  const [explanation, setExplanation] = useState<string | null>(null);
  const [isExplaining, setIsExplaining] = useState(false);

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
  });

  // Generate signal mutation
  const generateMutation = useMutation({
    mutationFn: (symbol: string) => generateSignal(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.signal(selectedAsset?.symbol || '') });
      setExplanation(null);
    },
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
    const matchesTab = activeTab === 'All' || asset.asset_type.toLowerCase() === activeTab.toLowerCase();
    return matchesSearch && matchesTab;
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

          <div className="flex bg-background-primary p-1 rounded-lg border border-border-default">
            {(['All', 'Equity', 'Crypto', 'Forex'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${
                  activeTab === tab ? 'bg-background-elevated text-text-primary shadow-sm' : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {tab}
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

                    <div className="pt-4 border-t border-border-default">
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
