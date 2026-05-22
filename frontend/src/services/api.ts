import axios from 'axios';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';

// 401 처리 후 ProtectedRoute 가 /login 으로 리다이렉트하도록 유도.
// 페이지 강제 리로드(window.location.href) 회피 — 작성 중인 폼/state 보존.
// 동시 요청 다수가 401 받을 때 toast 중복 방지: 고정 id 로 sonner 가 dedupe.
function handleAuthFailure(reason: 'no_refresh_token' | 'refresh_failed') {
  // 백엔드 diag 추적용 — 다음 axios 요청에 자동 첨부되지만 logout 직후라 발화 가능성 낮음.
  // 보존성 차원에서 세팅 (재로그인 직후 첫 요청에 실릴 수 있음).
  window.__diagAction = `auto_logout_${reason}`;
  useAuthStore.getState().logout();
  toast.error('세션이 만료되었습니다. 다시 로그인해주세요.', { id: 'session-expired' });
}

const api = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Auth interceptor - attach token (single source of truth = useAuthStore)
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const tenantId = localStorage.getItem('sms-tenant-id')
  if (tenantId) {
    config.headers['X-Tenant-Id'] = tenantId
  }
  return config
})

// DIAG_BLOCK_START: request correlation (refactor-2026-04)
// 주요 사용자 액션을 전역에 태그하고 다음 axios 요청에 자동 첨부
declare global {
  interface Window {
    __diagAction?: string;
  }
}

api.interceptors.request.use((config) => {
  // X-Request-ID 자동 생성 (8자 랜덤)
  if (!config.headers['X-Request-ID']) {
    config.headers['X-Request-ID'] = Math.random().toString(36).substring(2, 10);
  }
  // 최근 사용자 액션 첨부 (있으면)
  // HTTP 헤더는 ISO-8859-1 제약 — 한글 포함 (예: 객실명 '20평') 시 TypeError.
  // encodeURIComponent 로 ASCII-safe 화. 백엔드에서 unquote() 로 복원.
  const action = window.__diagAction;
  if (action) {
    config.headers['X-Diag-Action'] = encodeURIComponent(action);
    // 1회성으로 클리어 (다음 요청에 남지 않도록)
    window.__diagAction = undefined;
  }
  return config;
});
// DIAG_BLOCK_END

// Auth interceptor - handle 401 with refresh token
let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = []

