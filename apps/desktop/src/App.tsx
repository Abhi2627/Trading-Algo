import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import LoadingSpinner from './components/LoadingSpinner';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Signals   = lazy(() => import('./pages/Signals'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const Chat      = lazy(() => import('./pages/Chat'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const Settings: React.FC = () => (
  <div className="h-full flex items-center justify-center">
    <div className="text-center">
      <h2 className="text-2xl font-bold text-text-secondary mb-2">Settings</h2>
      <p className="text-text-muted text-sm">Coming soon</p>
    </div>
  </div>
);

const App: React.FC = () => {
  return (
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
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Suspense>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
