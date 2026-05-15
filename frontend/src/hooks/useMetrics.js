import { useQuery } from '@tanstack/react-query';
import { fetchMetrics } from '../api/opportunities';

export function useMetrics() {
  return useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 30000,
  });
}
