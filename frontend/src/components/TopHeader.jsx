import { Moon, Play, Search, Sun } from 'lucide-react';

export function TopHeader({
  isLight,
  onToggleTheme,
  onOpenScan,
  searchTerm,
  onSearchChange,
  scanRunning,
}) {
  return (
    <header className="top-header">
      <label className="search-shell">
        <Search size={17} className="text-[var(--text-faint)]" />
        <input
          value={searchTerm}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search current results"
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
          disabled={scanRunning}
          className="button-primary"
        >
          <Play size={16} />
          {scanRunning ? 'Scanning' : 'Run Scan'}
        </button>
      </div>
    </header>
  );
}
