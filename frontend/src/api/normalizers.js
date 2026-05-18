const URL_PATTERN = /^https?:\/\//i;

const STATUS_MAP = {
  approved: 'approved',
  approved_for_posting: 'approved',
  copied: 'copied',
  classified: 'scanning',
  discovered: 'scanning',
  drafted: 'drafted',
  edited: 'pending',
  pending: 'pending',
  ready: 'ready',
  posted: 'published',
  published: 'published',
  rejected: 'rejected',
  skipped: 'rejected',
  scheduled: 'scheduled',
};

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function firstText(value, fallback = '') {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (value !== null && value !== undefined && typeof value !== 'object') {
    const text = String(value).trim();
    if (text) return text;
  }
  return fallback;
}

function toNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function normalizePlatform(value) {
  return firstText(value, 'unknown').toLowerCase();
}

export function normalizeStatus(value) {
  const status = firstText(value, 'ready').toLowerCase();
  return STATUS_MAP[status] || status || 'ready';
}

export function normalizeOpportunity(raw = {}) {
  if (!isRecord(raw)) return null;

  const id = firstText(raw.id || raw.review_id || raw.opportunity_id);
  const platform = normalizePlatform(raw.platform);
  const title = firstText(raw.title, 'Untitled opportunity');
  const url = firstText(raw.url);
  const urlValid = raw.url_valid === true && URL_PATTERN.test(url);

  if (!id || !url || !urlValid || platform === 'unknown') {
    return null;
  }

  return {
    id,
    opportunity_id: firstText(raw.opportunity_id, id),
    review_id: firstText(raw.review_id),
    platform,
    title,
    url,
    url_valid: true,
    draft: firstText(raw.draft),
    score: Math.round(clamp(toNumber(raw.score, 0), 0, 100)),
    has_score: true,
    priority_label: firstText(raw.priority_label),
    source_score: toNumber(raw.source_score, 0),
    intent: firstText(raw.intent || raw.pipeline_state || raw.status),
    confidence: Math.round(clamp(toNumber(raw.confidence, 0), 0, 100)),
    status: normalizeStatus(raw.status || raw.review_status || raw.pipeline_state),
    pipeline_state: firstText(raw.pipeline_state).toLowerCase(),
    review_status: firstText(raw.review_status || raw.status).toLowerCase(),
    review_state: firstText(raw.review_state),
    source: firstText(raw.source || raw.community || raw.subreddit || raw.topic),
    summary: firstText(raw.summary || raw.body),
    body: firstText(raw.body),
    author: firstText(raw.author),
    community: firstText(raw.community),
    subreddit: firstText(raw.subreddit),
    topic: firstText(raw.topic),
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    signals: Array.isArray(raw.signals) ? raw.signals : [],
    created_at: firstText(raw.created_at),
    updated_at: firstText(raw.updated_at),
    tone: firstText(raw.tone),
    cta: firstText(raw.cta),
    reasoning: firstText(raw.reasoning),
    compliance_approved: Boolean(raw.compliance_approved),
    risk_level: firstText(raw.risk_level),
    violations: Array.isArray(raw.violations) ? raw.violations : [],
    recommendation: firstText(raw.recommendation),
    can_mutate: Boolean(raw.can_mutate || raw.review_id),
  };
}

export function normalizeOpportunityList(payload) {
  const items = Array.isArray(payload)
    ? payload
    : payload?.items || payload?.results || payload?.opportunities || [];

  return items.map(normalizeOpportunity).filter(Boolean);
}

export function normalizePipelineStatus(payload = {}) {
  const partialResults = isRecord(payload.partial_results)
    ? Object.entries(payload.partial_results).reduce((acc, [platform, value]) => {
        const record = isRecord(value) ? value : {};
        acc[normalizePlatform(platform)] = {
          count: toNumber(record.count, 0),
          items: normalizeOpportunityList(record.items || []),
          error: firstText(record.error),
        };
        return acc;
      }, {})
    : {};

  return {
    running: Boolean(payload.running),
    last_run: firstText(payload.last_run),
    last_query: firstText(payload.last_query),
    current_stage: firstText(payload.current_stage),
    items_found_so_far: toNumber(payload.items_found_so_far, 0),
    partial_results: partialResults,
    live_opportunities: normalizeOpportunityList(payload.live_opportunities || []),
    timings: isRecord(payload.timings) ? payload.timings : {},
  };
}

export function normalizeMetrics(payload = {}) {
  const byPlatform = isRecord(payload.by_platform) ? payload.by_platform : {};

  return {
    total_pending: toNumber(payload.total_pending, 0),
    posted_today: toNumber(payload.posted_today, 0),
    skipped_today: toNumber(payload.skipped_today, 0),
    by_platform: Object.entries(byPlatform).reduce((acc, [key, value]) => {
      acc[normalizePlatform(key)] = toNumber(value, 0);
      return acc;
    }, {}),
  };
}

export function getOpportunitySearchText(opportunity) {
  return [
    opportunity.platform,
    opportunity.title,
    opportunity.summary,
    opportunity.intent,
    opportunity.source,
    opportunity.draft,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}
