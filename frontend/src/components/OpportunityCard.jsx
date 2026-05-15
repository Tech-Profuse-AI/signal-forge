import { useEffect, useRef, useState } from 'react';
import { Copy, Edit3, ExternalLink, Send } from 'lucide-react';
import { useUpdateDraftMutation } from '../hooks/useOpportunities';
import { copyText } from '../lib/clipboard';
import { formatRelativeTime } from '../lib/date';
import { getPlatformMeta } from '../lib/platforms';
import { openExternalUrl } from '../lib/url';
import { useToast } from './toast';

function cleanLabel(value) {
  return String(value || '').replace(/_/g, ' ');
}

export function OpportunityCard({ opportunity }) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftText, setDraftText] = useState(opportunity.draft);
  const lastSavedDraft = useRef(opportunity.draft);
  const { addToast } = useToast();
  const draftMutation = useUpdateDraftMutation();
  const platform = getPlatformMeta(opportunity.platform);
  const PlatformIcon = platform.icon;
  const isSaving =
    draftMutation.isPending && draftMutation.variables?.id === opportunity.id;

  useEffect(() => {
    if (!isEditing || draftText === lastSavedDraft.current) {
      return undefined;
    }

    const nextDraft = draftText;
    const timer = window.setTimeout(() => {
      draftMutation.mutate(
        { id: opportunity.id, draft: nextDraft },
        {
          onSuccess: () => {
            lastSavedDraft.current = nextDraft;
          },
          onError: (error) => {
            addToast(error.userMessage || 'Draft autosave failed.', 'error');
          },
        },
      );
    }, 700);

    return () => window.clearTimeout(timer);
  }, [addToast, draftMutation, draftText, isEditing, opportunity.id]);

  const handleCopy = async () => {
    try {
      await copyText(draftText);
      addToast('Draft copied.', 'success');
    } catch (error) {
      addToast(error.message || 'Copy failed.', 'error');
    }
  };

  const handleOpen = () => {
    if (!openExternalUrl(opportunity.url)) {
      addToast('Unable to open source URL.', 'error');
    }
  };

  const handlePost = async () => {
    try {
      await copyText(draftText);
      openExternalUrl(opportunity.url);
      addToast('Draft copied. Paste directly into platform.', 'success');
    } catch (error) {
      addToast(error.message || 'Unable to copy draft.', 'error');
    }
  };

  return (
    <article className="opportunity-card">
      <header className="flex flex-wrap items-center gap-3 text-sm text-[var(--text-muted)]">
        <span className="platform-minimal" style={{ color: platform.accent }}>
          <PlatformIcon size={16} />
          <span>{platform.label}</span>
        </span>
        {opportunity.source && <span>{opportunity.source}</span>}
        {opportunity.created_at && <span>{formatRelativeTime(opportunity.created_at)}</span>}
        {opportunity.confidence > 0 && (
          <span className="confidence-badge">{opportunity.confidence}% confidence</span>
        )}
      </header>

      <div className="mt-4 space-y-3">
        <div>
          <h2 className="text-xl font-semibold leading-snug text-[var(--text-strong)]">
            {opportunity.title}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-faint)]">
            {cleanLabel(opportunity.intent)} / score {opportunity.score}
          </p>
        </div>
        {opportunity.summary && (
          <p className="text-sm leading-6 text-[var(--text-muted)]">{opportunity.summary}</p>
        )}
      </div>

      <section className="mt-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-[var(--text-strong)]">Draft</h3>
          {isSaving && <span className="text-xs text-[var(--text-faint)]">Saving</span>}
        </div>
        {isEditing ? (
          <textarea
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            className="draft-editor"
            rows={8}
          />
        ) : (
          <div className="draft-preview whitespace-pre-wrap">{draftText}</div>
        )}
      </section>

      <footer className="mt-5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setIsEditing((value) => !value)}
          className="button-secondary"
        >
          <Edit3 size={16} />
          {isEditing ? 'Done' : 'Edit'}
        </button>
        <button type="button" onClick={handleCopy} className="button-secondary">
          <Copy size={16} />
          Copy
        </button>
        <button type="button" onClick={handleOpen} className="button-secondary">
          <ExternalLink size={16} />
          Open URL
        </button>
        <button type="button" onClick={handlePost} className="button-primary">
          <Send size={16} />
          Post
        </button>
      </footer>
    </article>
  );
}
