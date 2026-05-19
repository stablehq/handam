function getTenantId(): string {
  return localStorage.getItem('sms-tenant-id') || 'unknown';
}

/**
 * Reservations 페이지 필터 객체 — list 와 별도 key 로 캐시 분리.
 * 필터/페이지 조합마다 다른 key → React Query 자동 캐시 격리.
 */
export interface ReservationFilters {
  page: number;
  pageSize?: number;
  status?: string;
  source?: string;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
}

/**
 * ActivityLogs 페이지 필터 객체.
 */
export interface ActivityLogFilters {
  type?: string;
  status?: string;
  date?: string;
  q?: string;
  page?: number;       // pagination 도 캐시 key 에 포함 (페이지 전환 시 자동 fetch + 재방문 캐시 hit)
  pageSize?: number;   // PAGE_SIZE 변경 가능성 대비
}

export const queryKeys = {
  // ========= 기존 (호환성 유지) =========
  reservations: {
    list: (date: string) => ['reservations', getTenantId(), date] as const,
    all: () => ['reservations', getTenantId()] as const,
    filtered: (filters: ReservationFilters) =>
      ['reservations', getTenantId(), 'filtered', filters] as const,
  },
  rooms: {
    list: () => ['rooms', getTenantId()] as const,
    groups: () => ['roomGroups', getTenantId()] as const,
    listWithInactive: () => ['rooms', getTenantId(), 'withInactive'] as const,
    bizItems: () => ['rooms', getTenantId(), 'bizItems'] as const,
    all: () => ['rooms', getTenantId()] as const,
  },
  templates: {
    labels: () => ['templates', 'labels', getTenantId()] as const,
    list: () => ['templates', getTenantId(), 'list'] as const,
    variables: () => ['templates', getTenantId(), 'variables'] as const,
    all: () => ['templates', getTenantId()] as const,
  },
  settings: {
    highlightColors: () => ['settings', 'highlightColors', getTenantId()] as const,
  },

  // ========= 신규 =========
  dashboard: {
    schedules: () => ['dashboard', getTenantId(), 'schedules'] as const,
    stats: () => ['dashboard', getTenantId(), 'stats'] as const,
    all: () => ['dashboard', getTenantId()] as const,
  },
  activityLogs: {
    list: (filters: ActivityLogFilters) =>
      ['activityLogs', getTenantId(), 'list', filters] as const,
    stats: () => ['activityLogs', getTenantId(), 'stats'] as const,
    all: () => ['activityLogs', getTenantId()] as const,
  },
  salesReport: {
    report: (dateFrom: string, dateTo: string) =>
      ['salesReport', getTenantId(), dateFrom, dateTo] as const,
    all: () => ['salesReport', getTenantId()] as const,
  },
  partyHosts: {
    list: () => ['partyHosts', getTenantId()] as const,
  },
  templateSchedules: {
    list: () => ['templateSchedules', getTenantId(), 'list'] as const,
    customTypes: () => ['templateSchedules', 'customTypes'] as const, // tenant-agnostic
    all: () => ['templateSchedules', getTenantId()] as const,
  },
  buildings: {
    list: () => ['buildings', getTenantId()] as const,
  },
  partyCheckin: {
    guests: (date: string, section: 'stable' | 'unstable') =>
      ['partyCheckin', getTenantId(), 'guests', date, section] as const,
    sales: (date: string) => ['partyCheckin', getTenantId(), 'sales', date] as const,
    host: (date: string) => ['partyCheckin', getTenantId(), 'host', date] as const,
    auction: (date: string) => ['partyCheckin', getTenantId(), 'auction', date] as const,
    review: (date: string) => ['partyCheckin', getTenantId(), 'review', date] as const,
    invites: (date: string) => ['partyCheckin', getTenantId(), 'invites', date] as const,
    all: () => ['partyCheckin', getTenantId()] as const,
  },
} as const;
