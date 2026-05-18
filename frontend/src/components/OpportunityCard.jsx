import { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  Check,
  Copy,
  Edit3,
  ExternalLink,
  Loader2,
  Send,
  XCircle,
} from 'lucide-react';
import { useUpdateDraftMutation, useUpdateStatusMutation } from '../hooks/useOpportunities';
import { copyText } from '../lib/clipboard';
import { formatRelativeTime } from '../lib/date';
import { getPlatformMeta } from '../lib/platforms';
import { openExternalUrl } from '../lib/url';
import { useToast } from './toast';

const STATUS_LABELS = {
  approved: 'Approved',
  copied: 'Copied',
  drafted: 'Draft ready',
  pending: 'Needs approval',
  published: 'Posted',
  ready: 'Ready',
  rejected: 'Rejected',
  scanning: 'Preparing',
  scheduled: 'Scheduled',
};

const PREP_LABELS = {
  discovered: 'Reading',
  classified: 'Qualified',
  drafted: 'Drafted',
  approved: 'Ready',
};

const DRAFT_PENDING_TEXT = {
  discovered: 'Reading the source and qualifying fit.',
  classified: 'Writing a platform-specific draft.',
  drafted: 'Checking the draft before it enters the queue.',
};

function cleanLabel(value) {
  return String(value || '').replace(/_/g, ' ');
}

function priorityLabel(opportunity) {
  if (opportunity.priority_label) return cleanLabel(opportunity.priority_label);
  if (opportunity.score >= 80) return 'High priority';
  if (opportunity.score >= 50) return 'Promising';
  if (opportunity.score > 0) return 'Low priority';
  return '';
}

function reviewStatus(opportunity) {
  return String(opportunity.status || opportunity.review_status || '').toLowerCase();
}

function isApproved(status) {
  return status === 'approved' || status === 'copied';
}

