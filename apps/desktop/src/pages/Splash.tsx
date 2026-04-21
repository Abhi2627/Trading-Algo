import React, { useEffect, useState } from 'react';

const Splash: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => {
      setVisible(false);
      setTimeout(onDone, 400);
    }, 2000);
    return () => clearTimeout(t);
  }, [onDone]);

  return (
    <div className={`fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#0A0A0F] transition-opacity duration-400 ${visible ? 'opacity-100' : 'opacity-0'}`}>
      {/* Hex logo mark */}
      <svg width="120" height="120" viewBox="0 0 120 120">
        <polygon points="60,8 104,32 104,80 60,104 16,80 16,32"
          fill="#1E1B2E" stroke="#7C3AED" strokeWidth="1.5"/>
        {/* Candlesticks */}
        <rect x="34" y="56" width="7" height="20" fill="#EF4444" rx="1"/>
        <rect x="46" y="44" width="7" height="26" fill="#22C55E" rx="1"/>
        <rect x="58" y="38" width="7" height="30" fill="#22C55E" rx="1"/>
        <rect x="70" y="48" width="7" height="20" fill="#F59E0B" rx="1"/>
        <rect x="82" y="34" width="7" height="34" fill="#22C55E" rx="1"/>
        {/* Trend line */}
        <polyline points="37,62 49,55 61,50 73,54 85,42"
          fill="none" stroke="#7C3AED" strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round"/>
        {/* Corner dots */}
        {[[60,8],[104,32],[104,80],[60,104],[16,80],[16,32]].map(([x,y],i) => (
          <circle key={i} cx={x} cy={y} r="3" fill="#7C3AED"/>
        ))}
      </svg>

      <div className="mt-7 text-center">
        <h1 className="text-[34px] font-bold tracking-tight text-[#F8FAFC]">
          Algo<span className="text-[#7C3AED]">Trade</span>
        </h1>
        <p className="mt-2 text-[11px] font-medium tracking-[5px] text-[#64748B]">
          PAPER TRADING
        </p>
        <div className="mt-2 mx-auto w-16 h-0.5 rounded-full"
          style={{background: 'linear-gradient(90deg, #7C3AED, #22C55E)'}}/>
      </div>

      {/* Loading dots */}
      <div className="mt-12 flex gap-1.5">
        {[0,1,2].map(i => (
          <div key={i} className="w-1.5 h-1.5 rounded-full bg-[#7C3AED] opacity-60"
            style={{animation: `pulse 1s ${i * 0.2}s infinite`}}/>
        ))}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.2; transform: scale(0.8); }
          50%       { opacity: 1;   transform: scale(1.2); }
        }
      `}</style>
    </div>
  );
};

export default Splash;
