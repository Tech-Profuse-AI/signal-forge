import { api } from './http';
import {
  normalizeMetrics,
  normalizeOpportunity,
  normalizeOpportunityList,
  normalizePipelineStatus,
} from './normalizers';

const LEGACY_STATUS_FALLBACKS = {
  approved: 'posted',
  published: 'posted',
  rejected: 'skipped',
};

function shouldFallbackDraftEndpoint(error) {
  const status = error?.response?.status;
  return status === 404 || status === 405;
}

function shouldFallbackStatus(error) {
  const status = error?.response?.status;
  return status === 400 || status === 404 || status === 405 || status === 422;
}

function encodeId(id) {
  return encodeURIComponent(id);
}

export async function fetchOpportunities() {
  const { data } = await api.get('/items/pending');
  return normalizeOpportunityList(data);
}

export async function fetchMetrics() {
  const { data } = await api.get('/metrics');
  return normalizeMetrics(data);
}

export async function fetchPipelineStatus() {
  const { data } = await api.get('/pipeline/status');
  return normalizePipelineStatus(data);
}

export async function fetchHealth() {
  const { data } = await api.get('/health');
  return data;
}

export async function runScan(query) {
  const { data } = await api.post('/pipeline/run', { query });
  return data;
}

export async function patchDraft({ id, draft }) {
  try {
    const { data } = await api.patch(`/drafts/${encodeId(id)}`, { draft });
    return normalizeOpportunity(data);
  } catch (error) {
    if (!shouldFallbackDraftEndpoint(error)) {
      throw error;
    }

    const { data } = await api.patch(`/items/${encodeId(id)}/draft`, { draft });
    return normalizeOpportunity(data);
  }
}

export async function patchOpportunityStatus({ id, status }) {
  try {
    const { data } = await api.patch(`/items/${encodeId(id)}/status`, { status });
    return normalizeOpportunity({ ...data, status: data?.status || status });
  } catch (error) {
    const fallbackStatus = LEGACY_STATUS_FALLBACKS[status];
    if (!fallbackStatus || !shouldFallbackStatus(error)) {
      throw error;
    }

    const { data } = await api.patch(`/items/${encodeId(id)}/status`, {
      status: fallbackStatus,
    });
    return normalizeOpportunity({ ...data, status: data?.status || fallbackStatus });
  }
}
