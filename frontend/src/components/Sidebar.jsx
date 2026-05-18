import { BarChart2, Clock3, Radio, Send } from 'lucide-react';

const NAV_ITEMS = [
  { id: 'workspace', label: 'Queue', icon: Send },
  { id: 'analytics', label: 'Analytics', icon: BarChart2 },
  { id: 'history', label: 'History', icon: Clock3 },
];

export function Sidebar({ activeView, onChangeView }) {
  return (
    <aside className="sidebar-shell">
      <div className="flex h-16 items-center gap-3 px-5">
        <div className="brand-mark">
          <Radio size={18} />
        </div>
        <div>
          <p className="text-base font-semibold text-[var(--text-strong)]">SignalForge</p>
          <p className="text-xs text-[var(--text-faint)]">Publishing command</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChangeView(item.id)}
              className={`nav-item ${activeView === item.id ? 'nav-item-active' : ''}`}
            >
              <Icon size={17} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="px-5 py-4 border-t border-[var(--border)]">
        <p className="text-xs text-[var(--text-faint)]">v0.9 · internal demo</p>
      </div>
    </aside>
  );
}
