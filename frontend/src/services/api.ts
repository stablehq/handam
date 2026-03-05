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
  assignRoom: (id: number, data: { room_number: string | null }) =>
    api.put(`/api/reservations/${id}/room`, data),
  syncNaver: () => api.post('/api/reservations/sync/naver'),
  syncSheets: () => api.post('/api/reservations/sync/sheets'),
};

// Rooms API
export const roomsAPI = {
  getAll: (params?: { include_inactive?: boolean }) => api.get('/api/rooms', { params }),
  getById: (id: number) => api.get(`/api/rooms/${id}`),
  create: (data: { room_number: string; room_type: string; is_active?: boolean; sort_order?: number }) =>
    api.post('/api/rooms', data),
  update: (id: number, data: any) => api.put(`/api/rooms/${id}`, data),
  delete: (id: number) => api.delete(`/api/rooms/${id}`),
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
  getList: () => api.get('/campaigns/list'),
  send: (data: { campaign_type: string; date?: string; variables?: any }) =>
    api.post('/campaigns/send', data),
  preview: (campaignType: string, date?: string) =>
    api.get('/campaigns/preview', { params: { campaign_type: campaignType, date } }),

  // Legacy APIs
  getTargets: (tag: string, smsType: string = 'room', date?: string) =>
    api.get('/campaigns/targets', { params: { tag, sms_type: smsType, date } }),
  sendByTag: (data: { tag: string; template_key: string; variables?: any; sms_type?: string; date?: string }) =>
    api.post('/campaigns/send-by-tag', data),
  getHistory: (params?: { skip?: number; limit?: number }) =>
    api.get('/campaigns/history', { params }),
  getTemplates: () => api.get('/campaigns/templates'),
  sendRoomGuide: (data: { date?: string }) =>
    api.post('/campaigns/notifications/room-guide', data),
  sendPartyGuide: (data: { date?: string }) =>
    api.post('/campaigns/notifications/party-guide', data),
};

// Scheduler API
export const schedulerAPI = {
  getJobs: () => api.get('/scheduler/jobs'),
  runJob: (jobId: string) => api.post(`/scheduler/jobs/${jobId}/run`),
  pauseJob: (jobId: string) => api.post(`/scheduler/jobs/${jobId}/pause`),
  resumeJob: (jobId: string) => api.post(`/scheduler/jobs/${jobId}/resume`),
  getStatus: () => api.get('/scheduler/status'),
};

// Gender Stats API
export const genderStatsAPI = {
  get: (date?: string) => api.get('/campaigns/gender-stats', { params: { date } }),
  getHistory: (days?: number) =>
    api.get('/campaigns/gender-stats/history', { params: { days } }),
  refresh: (date?: string) => api.post('/campaigns/gender-stats/refresh', null, { params: { date } }),
};

// Templates API
export const templatesAPI = {
  getAll: (params?: { category?: string; active?: boolean }) =>
    api.get('/api/templates', { params }),
  getById: (id: number) => api.get(`/api/templates/${id}`),
  create: (data: {
    key: string;
    name: string;
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
    sms_type?: string;
    exclude_sent?: boolean;
    active?: boolean;
  }) => api.post('/api/template-schedules', data),
  update: (id: number, data: any) => api.put(`/api/template-schedules/${id}`, data),
  delete: (id: number) => api.delete(`/api/template-schedules/${id}`),
  run: (id: number) => api.post(`/api/template-schedules/${id}/run`),
  preview: (id: number) => api.get(`/api/template-schedules/${id}/preview`),
  sync: () => api.post('/api/template-schedules/sync'),
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

export default api;
