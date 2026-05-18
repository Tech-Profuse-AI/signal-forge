import { AlertCircle, Loader2, Radio, SearchX, Sparkles } from 'lucide-react';
import { OpportunityCard } from './OpportunityCard';

const FILTERS = [
  ['all', 'All'],
  ['reddit', 'Reddit'],
  ['quora', 'Quora'],
  ['medium', 'Medium'],
];

const STAGE_COPY = {
  queued: 'Queued',
  scanner: 'Finding conversations',
  reddit_partial: 'Reddit surfaced',
  quora_partial: 'Quora surfaced',
  medium_partial: 'Medium surfaced',
  discovered: 'Reading signals',
  classified: 'Ranking intent',
  drafted: 'Writing drafts',
  approved: 'Ready for review',
  complete: 'Queue refreshed',
  failed: 'Sourcing paused',
};

function stageLabel(stage) {
  return STAGE_COPY[String(stage || '').toLowerCase()] || 'Sourcing opportunities';
}

function platformCounts(opportunities) {
  return opportunities.reduce(
    (counts, item) => {
      counts.all += 1;
      counts[item.platform] = (counts[item.platform] || 0) + 1;
      return counts;
    },
    { all: 0 },
  );
}

function OpportunitySkeleton({ compact = false }) {
  return (
    <div className={`opportunity-card skeleton-card ${compact ? 'skeleton-card-compact' : ''}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="skeleton-line h-4 w-28" />
        <div className="skeleton-line h-4 w-20" />
      </div>
      <div className="mt-5 space-y-3">
        <div className="skeleton-line h-7 w-3/4" />
        <div className="skeleton-line h-4 w-full" />
        <div className="skeleton-line h-4 w-5/6" />
        {!compact && <div className="skeleton-line h-32 w-full" />}
      </div>
    </div>
  );
}

function StreamStrip({ stage, count, partialResults }) {
  const partialEntries = FILTERS
    .filter(([platform]) => platform !== 'all')
    .map(([platform, label]) => ({
      platform,
      label,
      count: partialResults?.[platform]?.count || 0,
    }));

  return (
    <div className="stream-strip">
      <div className="flex min-w-0 items-center gap-3">
        <span className="stream-pulse">
          <Radio size={15} className="stream-pulse-icon" />
        </span>
        <div className="min-w-0">
          <p>{stageLabel(stage)}</p>
          <span>{count || 0} opportunities in motion</span>
        </div>
      </div>
      <div className="stream-platforms">
        {partialEntries.map((item) => (
          <span key={item.platform} className={`stream-platform platform-${item.platform}`}>
            {item.label}
            <strong>{item.count}</strong>
          </span>
        ))}
      </div>
    </div>
  );
}

function EmptyOnboarding({ onStartScan }) {
  return (
    <div className="onboarding-panel">
      <div className="onboarding-icon">
        <Sparkles size={28} />
      </div>
      <h2 className="text-xl font-semibold text-[var(--text-strong)]">Ready to source</h2>
      <p className="mt-2 max-w-sm text-center text-sm leading-6 text-[var(--text-muted)]">
        SignalForge scans Reddit, Quora, and Medium for high-intent conversations matching your signal — then drafts a reply for each one.
      </p>
      <div className="onboarding-steps">
        <div className="onboarding-step">
          <span className="onboarding-step-num">1</span>
          <span>Describe your buyer signal</span>
        </div>
        <div className="onboarding-step">
          <span className="onboarding-step-num">2</span>
          <span>Review AI-ranked opportunities</span>
        </div>
        <div className="onboarding-step">
          <span className="onboarding-step-num">3</span>
          <span>Approve, edit, and post in one click</span>
        </div>
      </div>
      {onStartScan && (
        <button type="button" onClick={onStartScan} className="button-primary mt-2">
          <Sparkles size={15} />
          Start your first scan
        </button>
      )}
    </div>
  );
}

export function OpportunityFeed({
  title,
  subtitle,
  opportunities,
  visibleOpportunities,
  platformFilter,
  onPlatformFilterChange,
  sortOrder,
  onSortOrderChange,
  isStreaming,
  streamStage,
  streamCount,
  partialResults,
  isLoading,
  isError,
  error,
  onRetry,
  hasActiveSession,
  onStartScan,
}) {
  const counts = platformCounts(opportunities);

  return (
    <div className="feed-shell">
      <div className="feed-header">
        <div>
          <p className="eyebrow">Live desk</p>
          <h1 className="mt-2 text-2xl font-semibold text-[var(--text-strong)]">{title}</h1>
          {subtitle && (
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
              {subtitle}
            </p>
          )}
        </div>

        <div className="feed-controls">
          <div className="segmented-control" aria-label="Filter by platform">
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => onPlatformFilterChange(value)}
                className={`filter-toggle ${platformFilter === value ? 'active' : ''}`}
              >
                <span>{label}</span>
                <strong>{counts[value] || 0}</strong>
              </button>
            ))}
          </div>

          <div className="segmented-control" aria-label="Sort opportunities">
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
        <div className="feed-list">
          {[0, 1, 2].map((item) => <OpportunitySkeleton key={item} />)}
        </div>
      ) : isError ? (
        <div className="empty-panel empty-panel-large">
          <AlertCircle size={24} className="text-red-300 shrink-0" />
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-[var(--text-strong)]">
              Could not load the queue
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {error?.userMessage || error?.message || 'The request failed.'}
            </p>
          </div>
          <button type="button" onClick={onRetry} className="button-secondary shrink-0">
            <Loader2 size={15} />
            Retry
          </button>
        </div>
      ) : !hasActiveSession && opportunities.length === 0 ? (
        <EmptyOnboarding onStartScan={onStartScan} />
      ) : opportunities.length === 0 && !isStreaming ? (
        <div className="empty-panel empty-panel-large">
          <SearchX size={24} className="text-[var(--text-faint)] shrink-0" />
          <div>
            <h2 className="text-base font-semibold text-[var(--text-strong)]">
              No opportunities in the queue.
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Start a new scan to build a fresh publishing list.
            </p>
          </div>
        </div>
      ) : visibleOpportunities.length === 0 ? (
        <div className="feed-list">
          {isStreaming && (
            <StreamStrip stage={streamStage} count={streamCount} partialResults={partialResults} />
          )}
          <div className="empty-panel">
            <SearchX size={20} className="text-[var(--text-faint)]" />
            <h2 className="text-base font-semibold text-[var(--text-strong)]">
              No matches for this filter.
            </h2>
          </div>
          {isStreaming && <OpportunitySkeleton compact />}
        </div>
      ) : (
        <div className="feed-list">
          {isStreaming && (
            <StreamStrip stage={streamStage} count={streamCount} partialResults={partialResults} />
          )}
          {visibleOpportunities.map((opportunity) => (
            <OpportunityCard key={opportunity.id} opportunity={opportunity} />
          ))}
          {isStreaming && <OpportunitySkeleton compact />}
        </div>
      )}
    </div>
  );
}
