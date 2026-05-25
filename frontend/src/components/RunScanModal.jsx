import { useEffect, useRef, useState } from 'react';
import { Loader2, X, Zap } from 'lucide-react';
import { useRunScanMutation } from '../hooks/usePipeline';
import { PLATFORM_BADGES } from '../lib/platforms';
import { useToast } from './toast';

export function RunScanModal({ isOpen, onClose, onScanStarted }) {
  const [query, setQuery] = useState('');
  const { addToast } = useToast();
  const runScanMutation = useRunScanMutation();
  const inputRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    const timer = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(timer);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  const handleSubmit = (event) => {
    event.preventDefault();
    const nextQuery = query.trim();
    if (!nextQuery || runScanMutation.isPending) return;
    onScanStarted(nextQuery);
    runScanMutation.mutate(nextQuery, {
      onSuccess: () => {
        addToast('Scan started — opportunities will appear as they clear review.', 'success');
        setQuery('');
        onClose();
      },
      onError: (error) => {
        addToast(error.userMessage || 'Unable to start sourcing.', 'error');
      },
    });
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-xl"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <form
        onSubmit={handleSubmit}
        className="glass-panel w-full max-w-lg overflow-hidden border border-white/10 shadow-2xl modal-enter"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-strong)]">
              Source opportunities
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Describe a buyer signal or audience moment to monitor.
            </p>
          </div>
          <button type="button" onClick={onClose} className="icon-button" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div className="flex gap-2">
            {PLATFORM_BADGES.map((p) => (
              <span
                key={p.label}
                className="platform-scan-badge"
                style={{ '--pb-color': p.color }}
              >
                {p.label}
              </span>
            ))}
          </div>

          <div>
            <label htmlFor="scan-query" className="mb-2 block text-sm font-medium text-[var(--text)]">
              Intent signal
            </label>
            <textarea
              id="scan-query"
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Founders evaluating B2B analytics tools"
              className="field-input resize-none"
              rows={3}
              maxLength={280}
            />
            <div className="mt-1 flex items-center justify-between">
              <p className="text-xs text-[var(--text-faint)]">
                Be specific — narrow intent = higher quality matches
              </p>
              <span className={`text-xs ${query.length > 240 ? 'text-amber-400' : 'text-[var(--text-faint)]'}`}>
                {query.length}/280
              </span>
            </div>
          </div>

          {runScanMutation.isError && (
            <p className="rounded-lg border border-red-400/20 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {runScanMutation.error?.userMessage || 'Something went wrong. Please try again.'}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-white/10 bg-white/[0.03] px-5 py-4">
          <button type="button" onClick={onClose} className="button-secondary">Cancel</button>
          <button
            type="submit"
            disabled={!query.trim() || runScanMutation.isPending}
            className="button-primary"
          >
            {runScanMutation.isPending ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Zap size={15} />
            )}
            {runScanMutation.isPending ? 'Starting…' : 'Start scan'}
          </button>
        </div>
      </form>
    </div>
  );
}
