import { AlertCircle, Loader2, SearchX } from 'lucide-react';
import { OpportunityCard } from './OpportunityCard';

export function OpportunityFeed({
  title,
  subtitle,
  opportunities,
  visibleOpportunities,
  platformFilter,
  onPlatformFilterChange,
  sortOrder,
  onSortOrderChange,
  isLoading,
  isError,
  error,
  onRetry,
}) {
  return (
    <div className="feed-shell">
      <div className="feed-header flex-col md:flex-row items-start md:items-end gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-[var(--text-strong)]">{title}</h1>
          {subtitle && (
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
              {subtitle}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 border border-[var(--border)] rounded-lg p-1 bg-[var(--surface-soft)]">
            <button
              type="button"
              onClick={() => onPlatformFilterChange('all')}
              className={`filter-toggle ${platformFilter === 'all' ? 'active' : ''}`}
            >
              All
            </button>
            <button
              type="button"
              onClick={() => onPlatformFilterChange('reddit')}
              className={`filter-toggle ${platformFilter === 'reddit' ? 'active' : ''}`}
            >
              Reddit
            </button>
            <button
              type="button"
              onClick={() => onPlatformFilterChange('quora')}
              className={`filter-toggle ${platformFilter === 'quora' ? 'active' : ''}`}
            >
              Quora
            </button>
            <button
              type="button"
              onClick={() => onPlatformFilterChange('medium')}
              className={`filter-toggle ${platformFilter === 'medium' ? 'active' : ''}`}
            >
              Medium
            </button>
          </div>

          <div className="flex items-center gap-1 border border-[var(--border)] rounded-lg p-1 bg-[var(--surface-soft)]">
            <button
              type="button"
              onClick={() => onSortOrderChange('newest')}
              className={`filter-toggle ${sortOrder === 'newest' ? 'active' : ''}`}
            >
              Newest
            </button>
            <button
              type="button"
              onClick={() => onSortOrderChange('oldest')}
              className={`filter-toggle ${sortOrder === 'oldest' ? 'active' : ''}`}
            >
              Oldest
            </button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[0, 1, 2].map((item) => (
            <div key={item} className="opportunity-card">
              <div className="skeleton-line h-4 w-1/4" />
              <div className="mt-5 space-y-3">
                <div className="skeleton-line h-7 w-3/4" />
                <div className="skeleton-line h-4 w-full" />
                <div className="skeleton-line h-32 w-full" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="empty-panel">
          <AlertCircle size={24} className="text-red-300" />
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-[var(--text-strong)]">
              Could not load opportunities
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {error?.userMessage || error?.message || 'The backend request failed.'}
            </p>
          </div>
          <button type="button" onClick={onRetry} className="button-secondary">
            <Loader2 size={15} />
            Retry
          </button>
        </div>
      ) : opportunities.length === 0 ? (
        <div className="empty-panel">
          <SearchX size={24} className="text-[var(--text-faint)]" />
          <h2 className="text-base font-semibold text-[var(--text-strong)]">
            No opportunities found.
          </h2>
        </div>
      ) : visibleOpportunities.length === 0 ? (
        <div className="empty-panel">
          <SearchX size={24} className="text-[var(--text-faint)]" />
          <h2 className="text-base font-semibold text-[var(--text-strong)]">
            No opportunities found.
          </h2>
        </div>
      ) : (
        <div className="space-y-4">
          {visibleOpportunities.map((opportunity) => (
            <OpportunityCard key={opportunity.id} opportunity={opportunity} />
          ))}
        </div>
      )}
    </div>
  );
}
