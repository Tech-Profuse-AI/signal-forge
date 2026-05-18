import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import { ToastContext } from './toast';

const TOAST_STYLES = {
  success: {
    icon: CheckCircle2,
    className: 'border-emerald-300/20 bg-emerald-950/90 text-emerald-50',
    bar: 'bg-emerald-400',
  },
  error: {
    icon: AlertCircle,
    className: 'border-red-300/20 bg-red-950/90 text-red-50',
    bar: 'bg-red-400',
  },
  info: {
    icon: Info,
    className: 'border-sky-300/20 bg-sky-950/90 text-sky-50',
    bar: 'bg-sky-400',
  },
  warning: {
    icon: AlertCircle,
    className: 'border-amber-300/20 bg-amber-950/90 text-amber-50',
    bar: 'bg-amber-400',
  },
};

const DURATION_MS = 3500;

function Toast({ toast, onDismiss }) {
  const style = TOAST_STYLES[toast.type] || TOAST_STYLES.info;
  const Icon = style.icon;
  const [exiting, setExiting] = useState(false);

  const dismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => onDismiss(toast.id), 280);
  }, [onDismiss, toast.id]);

  useEffect(() => {
    const t = setTimeout(dismiss, DURATION_MS);
    return () => clearTimeout(t);
  }, [dismiss]);

  return (
    <div className={`glass-toast flex items-start gap-3 border px-4 py-3 text-sm shadow-2xl ${style.className} ${exiting ? 'toast-exit' : 'toast-enter'}`}>
      <Icon size={17} className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1 leading-5">{toast.message}</span>
      <button
        type="button"
        onClick={dismiss}
        className="shrink-0 rounded-md p-1 opacity-70 transition hover:bg-white/10 hover:opacity-100"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
      <span
        className={`toast-progress-bar ${style.bar}`}
        style={{ animationDuration: `${DURATION_MS}ms` }}
      />
    </div>
  );
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismissToast = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((message, type = 'success') => {
    const id = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    setToasts((current) => [...current, { id, message, type }]);
    return id;
  }, []);

  const value = useMemo(() => ({ addToast, dismissToast }), [addToast, dismissToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
