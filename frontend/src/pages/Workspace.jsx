import { useMemo, useState } from 'react';
import { Moon, Settings, Sun } from 'lucide-react';
import { DeveloperMode } from '../components/DeveloperMode';
import { OpportunityFeed } from '../components/OpportunityFeed';
import { RunScanModal } from '../components/RunScanModal';
import { Sidebar } from '../components/Sidebar';
import { TopHeader } from '../components/TopHeader';
import { getOpportunitySearchText } from '../api/normalizers';
import { API_BASE_URL } from '../api/http';
import { useHealth } from '../hooks/useHealth';
import { useMetrics } from '../hooks/useMetrics';
import { useOpportunities } from '../hooks/useOpportunities';
import { usePipelineStatus } from '../hooks/usePipeline';
import { formatRelativeTime } from '../lib/date';
import { platformLabel } from '../lib/platforms';

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
  return opportunities.filter((opportunity) => opportunity.platform === platform);
}

function groupHistory(history) {
  return history.reduce((groups, session) => {
    const date = new Date(session.startedAt);
    const label = Number.isNaN(date.getTime())
      ? 'Earlier'
      : new Intl.DateTimeFormat(undefined, {
          month: 'long',
          day: 'numeric',
          year: 'numeric',
        }).format(date);

    groups[label] = groups[label] || [];
    groups[label].push(session);
    return groups;
  }, {});
}

