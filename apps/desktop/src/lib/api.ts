import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: {
    'X-API-Key': import.meta.env.VITE_API_KEY,
    'Content-Type': 'application/json',
  },
});

// ---------------------------------------------------------------------------
// Response interfaces — must match FastAPI response shapes exactly
// ---------------------------------------------------------------------------

export interface Asset {
  symbol: string;
  name: string;
  exchange: string;
  asset_type: string;
  is_active: boolean;
}

export interface AssetsResponse {
  count: number;
  assets: Asset[];
}

export interface AssetPrice {
  symbol: string;
  name: string;
  price: number;
  currency: string;
}

export interface Signal {
  signal_id: string;
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  ensemble_score: number;
  rl_score: number;
  transformer_score: number;
  sentiment_score: number;
  market_regime: string;
  technical_indicators: Record<string, number | null>;
  is_intraday: boolean;
  created_at: string;
}

export interface SignalWithSymbol extends Signal {
  symbol: string; // injected client-side from the route param
}

export interface SignalHistoryResponse {
  symbol: string;
  count: number;
  signals: Signal[];
}

export interface Position {
  trade_id: string;
  symbol: string;
  name: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealised_pnl: number;
  pnl_pct: number;
  stop_loss: number;
  take_profit: number;
  trade_type: 'intraday' | 'positional';
  entry_time: string;
}

export interface DailyBudget {
  profit_target: number;
  loss_limit: number;
  loss_used_today: number;
  remaining_loss_budget: number;
}

export interface WalletSummary {
  cash_balance: number;
  invested_balance: number;
  unrealised_pnl: number;
  realised_pnl: number;
  total_equity: number;
  peak_equity: number;
  drawdown_pct: number;
  risk_mode: 'normal' | 'conservative' | 'halted';
  monthly_topup: number;
  intraday_allocation: number;
  positional_allocation: number;
  daily_budget: DailyBudget;
  open_positions: Position[];
  open_count: number;
}

export interface TradeResult {
  approved: boolean;
  reason?: string;
  trade_id?: string;
  symbol?: string;
  quantity?: number;
  entry_price?: number;
  position_size?: number;
  stop_loss?: number;
  take_profit?: number;
  cash_remaining?: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  reply: string;
  context_used: string;
  signal_id: string | null;
}

export interface ExplainResponse {
  signal_id: string;
  symbol: string;
  action: string;
  confidence: number;
  explanation: string;
  context: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const getAssets = async (assetType?: string): Promise<AssetsResponse> => {
  const { data } = await api.get<AssetsResponse>('/assets/', {
    params: assetType ? { asset_type: assetType } : {},
  });
  return data;
};

export const getAssetPrice = async (symbol: string): Promise<AssetPrice> => {
  const { data } = await api.get<AssetPrice>(`/assets/${encodeURIComponent(symbol)}/price`);
  return data;
};

export const generateSignal = async (
  symbol: string,
  headlines: string[] = [],
): Promise<Signal> => {
  const { data } = await api.post<Signal>(`/signals/generate/${encodeURIComponent(symbol)}`, headlines);
  return data;
};

export const getLatestSignal = async (symbol: string): Promise<Signal> => {
  const { data } = await api.get<Signal>(`/signals/latest/${encodeURIComponent(symbol)}`);
  return data;
};

export const getSignalHistory = async (
  symbol: string,
  limit = 20,
): Promise<SignalHistoryResponse> => {
  const { data } = await api.get<SignalHistoryResponse>(
    `/signals/history/${encodeURIComponent(symbol)}`,
    { params: { limit } },
  );
  return data;
};

export const getWalletSummary = async (): Promise<WalletSummary> => {
  const { data } = await api.get<WalletSummary>('/wallet/summary');
  return data;
};

export const openTrade = async (
  signalId: string,
  assetSymbol: string,
  isIntraday = false,
): Promise<TradeResult> => {
  const { data } = await api.post<TradeResult>('/wallet/trade/open', {
    signal_id: signalId,
    asset_symbol: assetSymbol,
    is_intraday: isIntraday,
  });
  return data;
};

export const closeTrade = async (
  tradeId: string,
  reason = 'manual',
): Promise<Record<string, unknown>> => {
  const { data } = await api.post('/wallet/trade/close', { trade_id: tradeId, reason });
  return data;
};

export const applyTopup = async (): Promise<Record<string, unknown>> => {
  const { data } = await api.post('/wallet/topup');
  return data;
};

export const chat = async (
  message: string,
  conversationHistory: ChatMessage[] = [],
): Promise<ChatResponse> => {
  const { data } = await api.post<ChatResponse>('/chat/', {
    message,
    conversation_history: conversationHistory,
  });
  return data;
};

export const explainSignal = async (signalId: string): Promise<ExplainResponse> => {
  const { data } = await api.get<ExplainResponse>(`/chat/explain/${signalId}`);
  return data;
};

export const healthCheck = async (): Promise<{ status: string; env: string }> => {
  const { data } = await api.get('/health');
  return data;
};

export default api;