function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (token) resolve(token)
    else reject(error)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && window.location.pathname !== '/login' && !originalRequest._retry) {
      const refreshToken = useAuthStore.getState().refreshToken

      if (!refreshToken) {
        handleAuthFailure('no_refresh_token')
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(api(originalRequest))
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
        // store 경유 — persist middleware 가 localStorage 자동 동기화
        useAuthStore.getState().setTokens(data.access_token, data.refresh_token)
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        processQueue(null, data.access_token)
        return api(originalRequest)
      } catch {
        processQueue(error, null)
        handleAuthFailure('refresh_failed')
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)


// ============================================================================
// API Payload 타입 — backend Pydantic 스키마와 1:1 매칭. update 는 Partial<> 활용.
// 일부 함수(reservationsAPI.update 등)는 동적 [field] 패턴 caller 호환성 위해
// any 유지. 점진적 타입화 (Phase 5.1).
// ============================================================================

export interface ReservationCreatePayload {
  customer_name: string
  phone: string
  check_in_date: string  // YYYY-MM-DD
  check_in_time: string  // HH:MM
  check_out_date?: string | null
  status?: string
  notes?: string | null
  gender?: string | null
  male_count?: number | null
  female_count?: number | null
  party_size?: number | null
  party_type?: string | null
  booking_source?: string
  naver_room_type?: string | null
  section?: string | null
}

export interface BizItemLinkPayload {
  biz_item_id: string
  male_priority?: number
  female_priority?: number
}

export interface RoomCreatePayload {
  room_number: string
  room_type: string
  base_capacity?: number
  max_capacity?: number
  active?: boolean
  sort_order?: number
  naver_biz_item_id?: string | null
  biz_item_ids?: string[] | null
  biz_item_links?: BizItemLinkPayload[] | null
  building_id?: number | null
  dormitory?: boolean
  bed_capacity?: number
  door_password?: string | null
  room_memo?: string | null
}

export type RoomUpdatePayload = Partial<RoomCreatePayload>

export interface TemplateCreatePayload {
  template_key: string
  name: string
  short_label?: string | null
  content: string
  variables?: string
  category?: string
  active?: boolean
  participant_buffer?: number | null
}

export type TemplateUpdatePayload = Partial<TemplateCreatePayload>

export interface TemplateScheduleCreatePayload {
  template_id: number
  schedule_name: string
  schedule_type: string
  hour?: number
  minute?: number
  day_of_week?: string
  interval_minutes?: number
  timezone?: string
  filters?: Array<{ type: string; value: string }>
  exclude_sent?: boolean
  active?: boolean
  schedule_category?: 'standard' | 'event' | 'custom_schedule'
  custom_type?: string | null
  hours_since_booking?: number | null
  gender_filter?: 'male' | 'female' | null
  max_checkin_days?: number | null
  expires_after_days?: number | null
  send_condition_date?: string | null
  send_condition_ratio?: number | null
  send_condition_operator?: string | null
}

export type TemplateScheduleUpdatePayload = Partial<TemplateScheduleCreatePayload>

// Reservations API
export const reservationsAPI = {
  getAll: (params?: { skip?: number; limit?: number; status?: string; date?: string; search?: string; source?: string }) =>
    api.get('/api/reservations', { params }),
  create: (data: ReservationCreatePayload) => api.post('/api/reservations', data),
  // update: 동적 [field] 패턴 caller (RoomAssignment.tsx:631) 호환성 위해 any 유지.
  // 백엔드 ReservationUpdate 스키마 기준 Partial 적용 시 caller 측 cast 필요 — 별도 작업.
  update: (id: number, data: any) => api.put(`/api/reservations/${id}`, data),
  delete: (id: number) => api.delete(`/api/reservations/${id}`),
  assignRoom: (id: number, data: { room_id: number | null; date?: string; apply_subsequent?: boolean; apply_group?: boolean }) =>
    api.put(`/api/reservations/${id}/room`, data),
  syncNaver: (fromDate?: string) => api.post('/api/reservations/sync/naver', null, { params: fromDate ? { from_date: fromDate } : undefined }),
  updateDailyInfo: (id: number, data: { date: string; party_type?: string | null; notes?: string | null; unstable_party?: boolean }) =>
    api.put(`/api/reservations/${id}/daily-info`, data),
  smsSendByTag: (data: { template_key: string; date: string }) =>
    api.post('/api/reservations/sms-send-by-tag', data),
  extendStay: (reservationId: number, payload: { room_id: number | null }) =>
    api.post(`/api/reservations/${reservationId}/extend-stay`, payload),
  cancelExtendStay: (reservationId: number) =>
    api.delete(`/api/reservations/${reservationId}/extend-stay`),
  /** New model: reduce manually_extended_until by N days (default 1). */
  reduceExtension: (reservationId: number, days: number = 1) =>
    api.post(`/api/reservations/${reservationId}/reduce-extension`, { days }),
  assignExtendStayRoom: (reservationId: number, payload: { new_reservation_id: number; room_id: number; date: string }) =>
    api.post(`/api/reservations/${reservationId}/extend-stay/assign-room`, payload),
};

// Rooms API
export const roomsAPI = {
  getAll: (params?: { include_inactive?: boolean }) => api.get('/api/rooms', { params }),
  create: (data: RoomCreatePayload) => api.post('/api/rooms', data),
  update: (id: number, data: RoomUpdatePayload) => api.put(`/api/rooms/${id}`, data),
  reorder: (orderedIds: number[]) =>
    api.post('/api/rooms/reorder', { ordered_ids: orderedIds }),
  delete: (id: number) => api.delete(`/api/rooms/${id}`),
  hide: (id: number) => api.post(`/api/rooms/${id}/hide`),
  unhide: (id: number) => api.post(`/api/rooms/${id}/unhide`),
  getBizItems: () => api.get('/api/rooms/naver/biz-items'),
  syncBizItems: () => api.post('/api/rooms/naver/biz-items/sync'),
  updateBizItems: (items: Array<{biz_item_id: string; display_name?: string | null; default_capacity?: number | null; section_hint?: string | null; default_party_type?: string | null; grade?: number | null}>) =>
    api.patch('/api/rooms/naver/biz-items', items),
  updateRoomGrades: (items: Array<{id: number; grade: number}>) =>
    api.patch('/api/rooms/grades', items),
  autoAssign: (date?: string) => api.post('/api/rooms/auto-assign', null, { params: date ? { date } : undefined }),
  // Room Groups
  getGroups: () => api.get('/api/rooms/groups'),
  createGroup: (data: { name: string; sort_order?: number; color?: string; room_ids?: number[] }) => api.post('/api/rooms/groups', data),
  updateGroup: (id: number, data: { name?: string; sort_order?: number; color?: string; room_ids?: number[] }) => api.put(`/api/rooms/groups/${id}`, data),
  deleteGroup: (id: number) => api.delete(`/api/rooms/groups/${id}`),
};

// Dashboard API
export const dashboardAPI = {
  getStats: () => api.get('/api/dashboard/stats'),
  getTodaySchedules: () => api.get('/api/dashboard/today-schedules'),
};

// Templates API
export const templatesAPI = {
  getAll: (params?: { category?: string; active?: boolean }) =>
    api.get('/api/templates', { params }),
  getById: (id: number) => api.get(`/api/templates/${id}`),
  create: (data: TemplateCreatePayload) => api.post('/api/templates', data),
  update: (id: number, data: TemplateUpdatePayload) => api.put(`/api/templates/${id}`, data),
  reorder: (orderedIds: number[]) =>
    api.post('/api/templates/reorder', { ordered_ids: orderedIds }),
  delete: (id: number) => api.delete(`/api/templates/${id}`),
  preview: (id: number, variables: any) =>
    api.post(`/api/templates/${id}/preview`, { variables }),
  getAvailableVariables: () => api.get('/api/template-variables'),
  getLabels: () => api.get('/api/templates/labels'),
};

export const smsAssignmentsAPI = {
  assign: (reservationId: number, data: { template_key: string; date?: string }) =>
    api.post(`/api/reservations/${reservationId}/sms-assign`, data),
  remove: (reservationId: number, templateKey: string, date?: string) =>
    api.delete(`/api/reservations/${reservationId}/sms-assign/${templateKey}`, { params: date ? { date } : undefined }),
  toggle: (reservationId: number, templateKey: string, skipSend?: boolean, date?: string) =>
    api.patch(`/api/reservations/${reservationId}/sms-toggle/${templateKey}`, null, { params: { ...(skipSend ? { skip_send: true } : {}), ...(date ? { date } : {}) } }),
};

// Template Schedules API
export const templateSchedulesAPI = {
  getAll: (params?: { active?: boolean; template_id?: number }) =>
    api.get('/api/template-schedules', { params }),
  getById: (id: number) => api.get(`/api/template-schedules/${id}`),
  create: (data: TemplateScheduleCreatePayload) => api.post('/api/template-schedules', data),
  update: (id: number, data: TemplateScheduleUpdatePayload) => api.put(`/api/template-schedules/${id}`, data),
  delete: (id: number) => api.delete(`/api/template-schedules/${id}`),
  run: (id: number) => api.post(`/api/template-schedules/${id}/run`),
  preview: (id: number) => api.get(`/api/template-schedules/${id}/preview`),
  sync: () => api.post('/api/template-schedules/sync'),
  autoAssign: (date?: string) =>
    api.post('/api/template-schedules/auto-assign', null, { params: date ? { date } : undefined }),
  getCustomTypes: () => api.get<Array<{ value: string; label: string }>>('/api/template-schedules/custom-types'),
};

// Auth API
export const authAPI = {
  login: (data: { username: string; password: string }) =>
    api.post('/api/auth/login', data),
  me: () => api.get('/api/auth/me'),
  getUsers: () => api.get('/api/auth/users'),
  createUser: (data: { username: string; password: string; name: string; role: string }) =>
    api.post('/api/auth/users', data),
  updateUser: (id: number, data: any) => api.put(`/api/auth/users/${id}`, data),
  deleteUser: (id: number) => api.delete(`/api/auth/users/${id}`),
}

// Activity Logs API
export const activityLogsAPI = {
  getAll: (params?: { type?: string; status?: string; date?: string; skip?: number; limit?: number }) =>
    api.get('/api/activity-logs', { params }),
  getStats: () => api.get('/api/activity-logs/stats'),
};

// Buildings API
export const buildingsAPI = {
  getAll: () => api.get('/api/buildings'),
  create: (data: any) => api.post('/api/buildings', data),
  update: (id: number, data: any) => api.put(`/api/buildings/${id}`, data),
  delete: (id: number) => api.delete(`/api/buildings/${id}`),
};

// Settings API
export const settingsAPI = {
  getNaverStatus: () => api.get('/api/settings/naver/status'),
  updateNaverCookie: (cookie: string) =>
    api.post('/api/settings/naver/cookie', { cookie }),
  clearNaverCookie: () => api.delete('/api/settings/naver/cookie'),
  // Unstable
  getUnstableStatus: () => api.get('/api/settings/unstable/status'),
  updateUnstableSettings: (data: { business_id?: string; cookie?: string }) =>
    api.post('/api/settings/unstable/settings', data),
  syncUnstable: () => api.post('/api/settings/unstable/sync'),
  // Custom highlight colors
  getHighlightColors: () => api.get('/api/settings/highlight-colors'),
  updateHighlightColors: (colors: string[]) =>
    api.put('/api/settings/highlight-colors', { colors }),

};

// Party Check-in API
export const partyCheckinAPI = {
  getList: (date: string, partySource?: string) =>
    api.get('/api/party-checkin', { params: { date, ...(partySource ? { party_source: partySource } : {}) } }),
  toggle: (reservationId: number, date: string) =>
    api.patch(`/api/party-checkin/${reservationId}/toggle`, null, { params: { date } }),
};

// Tenants API
export const tenantsAPI = {
  getAll: () => api.get('/api/tenants'),
};

// Stay Group API
export const stayGroupAPI = {
  link: (id: number, reservationIds: number[]) =>
    api.post(`/api/reservations/${id}/stay-group/link`, { reservation_ids: reservationIds }),
  unlink: (id: number) =>
    api.delete(`/api/reservations/${id}/stay-group/unlink`),
};

// Event SMS API
export const eventSmsAPI = {
  search: (params: {
    date_from: string;
    date_to: string;
    gender?: string | null;
    min_nights?: number | null;
    max_nights?: number | null;
    min_visits?: number | null;
    max_visits?: number | null;
    exclude_age_groups?: string[] | null;
    exclude_invite?: boolean;
  }) => api.post('/api/event-sms/search', params),

  send: (params: {
    phones: string[];
    message: string;
    title?: string;
  }) => api.post('/api/event-sms/send', params),
};

// Sales Report API
export const salesReportAPI = {
  get: (params: {
    date_from: string;
    date_to: string;
    category?: string | null;
    biz_item_name?: string | null;
    item_name?: string | null;
    group_by?: string;
  }) => api.get('/api/sales-report', { params }),
};

// Onsite Sales API
export const onsiteSalesAPI = {
  getList: (date: string) => api.get('/api/onsite-sales', { params: { date } }),
  create: (data: { date: string; item_name: string; amount: number; payment_method: '카드' | '이체' | '현금' }) =>
    api.post('/api/onsite-sales', data),
  delete: (id: number) => api.delete(`/api/onsite-sales/${id}`),
};

// Daily Host API
export const dailyHostAPI = {
  get: (date: string) => api.get('/api/daily-host', { params: { date } }),
  upsert: (data: { date: string; host_username: string }) =>
    api.put('/api/daily-host', data),
};

// Party Hosts API
export const partyHostsAPI = {
  list: () => api.get('/api/party-hosts'),
  create: (data: { name: string }) => api.post('/api/party-hosts', data),
  delete: (id: number) => api.delete(`/api/party-hosts/${id}`),
};

// Onsite Auction API
export const onsiteAuctionAPI = {
  get: (date: string) => api.get('/api/onsite-auctions', { params: { date } }),
  upsert: (data: { date: string; item_name: string; final_amount: number; winner_name: string; payment_method: '카드' | '이체' | '현금' }) =>
    api.post('/api/onsite-auctions', data),
  delete: (id: number) => api.delete(`/api/onsite-auctions/${id}`),
};

// Daily Review API
export const dailyReviewAPI = {
  get: (date: string) => api.get('/api/daily-review', { params: { date } }),
  upsert: (data: { date: string; count: number }) =>
    api.put('/api/daily-review', data),
};

// Onsite Female Invite API
export const onsiteFemaleInviteAPI = {
  list: (date: string) => api.get('/api/onsite-female-invites', { params: { date } }),
  add: (data: { date: string; host_username: string; count: number }) =>
    api.post('/api/onsite-female-invites', data),
  update: (id: number, data: { host_username?: string; count?: number }) =>
    api.patch(`/api/onsite-female-invites/${id}`, data),
  delete: (id: number) => api.delete(`/api/onsite-female-invites/${id}`),
};

// Clean crew API
export interface CleanSkipRoom {
  room_number: string
  is_dormitory: boolean
  stayover_count?: number | null
  capacity?: number | null
}
export const cleancrewAPI = {
  listConsecutiveStays: () => api.get<CleanSkipRoom[]>('/api/clean'),
};

export default api;
