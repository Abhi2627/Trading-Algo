import React, { ReactNode } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface StatCardProps {
  label: string;
  value: string | number;
  subValue?: string | number;
  trend?: 'up' | 'down' | 'neutral';
  icon?: ReactNode;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, subValue, trend, icon }) => {
  return (
    <div className="bg-background-surface border border-border-default rounded-xl p-5 hover:border-border-subtle transition-colors">
      <div className="flex justify-between items-start mb-4">
        <span className="text-text-muted text-sm font-medium uppercase tracking-wider">{label}</span>
        {icon && <div className="text-text-muted">{icon}</div>}
      </div>
      
      <div className="flex items-baseline gap-2">
        <h3 className="text-2xl font-bold text-text-primary tracking-tight">{value}</h3>
        {trend && (
          <div className={`flex items-center text-xs font-bold ${
            trend === 'up' ? 'text-green' : trend === 'down' ? 'text-red' : 'text-text-muted'
          }`}>
            {trend === 'up' && <TrendingUp size={14} className="mr-0.5" />}
            {trend === 'down' && <TrendingDown size={14} className="mr-0.5" />}
            {trend === 'neutral' && <Minus size={14} className="mr-0.5" />}
          </div>
        )}
      </div>

      {subValue && (
        <div className="mt-1 text-sm text-text-secondary font-medium">
          {subValue}
        </div>
      )}
    </div>
  );
};

export default StatCard;
