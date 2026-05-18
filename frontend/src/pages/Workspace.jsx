import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { OpportunityFeed } from '../components/OpportunityFeed';
import { RunScanModal } from '../components/RunScanModal';
import { Sidebar } from '../components/Sidebar';
import { TopHeader } from '../components/TopHeader';
import { getOpportunitySearchText } from '../api/normalizers';
import { useMetrics } from '../hooks/useMetrics';
import { useOpportunities } from '../hooks/useOpportunities';
import { usePipelineStatus } from '../hooks/usePipeline';
import { formatRelativeTime } from '../lib/date';

const EMPTY_OPPORTUNITIES = [];

function sessionId() {
  return window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
}

function compareNewest(a, b) {
  return new Date(b.created_at || 0) - new Date(a.created_at || 0);
}

function isInLiveSession(opportunity, session) {
  if (!session?.startedAt) return true;
  if (!opportunity.created_at) return false;
  return new Date(opportunity.created_at).getTime() >= new Date(session.startedAt).getTime();
}

function applyPlatformFilter(opportunities, platform) {
  if (platform === 'all') return opportunities;
  return opportunities.filter((o) => o.platform === platform);
}

function opportunityMergeKey(o) {
  return o.url || `${o.platform}:${o.id}` || o.id;
}

function mergeOpportunities(persisted, live) {
  const merged = new Map();
  persisted.forEach((o) => merged.set(opportunityMergeKey(o), o));
  live.forEach((o) => {
    const key = opportunityMergeKey(o);
    const existing = merged.get(key);
    if (existing) {
      merged.set(key, {
        ...existing,
        ...o,
        review_id: existing.review_id || o.review_id,
        can_mutate: existing.can_mutate || o.can_mutate,
        status: existing.status !== 'pending' && existing.status !== 'scanning' ? existing.status : (o.status || existing.status),
      });
    } else {
      merged.set(key, o);
    }
  });
  return Array.from(merged.values());
}

function groupHistory(history) {
  return history.reduce((groups, session) => {
    const date = new Date(session.startedAt);
    const label = Number.isNaN(date.getTime())
      ? 'Earlier'
      : new Intl.DateTimeFormat(undefined, { month: 'long', day: 'numeric', year: 'numeric' }).format(date);
    groups[label] = groups[label] || [];
    groups[label].push(session);
    return groups;
  }, {});
}

function isTerminal(o) {
  return o.status === 'published' || o.status === 'rejected';
}

function isApproved(o) {
  return o.status === 'approved' || o.status === 'copied';
}

// ─── Analytics Page ──────────────────────────────────────────────────────────

const PLATFORM_COLORS = {
  reddit: '#ff4500',
  quora: '#b92b27',
  medium: '#17c964',
  unknown: '#6b7280',
};

function MetricCard({ label, value, sub, accent }) {
  return (
    <div className="analytics-card">
      <span className="analytics-label">{label}</span>
      <strong className="analytics-value" style={accent ? { color: accent } : undefined}>
        {value ?? '—'}
      </strong>
      {sub && <span className="analytics-sub">{sub}</span>}
    </div>
  );
}

