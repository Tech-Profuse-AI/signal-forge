import { api, API_BASE_URL } from './http';
import {
  normalizeMetrics,
  normalizeOpportunity,
  normalizeOpportunityList,
  normalizePipelineStatus,
} from './normalizers';

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

export function subscribePipelineEvents({ onEvent, onError } = {}) {
  if (typeof window === 'undefined' || typeof window.EventSource === 'undefined') {
    return () => {};
  }

  const source = new window.EventSource(`${API_BASE_URL}/pipeline/events`);
  const handleEvent = (message) => {
    if (!message.data) return;
    try {
      onEvent?.(JSON.parse(message.data));
    } catch (error) {
      onError?.(error);
    }
  };

  source.onmessage = handleEvent;
  source.addEventListener('pipeline_status', handleEvent);
  source.addEventListener('platform_batch', handleEvent);
  source.addEventListener('opportunity_state', handleEvent);
  source.addEventListener('pipeline_complete', handleEvent);
  source.addEventListener('pipeline_error', handleEvent);
  source.onerror = (error) => {
    onError?.(error);
  };

  return () => source.close();
}

export async function patchDraft({ id, draft }) {
  const { data } = await api.patch(`/items/${encodeId(id)}/draft`, { draft });
  return normalizeOpportunity(data);
}

export async function patchOpportunityStatus({ id, status }) {
  const { data } = await api.patch(`/items/${encodeId(id)}/status`, { status });
  return normalizeOpportunity({ ...data, status: data?.status || status });
}
