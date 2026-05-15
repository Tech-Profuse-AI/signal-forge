import { useCallback, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import { ToastContext } from './toast';

const TOAST_STYLES = {
  success: {
    icon: CheckCircle2,
    className: 'border-emerald-300/20 bg-emerald-950/90 text-emerald-50',
  },
  error: {
    icon: AlertCircle,
    className: 'border-red-300/20 bg-red-950/90 text-red-50',
  },
  info: {
    icon: Info,
    className: 'border-sky-300/20 bg-sky-950/90 text-sky-50',
  },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismissToast = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const addToast = useCallback((message, type = 'success') => {
    const id = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    setToasts((current) => [...current, { id, message, type }]);
    window.setTimeout(() => dismissToast(id), 3500);
    return id;
  }, [dismissToast]);

  const value = useMemo(() => ({ addToast, dismissToast }), [addToast, dismissToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((toast) => {
          const style = TOAST_STYLES[toast.type] || TOAST_STYLES.info;
          const Icon = style.icon;

          return (
            <div
              key={toast.id}
              className={`glass-toast flex items-start gap-3 border px-4 py-3 text-sm shadow-2xl ${style.className}`}
            >
              <Icon size={17} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 leading-5">{toast.message}</span>
              <button
                type="button"
                onClick={() => dismissToast(toast.id)}
                className="shrink-0 rounded-md p-1 opacity-70 transition hover:bg-white/10 hover:opacity-100"
                aria-label="Dismiss notification"
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
