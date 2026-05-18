import { Moon, Sun, Zap } from 'lucide-react';

export function TopHeader({
  isLight,
  onToggleTheme,
  onOpenScan,
  searchTerm,
  onSearchChange,
  sourceRunning,
}) {
  return (
    <header className="top-header">
      <label className="search-shell">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--text-faint)] shrink-0"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        <input
          value={searchTerm}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search opportunities…"
          className="min-w-0 flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-faint)]"
        />
      </label>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleTheme}
          className="icon-button"
          aria-label="Toggle theme"
        >
          {isLight ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <button
          type="button"
          onClick={onOpenScan}
          disabled={sourceRunning}
          className="button-primary run-scan-btn"
          id="run-scan-button"
        >
          {sourceRunning ? (
            <>
              <span className="live-dot" />
              Scanning…
            </>
          ) : (
            <>
              <Zap size={15} />
              Run Scan
            </>
          )}
        </button>
      </div>
    </header>
  );
}
