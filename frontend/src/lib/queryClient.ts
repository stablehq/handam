import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s default — overridden per-query for rooms/templates (5min)
      gcTime: 5 * 60_000, // 5 min cache retention
      retry: 1,
      refetchOnWindowFocus: true,
      refetchOnMount: true,
    },
    mutations: {
      retry: 0,
    },
  },
});