function MinimalMetrics({ opportunities, postedToday, metricsLoading }) {
  const readyToReview = opportunities.length;
  const readyToPublish = opportunities.filter((item) => item.draft && item.url).length;
  const metrics = [
    ['Ready to Review', readyToReview],
    ['Ready to Publish', readyToPublish],
    ['Posted Today', metricsLoading ? '-' : postedToday],
  ];

  return (
    <div className="minimal-metrics">
      {metrics.map(([label, value]) => (
        <div key={label} className="minimal-metric">
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function HistoryPage({ history, onOpenSession }) {
  const grouped = groupHistory(history);
  const groupEntries = Object.entries(grouped);

  return (
    <div className="simple-page">
      <div>
        <h1 className="text-3xl font-semibold text-[var(--text-strong)]">History</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Reopen previous searches without mixing them into today's workspace.
        </p>
      </div>

      {groupEntries.length === 0 ? (
        <div className="empty-panel">
          <h2 className="text-base font-semibold text-[var(--text-strong)]">
            No search history yet.
          </h2>
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

function IntegrationsPage({ healthQuery }) {
  const apiConnected = healthQuery.isSuccess && healthQuery.data?.status === 'ok';

  return (
    <div className="simple-page">
      <div>
        <h1 className="text-3xl font-semibold text-[var(--text-strong)]">Integrations</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Connection status from backend endpoints only.
        </p>
      </div>

      <section className="settings-panel">
        <div className="settings-row">
          <div>
            <h2>API</h2>
            <p>{API_BASE_URL}</p>
          </div>
          <span className={apiConnected ? 'soft-ok' : 'soft-muted'}>
            {apiConnected ? 'Connected' : healthQuery.isLoading ? 'Checking' : 'Unavailable'}
          </span>
        </div>
        <div className="settings-row">
          <div>
            <h2>Slack</h2>
            <p>Status is not exposed by the backend.</p>
          </div>
        </div>
        <div className="settings-row">
          <div>
            <h2>Supabase</h2>
            <p>Status is not exposed by the backend.</p>
          </div>
        </div>
      </section>
    </div>
  );
}

function SettingsPage({ isLight, onToggleTheme, developerMode, onToggleDeveloperMode }) {
  return (
    <div className="simple-page">
      <div>
        <h1 className="text-3xl font-semibold text-[var(--text-strong)]">Settings</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Keep the workspace quiet and publishing-focused.
        </p>
      </div>

      <section className="settings-panel">
        <div className="settings-row">
          <div>
            <h2>Appearance</h2>
            <p>{isLight ? 'Light mode' : 'Dark mode'}</p>
          </div>
          <button type="button" onClick={onToggleTheme} className="button-secondary">
            {isLight ? <Moon size={16} /> : <Sun size={16} />}
            Toggle
          </button>
        </div>
        <div className="settings-row">
          <div>
            <h2>Developer Mode</h2>
            <p>{developerMode ? 'Visible' : 'Hidden'}</p>
          </div>
          <button type="button" onClick={onToggleDeveloperMode} className="button-secondary">
            <Settings size={16} />
            {developerMode ? 'Hide' : 'Show'}
          </button>
        </div>
      </section>
    </div>
  );
}

export function Workspace() {
  const [activeView, setActiveView] = useState('dashboard');
  const [developerMode, setDeveloperMode] = useState(false);
  const [isLight, setIsLight] = useState(false);
  const [isScanOpen, setIsScanOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [platformFilter, setPlatformFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState('newest');
  const [activeSession, setActiveSession] = useState(null);
  const [history, setHistory] = useState([]);
  const pipelineQuery = usePipelineStatus();
  const opportunitiesQuery = useOpportunities({
    pollingInterval: pipelineQuery.data?.running ? 3000 : 15000,
  });
  const metricsQuery = useMetrics();
  const healthQuery = useHealth();
  const backendOpportunities = opportunitiesQuery.data ?? EMPTY_OPPORTUNITIES;

  const sessionOpportunities = useMemo(() => {
    if (activeSession?.mode === 'history') {
      return activeSession.results || EMPTY_OPPORTUNITIES;
    }

    return backendOpportunities
      .filter((opportunity) => isInLiveSession(opportunity, activeSession))
      .sort(compareNewest);
  }, [activeSession, backendOpportunities]);

  const visibleOpportunities = useMemo(() => {
    const searched = sessionOpportunities.filter((item) =>
      getOpportunitySearchText(item).includes(searchTerm.trim().toLowerCase()),
    );

    const filtered = applyPlatformFilter(searched, platformFilter);

    return filtered.sort((a, b) => {
      if (sortOrder === 'newest') {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      }
      if (sortOrder === 'oldest') {
        return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      }
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
    setActiveView('dashboard');
    setDeveloperMode(false);
    setSearchTerm('');
    setPlatformFilter('all');
    setSortOrder('newest');
  };

  const openHistorySession = (session) => {
    setActiveSession({ ...session, mode: 'history' });
    setActiveView('dashboard');
    setDeveloperMode(false);
    setSearchTerm('');
    setPlatformFilter('all');
    setSortOrder('newest');
  };

  const renderContent = () => {
    if (developerMode) {
      return (
        <DeveloperMode
          opportunities={sessionOpportunities}
          metrics={metricsQuery.data}
          pipelineStatus={pipelineQuery.data}
        />
      );
    }

    if (activeView === 'history') {
      return <HistoryPage history={history} onOpenSession={openHistorySession} />;
    }

    if (activeView === 'integrations') {
      return <IntegrationsPage healthQuery={healthQuery} />;
    }

    if (activeView === 'settings') {
      return (
        <SettingsPage
          isLight={isLight}
          onToggleTheme={() => setIsLight((value) => !value)}
          developerMode={developerMode}
          onToggleDeveloperMode={() => setDeveloperMode((value) => !value)}
        />
      );
    }

    return (
      <>
        <MinimalMetrics
          opportunities={sessionOpportunities}
          postedToday={metricsQuery.data?.posted_today}
          metricsLoading={metricsQuery.isLoading}
        />
        <OpportunityFeed
          title={activeSession?.query || 'What should you post next?'}
          subtitle={
            activeSession?.mode === 'history'
              ? 'Reopened from history.'
              : 'Review the draft, make any edits, then copy and open the source.'
          }
          opportunities={sessionOpportunities}
          visibleOpportunities={visibleOpportunities}
          platformFilter={platformFilter}
          onPlatformFilterChange={setPlatformFilter}
          sortOrder={sortOrder}
          onSortOrderChange={setSortOrder}
          isLoading={opportunitiesQuery.isLoading}
          isError={opportunitiesQuery.isError}
          error={opportunitiesQuery.error}
          onRetry={() => opportunitiesQuery.refetch()}
        />
      </>
    );
  };

  return (
    <div className={`workspace-root ${isLight ? 'theme-light' : 'theme-dark'}`}>
      <div className="app-frame">
        <Sidebar
          activeView={activeView}
          onChangeView={(view) => {
            setActiveView(view);
            setDeveloperMode(false);
          }}
          developerMode={developerMode}
          onToggleDeveloperMode={() => setDeveloperMode((value) => !value)}
        />
        <div className="workspace-shell">
          <TopHeader
            isLight={isLight}
            onToggleTheme={() => setIsLight((value) => !value)}
            onOpenScan={() => setIsScanOpen(true)}
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
            scanRunning={pipelineQuery.data?.running}
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
