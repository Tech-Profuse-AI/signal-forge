import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchOpportunities,
  patchDraft,
  patchOpportunityStatus,
} from '../api/opportunities';
import { normalizeStatus } from '../api/normalizers';

export const opportunityKeys = {
  all: ['opportunities'],
  lists: () => ['opportunities', 'list'],
  pending: () => ['opportunities', 'list', 'pending'],
};

function updateOpportunityEverywhere(queryClient, updater) {
  queryClient.setQueriesData({ queryKey: opportunityKeys.lists() }, (oldData) => {
    if (!Array.isArray(oldData)) return oldData;
    return updater(oldData);
  });
}

function restoreQueries(queryClient, snapshots = []) {
  snapshots.forEach(([queryKey, data]) => {
    queryClient.setQueryData(queryKey, data);
  });
}

export function useOpportunities({ pollingInterval = 15000 } = {}) {
  return useQuery({
    queryKey: opportunityKeys.pending(),
    queryFn: fetchOpportunities,
    refetchInterval: pollingInterval,
  });
}

export function useUpdateDraftMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: patchDraft,
    onMutate: async ({ id, draft }) => {
      await queryClient.cancelQueries({ queryKey: opportunityKeys.lists() });
      const previous = queryClient.getQueriesData({ queryKey: opportunityKeys.lists() });

      updateOpportunityEverywhere(queryClient, (items) =>
        items.map((item) => (item.id === id ? { ...item, draft } : item)),
      );

      return { previous };
    },
    onError: (_error, _variables, context) => {
      restoreQueries(queryClient, context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: opportunityKeys.lists() });
    },
  });
}

export function useUpdateStatusMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: patchOpportunityStatus,
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: opportunityKeys.lists() });
      const previous = queryClient.getQueriesData({ queryKey: opportunityKeys.lists() });
      const nextStatus = normalizeStatus(status);

      updateOpportunityEverywhere(queryClient, (items) =>
        items
          .map((item) => (
            item.id === id
              ? { ...item, status: nextStatus, review_status: status }
              : item
          ))
          .filter((item) => !['rejected', 'published', 'posted'].includes(item.status)),
      );

      return { previous };
    },
    onError: (_error, _variables, context) => {
      restoreQueries(queryClient, context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: opportunityKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ['metrics'] });
    },
  });
}
