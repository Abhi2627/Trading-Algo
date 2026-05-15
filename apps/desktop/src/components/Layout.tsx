import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import {
LayoutDashboard,
TrendingUp,
Wallet,
MessageSquare,
Settings,
BarChart2,
FlaskConical,
  Circle
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { healthCheck } from '../lib/api';
import { queryKeys } from '../lib/queryKeys';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [currentTime, setCurrentTime] = useState(new Date());

  // Update time every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Health check every 30s
  const { data: health, isError } = useQuery({
    queryKey: queryKeys.health,
    queryFn: healthCheck,
    refetchInterval: 30000,
    retry: true,
  });

  const isConnected = !!health && !isError;

  const navLinks = [
    { to: '/',           icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/signals',    icon: TrendingUp,      label: 'Signals' },
    { to: '/portfolio',  icon: Wallet,           label: 'Portfolio' },
    { to: '/analytics',  icon: BarChart2,        label: 'Analytics' },
    { to: '/backtest',   icon: FlaskConical,     label: 'Backtest' },
    { to: '/chat',       icon: MessageSquare,    label: 'Chat' },
    { to: '/settings',   icon: Settings,         label: 'Settings' },
  ];

  const formattedTime = currentTime.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });

  return (
    <div className="flex h-screen bg-background-primary overflow-hidden">
      {/* Sidebar */}
      <aside className="w-[220px] flex-shrink-0 bg-background-surface border-r border-border-default flex flex-col">
        <div className="p-6">
          <h1 className="text-2xl font-bold text-accent">AlgoTrade</h1>
          <p className="text-xs text-text-muted uppercase tracking-wider">Paper Trading</p>
        </div>

        <nav className="flex-1 px-4 space-y-2">
          {navLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-accent text-white'
                    : 'text-text-secondary hover:text-text-primary hover:bg-background-elevated'
                }`
              }
            >
              <link.icon size={20} />
              <span className="font-medium">{link.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-border-default">
          <div className="flex items-center gap-2 px-4 py-2 bg-background-elevated rounded-lg">
            <Circle 
              size={8} 
              fill={isConnected ? '#22c55e' : '#ef4444'} 
              className={isConnected ? 'text-green' : 'text-red'} 
            />
            <span className="text-xs font-medium text-text-secondary">
              {isConnected ? 'API Connected' : 'API Disconnected'}
            </span>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 border-b border-border-default bg-background-surface flex items-center justify-end px-8">
          <div className="text-text-secondary font-mono text-sm">
            IST: {formattedTime}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {children}
        </div>
      </main>
    </div>
  );
};

export default Layout;
