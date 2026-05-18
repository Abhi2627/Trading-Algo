import React from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  CheckCircle, XCircle, Clock, RefreshCw,
  Brain, Database, Calendar, AlertTriangle, Info
} from 'lucide-react';
import api from '../lib/api';

// ─── helpers ─────────────────────────────────────────────────────────────────

const fmt_date = (iso: string | undefined) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
    timeZone: 'Asia/Kolkata',
  }) + ' IST';
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="bg-background-surface border border-border-default rounded-xl p-6 space-y-4">
    <h2 className="font-bold text-text-primary text-sm uppercase tracking-wider">{title}</h2>
    {children}
  </div>
);

const Row: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-center justify-between py-2 border-b border-border-default last:border-0">
    <span className="text-sm text-text-muted">{label}</span>
    <span className="text-sm font-medium text-text-primary">{value}</span>
  </div>
);

// ─── retrain status card ──────────────────────────────────────────────────────

interface RetrainStatus {
  last_retrain: {
    success:       boolean;
    skipped?:      boolean;
    reason?:       string;
    samples_used?: number;
    files_updated?: string[];
    retrained_at?: string;
    run_at?:       string;
    finished_at?:  string;
    kernel_slug?:  string;
  } | null;
  message?: string;
}

const RetrainStatusCard: React.FC = () => {
  const { data, isLoading, refetch } = useQuery<RetrainStatus>({
    queryKey: ['retrain-status'],
    queryFn: async () => {
      const { data } = await api.get('/wallet/retrain/status');
      return data;
    },
    staleTime: 5 * 60 * 1000,
  });

  const trigger = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/wallet/retrain');
      return data;
    },
    onSuccess: () => setTimeout(() => refetch(), 2000),
  });

  const r = data?.last_retrain;

  const statusColor = !r ? 'text-text-muted'
    : r.skipped ? 'text-amber'
    : r.success  ? 'text-green'
    : 'text-red';

  const StatusIcon = !r ? Clock
    : r.skipped ? AlertTriangle
    : r.success  ? CheckCircle
    : XCircle;

  const statusText = !r ? 'Never run'
    : r.skipped ? `Skipped — ${r.reason?.replace(/_/g, ' ')}`
    : r.success  ? 'Completed successfully'
    : `Failed — ${r.reason?.replace(/_/g, ' ')}`;

  return (
    <Section title="ML Model Retraining">
      {/* Status banner */}
      <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${
        !r ? 'bg-background-elevated border-border-default'
        : r.skipped ? 'bg-amber/10 border-amber/30'
        : r.success  ? 'bg-green/10 border-green/30'
        : 'bg-red/10 border-red/30'
      }`}>
        <StatusIcon size={18} className={statusColor} />
        <div className="flex-1">
          <div className={`text-sm font-bold ${statusColor}`}>{statusText}</div>
          {r?.run_at && (
            <div className="text-xs text-text-muted mt-0.5">
              Started {fmt_date(r.run_at)}
              {r.finished_at && ` · Finished ${fmt_date(r.finished_at)}`}
            </div>
          )}
        </div>
        <button onClick={() => refetch()}
          className="text-text-muted hover:text-accent transition-colors">
          <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Details */}
      {r && !r.skipped && (
        <div className="space-y-0">
          {r.samples_used !== undefined && (
            <Row label="Samples used" value={
              <span className="flex items-center gap-1.5">
                <Database size={13} className="text-accent" />
                {r.samples_used} signal outcomes
              </span>
            } />
          )}
          {r.retrained_at && (
            <Row label="Retrained on" value={
              <span className="flex items-center gap-1.5">
                <Calendar size={13} className="text-accent" />
                {r.retrained_at}
              </span>
            } />
          )}
          {r.files_updated && r.files_updated.length > 0 && (
            <Row label="Files updated" value={
              <span className="text-green font-mono text-xs">
                {r.files_updated.join(', ')}
              </span>
            } />
          )}
          {r.kernel_slug && (
            <Row label="Kaggle notebook" value={
              <span className="font-mono text-xs text-text-muted">{r.kernel_slug}</span>
            } />
          )}
        </div>
      )}

      {/* Schedule info */}
      <div className="flex items-start gap-2 px-3 py-2.5 bg-background-elevated rounded-lg">
        <Info size={13} className="text-text-muted mt-0.5 shrink-0" />
        <p className="text-xs text-text-muted">
          Retraining runs automatically every <strong className="text-text-secondary">Sunday at 8 PM IST</strong>.
          Requires minimum 10 closed signal outcomes. You can also trigger manually below.
        </p>
      </div>

      {/* Manual trigger */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-text-primary">Manual retrain</p>
          <p className="text-xs text-text-muted">Trigger now — takes up to 2 hours</p>
        </div>
        <button
          onClick={() => trigger.mutate()}
          disabled={trigger.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-accent text-background
            font-bold text-xs rounded-lg hover:bg-accent/90 disabled:opacity-50
            disabled:cursor-not-allowed transition-all"
        >
          {trigger.isPending
            ? <><RefreshCw size={13} className="animate-spin" /> Queuing...</>
            : <><Brain size={13} /> Retrain Now</>}
        </button>
      </div>

      {trigger.isSuccess && (
        <p className="text-xs text-green text-center">
          ✅ Retrain queued — check back in ~2 hours. Status will update automatically.
        </p>
      )}
      {trigger.isError && (
        <p className="text-xs text-red text-center">
          Failed to queue retrain — check server logs.
        </p>
      )}
    </Section>
  );
};

// ─── main settings page ───────────────────────────────────────────────────────

const Settings: React.FC = () => {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
        <p className="text-sm text-text-muted mt-1">System configuration and model management</p>
      </div>

      <RetrainStatusCard />

      <Section title="Strategy Parameters">
        <div className="space-y-0">
          <Row label="Min confidence threshold" value="70%" />
          <Row label="ATR stop-loss multiplier" value="2.0x (PSU banks: 2.5x)" />
          <Row label="ATR take-profit multiplier" value="4.0x (PSU banks: 5.0x)" />
          <Row label="Time exit (flat positions)" value="7 days" />
          <Row label="Max portfolio heat" value="20%" />
          <Row label="Max single position" value="30% (PSU banks: 15%)" />
          <Row label="Max sector exposure" value="40%" />
          <Row label="Kelly fraction" value="Half-Kelly (50%)" />
        </div>
        <p className="text-xs text-text-muted">
          Parameters are auto-tuned weekly based on signal outcomes.
          Requires 15+ closed trades to activate auto-tuning.
        </p>
      </Section>

      <Section title="Schedule">
        <div className="space-y-0">
          <Row label="Morning signal scan" value="8:30 AM IST, Mon–Fri" />
          <Row label="Auto-execute trades" value="After morning scan" />
          <Row label="Real-time monitor (30s)" value="9:15 AM – 3:30 PM IST" />
          <Row label="Intraday scans" value="9:20 AM, 11:00 AM, 1:00 PM IST" />
          <Row label="Intraday force-close" value="3:15 PM IST" />
          <Row label="Evening report" value="3:30 PM IST" />
          <Row label="Weekly report" value="Sunday 7:00 PM IST" />
          <Row label="Model retraining" value="Sunday 8:00 PM IST" />
          <Row label="Monthly top-up" value="1st of each month, 9:00 AM IST" />
        </div>
      </Section>

      <Section title="System">
        <div className="space-y-0">
          <Row label="Backend" value="FastAPI + PostgreSQL + Redis" />
          <Row label="Task scheduler" value="Celery Beat" />
          <Row label="Signal models" value="RL + Transformer + Groq Sentiment" />
          <Row label="Data source" value="NSE India API + yfinance" />
          <Row label="ML training" value="Kaggle (weekly)" />
          <Row label="Server" value="DigitalOcean BLR1" />
        </div>
      </Section>
    </div>
  );
};

export default Settings;
