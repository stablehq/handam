import axios from 'axios';

const api = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Auth interceptor - attach token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('sms-token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Auth interceptor - handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('sms-token')
      localStorage.removeItem('sms-user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Messages API
export const messagesAPI = {
  getAll: (params?: { skip?: number; limit?: number; direction?: string; phone?: string }) =>
    api.get('/api/messages', { params }),
  getContacts: () => api.get('/api/messages/contacts'),
  send: (data: { to: string; message: string }) =>
    api.post('/api/messages/send', data),
  getReviewQueue: () => api.get('/api/messages/review-queue'),
  simulateReceive: (data: { from_: string; to: string; message: string }) =>
    api.post('/webhooks/sms/receive', data),
};

// Reservations API
export const reservationsAPI = {
  getAll: (params?: { skip?: number; limit?: number; status?: string; date?: string }) =>
    api.get('/api/reservations', { params }),
  create: (data: any) => api.post('/api/reservations', data),
  update: (id: number, data: any) => api.put(`/api/reservations/${id}`, data),
  delete: (id: number) => api.delete(`/api/reservations/${id}`),
  assignRoom: (id: number, data: { room_number: string | null; date?: string; apply_subsequent?: boolean }) =>
    api.put(`/api/reservations/${id}/room`, data),
  syncNaver: () => api.post('/api/reservations/sync/naver'),
};

// Rooms API
export const roomsAPI = {
  getAll: (params?: { include_inactive?: boolean }) => api.get('/api/rooms', { params }),
  create: (data: { room_number: string; room_type: string; is_active?: boolean; sort_order?: number }) =>
    api.post('/api/rooms', data),
  update: (id: number, data: any) => api.put(`/api/rooms/${id}`, data),
  delete: (id: number) => api.delete(`/api/rooms/${id}`),
  getBizItems: () => api.get('/api/rooms/naver/biz-items'),
  syncBizItems: () => api.post('/api/rooms/naver/biz-items/sync'),
  updateBizItem: (bizItemId: string, data: { is_dormitory?: boolean; dormitory_beds?: number | null }) =>
    api.put(`/api/rooms/naver/biz-items/${bizItemId}`, data),
  autoAssign: (date?: string) => api.post('/api/rooms/auto-assign', null, { params: date ? { date } : undefined }),
};

// Rules API
export const rulesAPI = {
  getAll: () => api.get('/api/rules'),
  create: (data: any) => api.post('/api/rules', data),
  update: (id: number, data: any) => api.put(`/api/rules/${id}`, data),
  delete: (id: number) => api.delete(`/api/rules/${id}`),
};

// Documents API
export const documentsAPI = {
  getAll: () => api.get('/api/documents'),
  upload: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  delete: (id: number) => api.delete(`/api/documents/${id}`),
};

// Auto-response API
export const autoResponseAPI = {
  generate: (messageId: number) =>
    api.post('/api/auto-response/generate', { message_id: messageId }),
  test: (message: string) =>
    api.post('/api/auto-response/test', { message }),
  reloadRules: () => api.post('/api/auto-response/reload-rules'),
};

// Dashboard API
export const dashboardAPI = {
  getStats: () => api.get('/api/dashboard/stats'),
};

// Campaigns API
export const campaignsAPI = {
  // New independent campaign APIs
  getList: () => api.get('/api/campaigns/list'),
  send: (data: { campaign_type: string; date?: string; variables?: any }) =>
    api.post('/api/campaigns/send', data),
  preview: (campaignType: string, date?: string) =>
    api.get('/api/campaigns/preview', { params: { campaign_type: campaignType, date } }),

  getHistory: (params?: { skip?: number; limit?: number }) =>
    api.get('/api/campaigns/history', { params }),
};

// Scheduler API
export const schedulerAPI = {
  getJobs: () => api.get('/api/scheduler/jobs'),
  runJob: (jobId: string) => api.post(`/api/scheduler/jobs/${jobId}/run`),
  pauseJob: (jobId: string) => api.post(`/api/scheduler/jobs/${jobId}/pause`),
  resumeJob: (jobId: string) => api.post(`/api/scheduler/jobs/${jobId}/resume`),
  getStatus: () => api.get('/api/scheduler/status'),
};

// Templates API
export const templatesAPI = {
  getAll: (params?: { category?: string; active?: boolean }) =>
    api.get('/api/templates', { params }),
  getById: (id: number) => api.get(`/api/templates/${id}`),
  create: (data: {
    key: string;
    name: string;
    short_label?: string | null;
    content: string;
    variables?: string;
    category?: string;
    active?: boolean;
  }) => api.post('/api/templates', data),
  update: (id: number, data: any) => api.put(`/api/templates/${id}`, data),
  delete: (id: number) => api.delete(`/api/templates/${id}`),
  preview: (id: number, variables: any) =>
    api.post(`/api/templates/${id}/preview`, { variables }),
  getAvailableVariables: () => api.get('/api/template-variables'),
  getLabels: () => api.get('/api/templates/labels'),
};

export const smsAssignmentsAPI = {
  assign: (reservationId: number, data: { template_key: string }) =>
    api.post(`/api/reservations/${reservationId}/sms-assign`, data),
  remove: (reservationId: number, templateKey: string) =>
    api.delete(`/api/reservations/${reservationId}/sms-assign/${templateKey}`),
  toggle: (reservationId: number, templateKey: string) =>
    api.patch(`/api/reservations/${reservationId}/sms-toggle/${templateKey}`),
};

// Template Schedules API
export const templateSchedulesAPI = {
  getAll: (params?: { active?: boolean; template_id?: number }) =>
    api.get('/api/template-schedules', { params }),
  getById: (id: number) => api.get(`/api/template-schedules/${id}`),
  create: (data: {
    template_id: number;
    schedule_name: string;
    schedule_type: string;
    hour?: number;
    minute?: number;
    day_of_week?: string;
    interval_minutes?: number;
    timezone?: string;
    target_type: string;
    target_value?: string;
    date_filter?: string;
    exclude_sent?: boolean;
    active?: boolean;
  }) => api.post('/api/template-schedules', data),
  update: (id: number, data: any) => api.put(`/api/template-schedules/${id}`, data),
  delete: (id: number) => api.delete(`/api/template-schedules/${id}`),
  run: (id: number) => api.post(`/api/template-schedules/${id}/run`),
  preview: (id: number) => api.get(`/api/template-schedules/${id}/preview`),
  sync: () => api.post('/api/template-schedules/sync'),
  autoAssign: (date?: string) =>
    api.post('/api/template-schedules/auto-assign', null, { params: date ? { date } : undefined }),
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

// Settings API
export const settingsAPI = {
  getNaverStatus: () => api.get('/api/settings/naver/status'),
  updateNaverCookie: (cookie: string) =>
    api.post('/api/settings/naver/cookie', { cookie }),
  clearNaverCookie: () => api.delete('/api/settings/naver/cookie'),
  getBookmarklet: () => api.get('/api/settings/naver/bookmarklet'),
};

export default api;
