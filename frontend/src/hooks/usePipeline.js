import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchPipelineStatus, runScan } from '../api/opportunities';
import { opportunityKeys } from './useOpportunities';

export function usePipelineStatus() {
  return useQuery({
    queryKey: ['pipelineStatus'],
    queryFn: fetchPipelineStatus,
    refetchInterval: 3000,
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
