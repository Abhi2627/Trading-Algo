import React, { Suspense, lazy, useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import LoadingSpinner from './components/LoadingSpinner';
import Splash from './pages/Splash';


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