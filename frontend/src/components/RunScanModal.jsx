import { useState } from 'react';
import { Loader2, Play, X } from 'lucide-react';
import { useRunScanMutation } from '../hooks/usePipeline';
import { useToast } from './toast';

export function RunScanModal({ isOpen, onClose, onScanStarted }) {
  const [query, setQuery] = useState('');
  const { addToast } = useToast();
  const runScanMutation = useRunScanMutation();

  const handleSubmit = (event) => {
    event.preventDefault();
    const nextQuery = query.trim();
    if (!nextQuery || runScanMutation.isPending) return;

    onScanStarted(nextQuery);
    runScanMutation.mutate(nextQuery, {
      onSuccess: () => {
        addToast('Scan started. New opportunities will appear here.', 'success');
        setQuery('');
        onClose();
      },
      onError: (error) => {
        addToast(error.userMessage || 'Unable to start scan.', 'error');
      },
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-xl">
      <form
        onSubmit={handleSubmit}
        className="glass-panel w-full max-w-lg overflow-hidden border border-white/10 shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-strong)]">Run scan</h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Search intent across the connected sources.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="icon-button"
            aria-label="Close scan dialog"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 px-5 py-5">
          <label htmlFor="scan-query" className="text-sm font-medium text-[var(--text)]">
            Query
          </label>
          <input
            id="scan-query"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="What should SignalForge look for?"
            className="field-input"
          />
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-white/10 bg-white/[0.03] px-5 py-4">
          <button type="button" onClick={onClose} className="button-secondary">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!query.trim() || runScanMutation.isPending}
            className="button-primary"
          >
            {runScanMutation.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Play size={16} />
            )}
            Run scan
          </button>
        </div>
      </form>
    </div>
  );
}
