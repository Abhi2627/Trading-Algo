export const queryKeys = {
  assets: ['assets'] as const,
  assetPrice: (symbol: string) => ['assets', symbol, 'price'] as const,
  assetFeatures: (symbol: string) => ['assets', symbol, 'features'] as const,
  signal: (symbol: string) => ['signals', symbol, 'latest'] as const,
  signalHistory: (symbol: string) => ['signals', symbol, 'history'] as const,
  wallet: ['wallet', 'summary'] as const,
  health: ['health'] as const,
};