function ScoreBar({ score }) {
  if (!score || score <= 0) return null;
  const pct = Math.min(100, Math.max(0, score));
  const color = pct >= 80 ? 'var(--accent)' : pct >= 50 ? '#facc15' : '#6b7280';
  return (
    <div className="score-bar-track" title={`Score: ${pct}`}>
      <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export function OpportunityCard({ opportunity }) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftText, setDraftText] = useState(opportunity.draft || '');
  const [isCopied, setIsCopied] = useState(false);
  
  const lastSavedDraft = useRef(opportunity.draft || '');
  const editTextareaRef = useRef(null);
  
  const { addToast } = useToast();
  const draftMutation = useUpdateDraftMutation();
  const statusMutation = useUpdateStatusMutation();
  
  const platform = getPlatformMeta(opportunity.platform);
  const PlatformIcon = platform.icon;
  const platformKey = String(opportunity.platform || 'unknown').toLowerCase();
  const status = reviewStatus(opportunity);
  const pipelineState = opportunity.pipeline_state || '';
  
  const activeDraft = isEditing ? draftText : (opportunity.draft || draftText);
  const hasDraft = Boolean(activeDraft?.trim());
  const canMutate = Boolean(opportunity.can_mutate);
  
  // Specific loading states
  const isSavingDraft = draftMutation.isPending && draftMutation.variables?.id === opportunity.id;
  const isApproving = statusMutation.isPending && statusMutation.variables?.id === opportunity.id && statusMutation.variables?.status === 'approved';
  const isRejecting = statusMutation.isPending && statusMutation.variables?.id === opportunity.id && statusMutation.variables?.status === 'rejected';
  const isPosting = statusMutation.isPending && statusMutation.variables?.id === opportunity.id && statusMutation.variables?.status === 'published';
  const isSavingStatus = statusMutation.isPending && statusMutation.variables?.id === opportunity.id;

  const statusLabel = STATUS_LABELS[status] || PREP_LABELS[pipelineState] || STATUS_LABELS.pending;
  const priority = priorityLabel(opportunity);

  // Sync state if external change happens while not editing
  useEffect(() => {
    if (isEditing) return;
    lastSavedDraft.current = opportunity.draft || '';
  }, [isEditing, opportunity.draft]);

  // Autofocus when editing starts
  useEffect(() => {
    if (isEditing && editTextareaRef.current) {
      editTextareaRef.current.focus();
      // Move cursor to end
      editTextareaRef.current.setSelectionRange(draftText.length, draftText.length);
    }
  }, [isEditing, draftText.length]);

  // Autosave when typing
  useEffect(() => {
    if (!isEditing || draftText === lastSavedDraft.current) return;
    const timer = window.setTimeout(() => {
      const value = String(draftText || '');
      if (!canMutate || value === lastSavedDraft.current) return;
      draftMutation.mutate({ id: opportunity.id, draft: value }, {
        onSuccess: () => { lastSavedDraft.current = value; }
      });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [draftText, isEditing, canMutate, draftMutation, opportunity.id]);

  const updateStatus = (nextStatus, successMessage) => {
    if (!canMutate || isSavingStatus) return;
    statusMutation.mutate(
      { id: opportunity.id, status: nextStatus },
      {
        onSuccess: () => {
          if (successMessage) addToast(successMessage, 'success');
        },
        onError: (error) => {
          addToast(error.userMessage || 'Queue update failed.', 'error');
        },
      },
    );
  };

  const handleStartEdit = () => {
    const nextDraft = opportunity.draft || draftText;
    setDraftText(nextDraft);
    lastSavedDraft.current = nextDraft;
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setDraftText(opportunity.draft || lastSavedDraft.current);
    setIsEditing(false);
  };

  const handleSaveEdit = () => {
    const value = String(draftText || '');
    if (!canMutate) return;
    if (value === opportunity.draft) {
      setIsEditing(false);
      return;
    }
    draftMutation.mutate(
      { id: opportunity.id, draft: value },
      {
        onSuccess: () => {
          lastSavedDraft.current = value;
          addToast('Draft saved.', 'success');
          setIsEditing(false);
        },
        onError: (error) => {
          addToast(error.userMessage || 'Draft save failed.', 'error');
        },
      },
    );
  };

  const handleEditorKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      handleCancelEdit();
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSaveEdit();
    }
  };

  const handleCopy = async () => {
    if (isCopied) return;
    try {
      await copyText(activeDraft);
      setIsCopied(true);
      addToast('Draft copied — ready to paste.', 'success');
      setTimeout(() => setIsCopied(false), 1500);
      
      if (canMutate && !isApproved(status) && status !== 'copied') {
        statusMutation.mutate({ id: opportunity.id, status: 'copied' });
      }
    } catch (error) {
      addToast(error.message || 'Copy failed.', 'error');
    }
  };

  const handlePost = async () => {
    try {
      await copyText(activeDraft);
      const opened = openExternalUrl(opportunity.url);
      if (!opened) {
        addToast('Draft copied, but the URL could not open. Check pop-up blockers.', 'error');
        return;
      }
      updateStatus('published', 'Draft copied and source opened.');
    } catch (error) {
      addToast(error.message || 'Unable to prepare the post.', 'error');
    }
  };

  return (
    <article
      className={`opportunity-card platform-card platform-${platformKey}`}
      style={{ '--platform-accent': platform.accent }}
    >
      <header className="opportunity-card-header">
        <div className="opportunity-source-row">
          <span className="platform-minimal">
            <PlatformIcon size={16} />
            <span>{platform.label}</span>
          </span>
          {opportunity.source && <span>{opportunity.source}</span>}
          {opportunity.created_at && <span>{formatRelativeTime(opportunity.created_at)}</span>}
        </div>

        <span className={`status-chip status-${status || pipelineState}`}>
          {isSavingStatus && <Loader2 size={13} className="animate-spin" />}
          {statusLabel}
        </span>
      </header>

      <div className="mt-4 space-y-3">
        <div>
          <h2 className="text-xl font-semibold leading-snug text-[var(--text-strong)]">
            {opportunity.title}
          </h2>
          <ScoreBar score={opportunity.score} />
          <div className="opportunity-context">
            {priority && <span>{priority}</span>}
            {opportunity.intent && <span>{cleanLabel(opportunity.intent)}</span>}
            {opportunity.confidence > 0 && <span>{opportunity.confidence}% fit</span>}
          </div>
        </div>
        {opportunity.summary && (
          <p className="text-sm leading-6 text-[var(--text-muted)]">{opportunity.summary}</p>
        )}
      </div>

      <section className="mt-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-[var(--text-strong)]">Draft</h3>
          {isSavingDraft && !isEditing && (
            <span className="flex items-center gap-1 text-xs text-[var(--text-faint)]">
              <Loader2 size={11} className="animate-spin" />
              Saving…
            </span>
          )}
        </div>
        {isEditing ? (
          <div className="flex flex-col gap-2">
            <textarea
              ref={editTextareaRef}
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              onKeyDown={handleEditorKeyDown}
              className="draft-editor"
              rows={8}
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-faint)]">
                {draftText.length} characters (ESC to cancel, CMD+Enter to save)
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  className="button-secondary pressable text-xs py-1"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isSavingDraft}
                  onClick={handleSaveEdit}
                  className="button-primary pressable text-xs py-1"
                >
                  {isSavingDraft ? <Loader2 size={13} className="animate-spin" /> : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        ) : !hasDraft ? (
          <div className="draft-preview draft-preview-pending">
            <Loader2 size={16} className="animate-spin" />
            <span>{DRAFT_PENDING_TEXT[pipelineState] || 'Draft is being prepared…'}</span>
          </div>
        ) : (
          <div 
            className="draft-preview whitespace-pre-wrap cursor-text"
            onDoubleClick={hasDraft && canMutate ? handleStartEdit : undefined}
          >
            {activeDraft}
          </div>
        )}
      </section>

      {/* FOOTER ACTIONS */}
      {!isEditing && (
        <footer className="opportunity-actions">
          <button
            type="button"
            disabled={!hasDraft || !canMutate || isSavingStatus}
            onClick={handleStartEdit}
            className="button-secondary pressable cursor-pointer"
            aria-label="Edit draft"
          >
            <Edit3 size={16} />
            Edit
          </button>
          
          <button
            type="button"
            disabled={!hasDraft || isSavingStatus}
            onClick={handleCopy}
            className="button-secondary pressable cursor-pointer min-w-[110px]"
            aria-label="Copy draft"
          >
            {isCopied ? <Check size={16} className="text-[var(--accent)]" /> : <Copy size={16} />}
            {isCopied ? 'Copied!' : 'Copy Draft'}
          </button>
          
          <button
            type="button"
            disabled={!opportunity.url}
            onClick={() => {
              if (!openExternalUrl(opportunity.url)) {
                addToast('Unable to open the source URL.', 'error');
              }
            }}
            className="button-secondary pressable cursor-pointer"
            aria-label="Open original URL"
          >
            <ExternalLink size={16} />
            Open URL
          </button>
          
          <button
            type="button"
            disabled={!hasDraft || !canMutate || isApproved(status) || isSavingStatus}
            onClick={() => updateStatus('approved', 'Approved — ready to post.')}
            className="button-secondary pressable cursor-pointer"
            aria-label="Approve draft"
          >
            {isApproving ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
            Approve
          </button>
          
          <button
            type="button"
            disabled={!canMutate || isSavingStatus}
            onClick={() => updateStatus('rejected', 'Removed from queue.')}
            className="button-danger pressable cursor-pointer"
            aria-label="Reject opportunity"
          >
            {isRejecting ? <Loader2 size={16} className="animate-spin" /> : <XCircle size={16} />}
            Reject
          </button>
          
          <button
            type="button"
            disabled={!hasDraft || !canMutate || !opportunity.url || isSavingStatus}
            onClick={handlePost}
            className="button-primary pressable cursor-pointer"
            aria-label="Copy draft and open URL"
          >
            {isPosting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            Post
          </button>
        </footer>
      )}
    </article>
  );
}

