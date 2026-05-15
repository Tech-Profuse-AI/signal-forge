import { API_BASE_URL } from '../api/http';

export function DeveloperMode({ opportunities, metrics, pipelineStatus }) {
  const normalizedSnapshot = {
    apiBaseUrl: API_BASE_URL,
    pipelineStatus,
    metrics,
    normalizedOpportunitySample: opportunities.slice(0, 3),
  };

  return (
    <div className="space-y-5">
      <div>
        <p className="eyebrow">Developer Mode</p>
        <h1 className="mt-1 text-2xl font-semibold text-[var(--text-strong)]">
          Integration diagnostics
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
          Technical state is isolated here so the publishing workflow stays clean.
        </p>
      </div>

      <section className="glass-panel border border-white/10 p-5">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <p className="text-xs uppercase text-[var(--text-faint)]">
              API base
            </p>
            <p className="mt-2 break-all text-sm text-[var(--text-strong)]">{API_BASE_URL}</p>
          </div>
          <div>
            <p className="text-xs uppercase text-[var(--text-faint)]">
              Scan
            </p>
            <p className="mt-2 text-sm text-[var(--text-strong)]">
              {pipelineStatus?.running ? 'Running' : 'Idle'}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase text-[var(--text-faint)]">
              Queue
            </p>
            <p className="mt-2 text-sm text-[var(--text-strong)]">
              {opportunities.length} normalized items
            </p>
          </div>
        </div>
      </section>

      <section className="glass-panel border border-white/10 p-5">
        <h2 className="text-sm font-semibold text-[var(--text-strong)]">Normalized snapshot</h2>
        <pre className="mt-4 max-h-[520px] overflow-auto rounded-lg border border-white/10 bg-black/30 p-4 text-xs leading-5 text-slate-200">
          {JSON.stringify(normalizedSnapshot, null, 2)}
        </pre>
      </section>
    </div>
  );
}
