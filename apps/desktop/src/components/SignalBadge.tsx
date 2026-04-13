import React from 'react';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';

interface SignalBadgeProps {
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  size?: 'sm' | 'md';
}

const SignalBadge: React.FC<SignalBadgeProps> = ({ action, confidence, size = 'md' }) => {
  const isBuy = action === 'buy';
  const isSell = action === 'sell';
  const isHold = action === 'hold';

  const config = {
    buy: {
      bg: 'bg-green/10',
      text: 'text-green',
      icon: ArrowUpRight,
      label: 'BUY',
    },
    sell: {
      bg: 'bg-red/10',
      text: 'text-red',
      icon: ArrowDownRight,
      label: 'SELL',
    },
    hold: {
      bg: 'bg-amber/10',
      text: 'text-amber',
      icon: Minus,
      label: 'HOLD',
    },
  }[action];

  const Icon = config.icon;

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-3 py-1 text-xs';
  const iconSize = size === 'sm' ? 12 : 14;

  return (
    <div className={`inline-flex items-center gap-1.5 font-bold rounded-full border ${config.bg} ${config.text} border-current ${sizeClasses}`}>
      <Icon size={iconSize} strokeWidth={3} />
      <span>
        {config.label} {(confidence * 100).toFixed(0)}%
      </span>
    </div>
  );
};

export default SignalBadge;
