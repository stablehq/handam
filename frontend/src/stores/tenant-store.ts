import { create } from 'zustand'
import { toast } from 'sonner'
import { tenantsAPI } from '@/services/api'

export interface Tenant {
  id: number
  name: string
  slug: string
  has_unstable?: boolean
}

interface TenantState {
  tenants: Tenant[]
  currentTenantId: string | null
  loadTenants: () => Promise<void>
  setCurrentTenantId: (tenantId: string) => void
}

const TENANT_KEY = 'sms-tenant-id'

export const useTenantStore = create<TenantState>((set) => ({
  tenants: [],
  currentTenantId: localStorage.getItem(TENANT_KEY),

  // store + localStorage 동시 갱신 — axios 인터셉터/queryKeys 의 localStorage 읽기와 일관성 보장
  setCurrentTenantId: (tenantId: string) => {
    localStorage.setItem(TENANT_KEY, tenantId)
    set({ currentTenantId: tenantId })
  },

  loadTenants: async () => {
    try {
      const res = await tenantsAPI.getAll()
      const tenants: Tenant[] = res.data
      const stored = localStorage.getItem(TENANT_KEY)

      // 1) stored ID 가 있고 + 응답 list 에 실제 존재 → 사용
      if (stored && tenants.some((t) => String(t.id) === stored)) {
        set({ tenants, currentTenantId: stored })
        return
      }

      // 2) stored ID 가 없거나 invalid + list 비어있지 않음 → 첫 번째 테넌트로 fallback
      //    (예전 hardcoded '1' 대신 실제 응답의 첫 항목 사용 — 존재 보장)
      if (tenants.length > 0) {
        const firstId = String(tenants[0].id)
        localStorage.setItem(TENANT_KEY, firstId)
        set({ tenants, currentTenantId: firstId })
        return
      }

      // 3) list 자체가 비어있음 → null. 강제 fallback 안 함 (없는 테넌트 ID 잠그기 방지).
      localStorage.removeItem(TENANT_KEY)
      set({ tenants: [], currentTenantId: null })
      window.__diagAction = 'tenant_list_empty'
    } catch {
      // API 실패 — 기존 stored 가 있으면 그대로 두고, 없으면 null. 강제 hardcoded fallback 안 함.
      const stored = localStorage.getItem(TENANT_KEY)
      if (!stored) {
        toast.error('테넌트 목록을 불러오지 못했습니다. 새로고침 후 다시 시도해주세요.', {
          id: 'tenant-load-failed',
        })
      }
      set({ currentTenantId: stored })
    }
  },
}))
