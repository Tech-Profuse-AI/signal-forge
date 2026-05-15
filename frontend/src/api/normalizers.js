const URL_PATTERN = /^https?:\/\//i;

const STATUS_MAP = {
  approved: 'ready',
  copied: 'ready',
  edited: 'ready',
  pending: 'ready',
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

function firstText(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
    if (value !== null && value !== undefined && typeof value !== 'object') {
      const text = String(value).trim();
      if (text) return text;
    }
  }

  return '';
}

function toNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function normalizePercentage(value, fallback = 0) {
  const number = toNumber(value, fallback);
  const scaled = number > 0 && number <= 1 ? number * 100 : number;

  return Math.round(clamp(scaled, 0, 100));
}

function summarize(text, maxLength = 220) {
  const cleaned = firstText(text).replace(/\s+/g, ' ');
  if (cleaned.length <= maxLength) return cleaned;

  return `${cleaned.slice(0, maxLength - 1).trim()}...`;
}

function createdAtFromOpportunity(opportunity) {
  const createdUtc = toNumber(opportunity?.created_utc, 0);
  if (createdUtc > 0) {
    return new Date(createdUtc * 1000).toISOString();
  }

  return '';
}

function normalizePlatform(value) {
  const platform = firstText(value).toLowerCase();
  return platform;
}

function sourceFromOpportunity(platform, opportunity, raw) {
  const source = firstText(
    raw.source,
    raw.community,
    raw.channel,
    raw.subreddit,
    raw.topic,
    opportunity.source,
    opportunity.community,
    opportunity.channel,
  );

  if (source) return source;

  if (platform === 'reddit') {
    const subreddit = firstText(opportunity.subreddit);
    return subreddit ? `r/${subreddit.replace(/^r\//i, '')}` : '';
  }

  if (platform === 'quora') {
    return firstText(opportunity.topic, opportunity.author);
  }

  if (platform === 'medium') {
    return firstText(opportunity.author);
  }

  return '';
}

function draftFromRaw(raw) {
  const draft = isRecord(raw.draft) ? raw.draft : {};
  const compliance = isRecord(raw.compliance) ? raw.compliance : {};
  const mainDraft = firstText(
    raw.final_draft,
    raw.safe_draft,
    compliance.safe_draft,
    raw.draft_text,
    typeof raw.draft === 'string' ? raw.draft : '',
    draft.draft,
  );
  const cta = firstText(draft.cta);

  if (mainDraft && cta && !mainDraft.includes(cta)) {
    return `${mainDraft}\n\n${cta}`;
  }

  return mainDraft;
}

function scoreFromRaw(raw, opportunity) {
  const score = isRecord(raw.score) ? raw.score : {};
  const candidate = firstText(
    score.priority_score,
    score.score,
    raw.priority_score,
    typeof raw.score === 'number' ? raw.score : '',
    raw.score_value,
    opportunity.priority_score,
  );

  if (!candidate) {
    return { hasScore: false, score: 0 };
  }

  return {
    hasScore: true,
    score: Math.round(clamp(toNumber(candidate, 0), 0, 100)),
  };
}

function confidenceFromRaw(raw) {
  const intent = isRecord(raw.intent) ? raw.intent : {};
  const score = isRecord(raw.score) ? raw.score : {};

  return normalizePercentage(
    firstText(
      raw.confidence,
      raw.intent_confidence,
      intent.confidence,
      score.confidence,
    ),
    0,
  );
}

function normalizeStatus(value) {
  const status = firstText(value).toLowerCase();
  return STATUS_MAP[status] || status || 'ready';
}

const REDDIT_ENTITY_PATTERN = /\/t[12345]_[a-z0-9]+/i;

function isValidRedditPostUrl(url) {
  if (!url || typeof url !== 'string') return false;
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes('reddit.com')) return true; // not reddit, skip check
    // Reject entity URLs (t5_ subreddits, t1_ comments, etc.)
    if (REDDIT_ENTITY_PATTERN.test(parsed.pathname)) return false;
    // Must contain /comments/ for a valid Reddit post URL
    if (!parsed.pathname.includes('/comments/')) return false;
    // Reject bare subreddit URLs
    if (/^\/r\/[^/]+\/?$/.test(parsed.pathname)) return false;
    // Reject user profile URLs
    if (parsed.pathname.startsWith('/user/') || parsed.pathname.startsWith('/u/')) return false;
    return true;
  } catch {
    return false;
  }
}

function normalizeUrl(rawUrl) {
  const url = firstText(rawUrl);
  const basicValid = URL_PATTERN.test(url);

  // For Reddit URLs, apply stricter validation
  let redditValid = true;
  if (basicValid && url.includes('reddit.com')) {
    redditValid = isValidRedditPostUrl(url);
  }

  return {
    url,
    urlValid: basicValid && redditValid,
  };
}

export function normalizeOpportunity(raw = {}) {
  const record = isRecord(raw) ? raw : {};
  const opportunity = isRecord(record.opportunity) ? record.opportunity : {};
  const intent = isRecord(record.intent) ? record.intent : {};
  const knowledge = isRecord(record.knowledge) ? record.knowledge : {};
  const platform = normalizePlatform(record.platform || opportunity.platform);
  if (!platform || platform === 'unknown') {
    return null;
  }

  const idSource = firstText(
    record.id,
    record.review_id,
    record.opportunity_id,
    opportunity.id,
    opportunity.url,
    record.url,
  );
  const title = firstText(record.title, opportunity.title, opportunity.query);
  const { url, urlValid } = normalizeUrl(record.url || opportunity.url || opportunity.link);
  const draft = draftFromRaw(record);
  const intentLabel = firstText(
    typeof record.intent === 'string' ? record.intent : '',
    intent.intent,
    intent.label,
  );
  const score = scoreFromRaw(record, opportunity);

  if (!idSource || !title || !url || !urlValid || !draft || !intentLabel || !score.hasScore) {
    return null;
  }

  const summary = summarize(
    firstText(
      record.summary,
      record.description,
      knowledge.summary,
      opportunity.summary,
      record.body,
      opportunity.body,
    ),
  );

  return {
    id: idSource,
    platform,
    title,
    url,
    url_valid: true,
    intent: intentLabel,
    score: score.score,
    draft,
    status: normalizeStatus(record.status || record.review_status || record.approval_mode),
    source: sourceFromOpportunity(platform, opportunity, record),
    created_at: firstText(
      record.created_at,
      record.createdAt,
      record.dequeued_at,
      opportunity.created_at,
      createdAtFromOpportunity(opportunity),
    ),
    summary,
    confidence: confidenceFromRaw(record),
    can_mutate: Boolean(idSource),
  };
}

export function normalizeOpportunityList(payload) {
  const items = Array.isArray(payload)
    ? payload
    : payload?.items || payload?.results || payload?.opportunities || [];

  return items.map(normalizeOpportunity).filter(Boolean);
}

export function normalizePipelineStatus(payload = {}) {
  return {
    running: Boolean(payload.running),
    last_run: firstText(payload.last_run),
    last_query: firstText(payload.last_query),
    current_stage: firstText(payload.current_stage),
    items_found_so_far: toNumber(payload.items_found_so_far, 0),
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

export { normalizeStatus };
