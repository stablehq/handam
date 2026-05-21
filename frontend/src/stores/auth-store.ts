import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface AuthUser {
  id: number
  username: string
  name: string
  role: 'superadmin' | 'admin' | 'staff' | 'cleancrew'
  active: boolean
}

interface PersistedAuthState {
  token: string | null
  refreshToken: string | null
  user: AuthUser | null
  isAuthenticated: boolean
}

interface AuthActions {
  login: (token: string, refreshToken: string, user: AuthUser) => void
  logout: () => void
  setTokens: (token: string, refreshToken: string) => void
  loadFromStorage: () => void
}

type AuthState = PersistedAuthState & AuthActions

// 신규 단일 storage 키 — 이전 sms-token/sms-refresh-token/sms-user 3개 키 통합
const STORAGE_KEY = 'sms-auth'
const STORAGE_VERSION = 2

const LEGACY_TOKEN_KEY = 'sms-token'
const LEGACY_REFRESH_KEY = 'sms-refresh-token'
const LEGACY_USER_KEY = 'sms-user'

/**
 * 모듈 로드 시 1회성 마이그레이션 — Phase 3 배포 직후 첫 페이지 로드에서 실행.
 *
 * 시나리오:
 * - 신규 사용자: localStorage 비어있음 → 아무것도 안 함
 * - legacy 사용자 (Phase 2 이전 로그인 유지): sms-token/sms-refresh-token/sms-user 존재
 *   → 새 STORAGE_KEY 로 통합 + legacy 키 제거. 강제 로그아웃 없음.
 * - 이미 마이그레이션된 사용자: STORAGE_KEY 존재 → 아무것도 안 함 (idempotent)
 * - 비정상 데이터 (JSON 파싱 실패): legacy 그대로 두고 종료. 기존 동작과 동일하게 logout 처리됨.
 */
function bootstrapMigration() {
  // 이미 새 키 있으면 skip (idempotent)
  if (localStorage.getItem(STORAGE_KEY)) return

  const token = localStorage.getItem(LEGACY_TOKEN_KEY)
  const refreshToken = localStorage.getItem(LEGACY_REFRESH_KEY)
  const userStr = localStorage.getItem(LEGACY_USER_KEY)
  if (!token || !userStr) return

  try {
    const user = JSON.parse(userStr) as AuthUser
    const persistedShape = {
      state: {
        token,
        refreshToken,
        user,
        isAuthenticated: true,
      },
      version: STORAGE_VERSION,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persistedShape))
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    localStorage.removeItem(LEGACY_REFRESH_KEY)
    localStorage.removeItem(LEGACY_USER_KEY)
  } catch {
    // 파싱 실패 — 잘못된 데이터. 그대로 둠. 다음 로그인 시 정리됨.
  }
}

bootstrapMigration()

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,

      login: (token, refreshToken, user) => {
        set({ token, refreshToken, user, isAuthenticated: true })
      },

      logout: () => {
        set({ token: null, refreshToken: null, user: null, isAuthenticated: false })
      },

      // api.ts interceptor 의 토큰 갱신 경로용 — store 경유로 persist 자동 동기화
      setTokens: (token, refreshToken) => {
        set({ token, refreshToken })
      },

      // 호환용 — App.tsx 가 부르고 있어 alias 로 유지. persist 가 자동 hydrate 라 사실상 no-op.
      loadFromStorage: () => {
        useAuthStore.persist.rehydrate()
      },
    }),
    {
      name: STORAGE_KEY,
      version: STORAGE_VERSION,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      // version bump 시 데이터 변환. 현재 v2 가 첫 버전이므로 기본 통과.
      migrate: (persistedState, _version) => {
        return persistedState as PersistedAuthState
      },
    }
  )
)
