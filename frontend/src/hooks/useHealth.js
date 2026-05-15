import { useQuery } from '@tanstack/react-query';
import { fetchHealth } from '../api/opportunities';

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });
}
