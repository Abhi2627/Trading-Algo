import React, { Suspense, lazy, useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import LoadingSpinner from './components/LoadingSpinner';
import Splash from './pages/Splash';
import { healthCheck } from './lib/api';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Signals   = lazy(() => import('./pages/Signals'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const Chat      = lazy(() => import('./pages/Chat'));
const Analytics = lazy(() => import('./pages/Analytics'));
const Backtest  = lazy(() => import('./pages/Backtest'));
const Settings  = lazy(() => import('./pages/Settings'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      refetchOnReconnect:   true,
      retry:                1,
      retryDelay:           3000,
      staleTime:            2 * 60 * 1000,   // 2 min default
      gcTime:               10 * 60 * 1000,  // keep cache 10 min
    },
  },
});

const Settings: React.FC = () => {
  const [serverUrl, setServerUrl] = useState(
    import.meta.env.VITE_API_URL || 'http://139.59.23.105:8000'
  );
  const [apiKey, setApiKey] = useState(
    import.meta.env.VITE_API_KEY || 'abhay-algotrade-2025'
  );
  const [status, setStatus] = useState<'idle' | 'checking' | 'ok' | 'error'>('idle');

  const testConnection = async () => {
    setStatus('checking');
    try {
      const res = await healthCheck();
      setStatus(res.status === 'ok' ? 'ok' : 'error');
    } catch {
      setStatus('error');
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-text-primary mb-1">Settings</h1>
        <p className="text-text-muted text-sm">Configure your AlgoTrade connection</p>
      </div>

      {/* Server Config */}
      <div className="bg-background-surface border border-border-default rounded-2xl p-6 space-y-4">
        <h2 className="font-bold text-text-primary">Server Connection</h2>

        <div>
          <label className="text-xs font-bold text-text-muted uppercase tracking-wider block mb-2">
            Backend URL
          </label>
          <input
            type="text"
            value={serverUrl}
            onChange={e => setServerUrl(e.target.value)}
            className="w-full bg-background-primary border border-border-default rounded-lg px-4 py-2.5 text-sm font-mono focus:outline-none focus:border-accent transition-colors"
            placeholder="http://139.59.23.105:8000"
          />
        </div>

        <div>
          <label className="text-xs font-bold text-text-muted uppercase tracking-wider block mb-2">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            className="w-full bg-background-primary border border-border-default rounded-lg px-4 py-2.5 text-sm font-mono focus:outline-none focus:border-accent transition-colors"
            placeholder="your-api-key"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={testConnection}
            disabled={status === 'checking'}
            className="bg-accent hover:bg-accent-hover disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-bold transition-all"
          >
            {status === 'checking' ? 'Testing...' : 'Test Connection'}
          </button>

          {status === 'ok' && (
            <span className="text-green text-sm font-bold">✅ Connected</span>
          )}
          {status === 'error' && (
            <span className="text-red text-sm font-bold">❌ Connection failed</span>
          )}
        </div>
      </div>

      {/* System Info */}
      <div className="bg-background-surface border border-border-default rounded-2xl p-6 space-y-3">
        <h2 className="font-bold text-text-primary">System Info</h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-background-primary rounded-lg p-3">
            <div className="text-text-muted text-xs uppercase font-bold mb-1">Server</div>
            <div className="font-mono text-text-primary text-xs">139.59.23.105</div>
          </div>
          <div className="bg-background-primary rounded-lg p-3">
            <div className="text-text-muted text-xs uppercase font-bold mb-1">Region</div>
            <div className="font-mono text-text-primary text-xs">Bangalore, India</div>
          </div>
          <div className="bg-background-primary rounded-lg p-3">
            <div className="text-text-muted text-xs uppercase font-bold mb-1">ML Models</div>
            <div className="font-mono text-text-primary text-xs">RL + Transformer + Sentiment</div>
          </div>
          <div className="bg-background-primary rounded-lg p-3">
            <div className="text-text-muted text-xs uppercase font-bold mb-1">Starting Capital</div>
            <div className="font-mono text-text-primary text-xs">₹2,000</div>
          </div>
        </div>
      </div>

      {/* Emergency */}
      <div className="bg-red/5 border border-red/20 rounded-2xl p-6 space-y-3">
        <h2 className="font-bold text-red">Emergency</h2>
        <p className="text-sm text-text-muted">
          Need money urgently? The emergency liquidation feature sells your lowest-performing
          stocks first to raise cash quickly.
        </p>
        <a
          href="#"
          className="text-red text-sm font-bold hover:underline"
          onClick={e => {
            e.preventDefault();
            window.open(`${serverUrl}/docs#/emergency`, '_blank');
          }}
        >
          View Emergency API →
        </a>
      </div>
    </div>
  );
};

const App: React.FC = () => {
  const [ready, setReady] = useState(false);

  return (
    <>
      {!ready ? (
        <Splash onDone={() => setReady(true)} />
      ) : (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Layout>
              <Suspense fallback={
                <div className="h-full flex items-center justify-center">
                  <LoadingSpinner size="lg" />
                </div>
              }>
                <Routes>
                  <Route path="/"          element={<Dashboard />} />
                  <Route path="/signals"   element={<Signals />} />
                  <Route path="/portfolio" element={<Portfolio />} />
                  <Route path="/chat"      element={<Chat />} />
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/backtest"  element={<Backtest />} />
                  <Route path="/settings"  element={<Settings />} />
                </Routes>
              </Suspense>
            </Layout>
          </BrowserRouter>
        </QueryClientProvider>
      )}
    </>
  );
};

export default App;