import { create } from 'zustand'

export interface AuthUser {
  id: number
  username: string
  name: string
  role: 'superadmin' | 'admin' | 'staff'
  is_active: boolean
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  isAuthenticated: boolean
  login: (token: string, user: AuthUser) => void
  logout: () => void
  loadFromStorage: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  isAuthenticated: false,

  login: (token, user) => {
    localStorage.setItem('sms-token', token)
    localStorage.setItem('sms-user', JSON.stringify(user))
    set({ token, user, isAuthenticated: true })
  },

  logout: () => {
    localStorage.removeItem('sms-token')
    localStorage.removeItem('sms-user')
    set({ token: null, user: null, isAuthenticated: false })
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('sms-token')
    const userStr = localStorage.getItem('sms-user')
    if (token && userStr) {
      try {
        const user = JSON.parse(userStr) as AuthUser
        set({ token, user, isAuthenticated: true })
      } catch {
        localStorage.removeItem('sms-token')
        localStorage.removeItem('sms-user')
      }
    }
  },
}))
