import { Clock3, LayoutDashboard, Plug, Radio, Settings, Wrench } from 'lucide-react';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'history', label: 'History', icon: Clock3 },
  { id: 'integrations', label: 'Integrations', icon: Plug },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export function Sidebar({ activeView, onChangeView, developerMode, onToggleDeveloperMode }) {
  return (
    <aside className="sidebar-shell">
      <div className="flex h-16 items-center gap-3 px-5">
        <div className="brand-mark">
          <Radio size={18} />
        </div>
        <div>
          <p className="text-base font-semibold text-[var(--text-strong)]">SignalForge</p>
          <p className="text-xs text-[var(--text-faint)]">Publishing workspace</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id && !developerMode;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChangeView(item.id)}
              className={`nav-item ${isActive ? 'nav-item-active' : ''}`}
            >
              <Icon size={17} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="p-3">
        <button
          type="button"
          onClick={onToggleDeveloperMode}
          className={`developer-toggle ${developerMode ? 'developer-toggle-active' : ''}`}
          title="Developer Mode"
        >
          <Wrench size={14} />
          <span>Developer Mode</span>
        </button>
      </div>
    </aside>
  );
}
