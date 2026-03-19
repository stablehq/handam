import { create } from 'zustand'
import { tenantsAPI } from '@/services/api'

export interface Tenant {
  id: number
  name: string
  slug: string
}

interface TenantState {
  tenants: Tenant[]
  currentTenantId: string | null
  loadTenants: () => Promise<void>
}

export const useTenantStore = create<TenantState>((set) => ({
  tenants: [],
  currentTenantId: localStorage.getItem('sms-tenant-id'),

  loadTenants: async () => {
    try {
      const res = await tenantsAPI.getAll()
      const tenants: Tenant[] = res.data
      // Default to first tenant if none selected
      if (!localStorage.getItem('sms-tenant-id') && tenants.length > 0) {
        localStorage.setItem('sms-tenant-id', String(tenants[0].id))
        set({ tenants, currentTenantId: String(tenants[0].id) })
      } else {
        set({ tenants })
      }
    } catch {
      // If tenants endpoint not available, default to handam (id=1)
      if (!localStorage.getItem('sms-tenant-id')) {
        localStorage.setItem('sms-tenant-id', '1')
      }
      set({ currentTenantId: localStorage.getItem('sms-tenant-id') })
    }
  },
}))
