import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { normalizePipelineStatus } from '../api/normalizers';
import { fetchPipelineStatus, runScan, subscribePipelineEvents } from '../api/opportunities';
import { opportunityKeys } from './useOpportunities';

export function usePipelineStatus() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubscribe = subscribePipelineEvents({
      onEvent: (event) => {
        const status = event?.payload?.status;
        if (status) {
          queryClient.setQueryData(['pipelineStatus'], normalizePipelineStatus(status));
        } else {
          queryClient.invalidateQueries({ queryKey: ['pipelineStatus'] });
        }

        if (event?.type === 'pipeline_complete' || event?.type === 'pipeline_error') {
          queryClient.invalidateQueries({ queryKey: opportunityKeys.lists() });
          queryClient.invalidateQueries({ queryKey: ['metrics'] });
        }
      },
    });

    return unsubscribe;
  }, [queryClient]);

  return useQuery({
    queryKey: ['pipelineStatus'],
    queryFn: fetchPipelineStatus,
    refetchInterval: (query) => (query.state.data?.running ? 1000 : 10000),
  });
}

export function useRunScanMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: runScan,
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: opportunityKeys.lists() });
      queryClient.setQueryData(opportunityKeys.pending(), []);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelineStatus'] });
      queryClient.invalidateQueries({ queryKey: opportunityKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ['metrics'] });
    },
  });
}