function AnalyticsPage({ opportunities, metrics, metricsLoading, history }) {
  const inReview = opportunities.filter((o) => !isTerminal(o) && !isApproved(o)).length;
  const readyToPost = opportunities.filter((o) => !isTerminal(o) && isApproved(o) && o.draft && o.url).length;
  const postedToday = metricsLoading ? null : (metrics?.posted_today ?? 0);
  const totalPending = metricsLoading ? null : (metrics?.total_pending ?? 0);

  const winRate = totalPending > 0
    ? Math.round((postedToday / (postedToday + totalPending)) * 100)
    : null;

  const byPlatform = metrics?.by_platform || {};
  const chartData = Object.entries(byPlatform)
    .filter(([, v]) => v > 0)
    .map(([platform, count]) => ({
      platform: platform.charAt(0).toUpperCase() + platform.slice(1),
      count,
      color: PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown,
    }));

  return (
    <div className="simple-page">
      <div>
        <p className="eyebrow">Overview</p>
        <h1 className="mt-2 text-2xl font-semibold text-[var(--text-strong)]">Analytics</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Queue health and sourcing performance at a glance.
        </p>
      </div>

      <div className="analytics-grid">
        <MetricCard label="In review" value={inReview} sub="awaiting decision" />
        <MetricCard label="Ready to post" value={readyToPost} sub="approved + drafted" accent="var(--accent)" />
        <MetricCard label="Posted today" value={postedToday} sub="published this session" />
        <MetricCard
          label="Win rate"
          value={winRate !== null ? `${winRate}%` : '—'}
          sub="posted ÷ total"
          accent={winRate >= 50 ? 'var(--accent)' : undefined}
        />
      </div>

      {chartData.length > 0 && (
        <div className="glass-panel border border-[var(--border)] p-6">
          <h2 className="mb-4 text-sm font-semibold text-[var(--text-strong)]">Opportunities by platform</h2>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData} barCategoryGap="28%">
              <XAxis
                dataKey="platform"
                tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'var(--text-faint)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                contentStyle={{
                  background: 'rgba(17,20,24,0.92)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8,
                  fontSize: 13,
                  color: '#f7f7f5',
                }}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {chartData.map((entry) => (
                  <Cell key={entry.platform} fill={entry.color} fillOpacity={0.85} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-[var(--text-faint)]">Recent scans</h2>
          <div className="space-y-2">
            {history.slice(0, 5).map((session) => (
              <div key={session.id} className="history-item">
                <span>
                  <strong>{session.query}</strong>
                  <small>{formatRelativeTime(session.startedAt)}</small>
                </span>
                <span className="soft-muted text-xs">{(session.results || []).length} items</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {history.length === 0 && chartData.length === 0 && (
        <div className="empty-panel empty-panel-large">
          <p className="text-sm text-[var(--text-muted)]">
            Run your first scan to see analytics here.
          </p>
        </div>
      )}
    </div>
  );
}

// ─── History Page ─────────────────────────────────────────────────────────────

function HistoryPage({ history, onOpenSession }) {
  const grouped = groupHistory(history);
  const groupEntries = Object.entries(grouped);

  return (
    <div className="simple-page">
      <div>
        <p className="eyebrow">Archive</p>
        <h1 className="mt-2 text-2xl font-semibold text-[var(--text-strong)]">Sourcing history</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Reopen previous runs without mixing them into the active queue.
        </p>
      </div>

      {groupEntries.length === 0 ? (
        <div className="empty-panel">
          <h2 className="text-base font-semibold text-[var(--text-strong)]">No previous sourcing runs.</h2>
        </div>
      ) : (
        <div className="history-timeline">
          {groupEntries.map(([date, sessions]) => (
            <section key={date} className="history-group">
              <h2>{date}</h2>
              <div className="space-y-2">
                {sessions.map((session) => (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => onOpenSession(session)}
                    className="history-item"
                  >
                    <span>
                      <strong>{session.query}</strong>
                      <small>{formatRelativeTime(session.startedAt)}</small>
                    </span>
                    <span>Open</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Command Metrics bar ──────────────────────────────────────────────────────

function CommandMetrics({ opportunities, postedToday, metricsLoading, isStreaming, foundCount }) {
  const inReview = opportunities.filter((item) => !isTerminal(item) && !isApproved(item)).length;
  const readyToPost = opportunities.filter(
    (item) => !isTerminal(item) && isApproved(item) && item.draft && item.url,
  ).length;
  const metrics = [
    [isStreaming ? 'Sourcing now' : 'In review', isStreaming ? foundCount : inReview],
    ['Ready to post', readyToPost],
    ['Posted today', metricsLoading ? '—' : (postedToday ?? '—')],
  ];

  return (
    <div className="command-metrics">
      {metrics.map(([label, value]) => (
        <div key={label} className="command-metric">
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

// ─── Workspace ────────────────────────────────────────────────────────────────

export function Workspace() {
  const [activeView, setActiveView] = useState('workspace');
  const [isLight, setIsLight] = useState(false);
  const [isScanOpen, setIsScanOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [platformFilter, setPlatformFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState('newest');
  const [activeSession, setActiveSession] = useState(null);
  const [history, setHistory] = useState([]);

  const pipelineQuery = usePipelineStatus();
  const pipelineStatus = pipelineQuery.data;
  const opportunitiesQuery = useOpportunities({
    pollingInterval: pipelineStatus?.running ? 3000 : 15000,
  });
  const metricsQuery = useMetrics();
  const backendOpportunities = opportunitiesQuery.data ?? EMPTY_OPPORTUNITIES;
  const liveOpportunities = pipelineStatus?.live_opportunities ?? EMPTY_OPPORTUNITIES;
  const mergedOpportunities = useMemo(
    () => mergeOpportunities(backendOpportunities, liveOpportunities),
    [backendOpportunities, liveOpportunities],
  );

  const sessionOpportunities = useMemo(() => {
    if (activeSession?.mode === 'history') {
      return activeSession.results || EMPTY_OPPORTUNITIES;
    }
    return mergedOpportunities
      .filter((o) => isInLiveSession(o, activeSession))
      .sort(compareNewest);
  }, [activeSession, mergedOpportunities]);

  const visibleOpportunities = useMemo(() => {
    const searchValue = searchTerm.trim().toLowerCase();
    const searched = searchValue
      ? sessionOpportunities.filter((item) => getOpportunitySearchText(item).includes(searchValue))
      : sessionOpportunities;
    const filtered = applyPlatformFilter(searched, platformFilter);
    return [...filtered].sort((a, b) => {
      if (sortOrder === 'newest') return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      if (sortOrder === 'oldest') return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      return 0;
    });
  }, [platformFilter, sortOrder, searchTerm, sessionOpportunities]);

  const handleScanStarted = (query) => {
    if (activeSession?.mode === 'live' && activeSession.query) {
      setHistory((current) => [
        { ...activeSession, results: sessionOpportunities },
        ...current.filter((item) => item.id !== activeSession.id),
      ]);
    }
    setActiveSession({
      id: sessionId(),
      mode: 'live',
      query,
      startedAt: new Date().toISOString(),
    });
    setActiveView('workspace');
    setSearchTerm('');
    setPlatformFilter('all');
    setSortOrder('newest');
  };

  const openHistorySession = (session) => {
    setActiveSession({ ...session, mode: 'history' });
    setActiveView('workspace');
    setSearchTerm('');
    setPlatformFilter('all');
    setSortOrder('newest');
  };

  const renderContent = () => {
    if (activeView === 'analytics') {
      return (
        <AnalyticsPage
          opportunities={sessionOpportunities}
          metrics={metricsQuery.data}
          metricsLoading={metricsQuery.isLoading}
          history={history}
        />
      );
    }

    if (activeView === 'history') {
      return <HistoryPage history={history} onOpenSession={openHistorySession} />;
    }

    return (
      <>
        <CommandMetrics
          opportunities={sessionOpportunities}
          postedToday={metricsQuery.data?.posted_today}
          metricsLoading={metricsQuery.isLoading}
          isStreaming={Boolean(pipelineStatus?.running)}
          foundCount={pipelineStatus?.items_found_so_far || liveOpportunities.length}
        />
        <OpportunityFeed
          title={activeSession?.query || 'Publishing queue'}
          subtitle={
            activeSession?.mode === 'history'
              ? 'Reopened from history.'
              : 'Edit, approve, copy, and post from one focused queue.'
          }
          opportunities={sessionOpportunities}
          visibleOpportunities={visibleOpportunities}
          platformFilter={platformFilter}
          onPlatformFilterChange={setPlatformFilter}
          sortOrder={sortOrder}
          onSortOrderChange={setSortOrder}
          isStreaming={Boolean(pipelineStatus?.running)}
          streamStage={pipelineStatus?.current_stage}
          streamCount={pipelineStatus?.items_found_so_far || liveOpportunities.length}
          partialResults={pipelineStatus?.partial_results || {}}
          isLoading={
            opportunitiesQuery.isLoading
            && !pipelineStatus?.running
            && sessionOpportunities.length === 0
          }
          isError={opportunitiesQuery.isError}
          error={opportunitiesQuery.error}
          onRetry={() => opportunitiesQuery.refetch()}
          hasActiveSession={Boolean(activeSession)}
          onStartScan={() => setIsScanOpen(true)}
        />
      </>
    );
  };

  return (
    <div className={`workspace-root ${isLight ? 'theme-light' : 'theme-dark'}`}>
      <div className="app-frame">
        <Sidebar activeView={activeView} onChangeView={setActiveView} />
        <div className="workspace-shell">
          <TopHeader
            isLight={isLight}
            onToggleTheme={() => setIsLight((v) => !v)}
            onOpenScan={() => setIsScanOpen(true)}
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
            sourceRunning={pipelineStatus?.running}
          />
          <main className="workspace-body">{renderContent()}</main>
        </div>
      </div>

      <RunScanModal
        isOpen={isScanOpen}
        onClose={() => setIsScanOpen(false)}
        onScanStarted={handleScanStarted}
      />
    </div>
  );
}
