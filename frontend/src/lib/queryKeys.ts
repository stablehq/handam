function getTenantId(): string {
  return localStorage.getItem('sms-tenant-id') || 'unknown';
}

export const queryKeys = {
  reservations: {
    list: (date: string) => ['reservations', getTenantId(), date] as const,
    all: () => ['reservations', getTenantId()] as const, // for broad invalidation
  },
  rooms: {
    list: () => ['rooms', getTenantId()] as const,
    groups: () => ['roomGroups', getTenantId()] as const,
  },
  templates: {
    labels: () => ['templates', 'labels', getTenantId()] as const,
  },
  settings: {
    highlightColors: () => ['settings', 'highlightColors', getTenantId()] as const,
  },
} as const;
