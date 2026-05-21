import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Outlet, Navigate } from 'react-router-dom'
import Layout, { ThemeProvider } from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { Toaster } from '@/components/ui/Sonner'
import { useAuthStore } from '@/stores/auth-store'
import { useTenantStore } from '@/stores/tenant-store'
import Dashboard from './pages/Dashboard'
import Reservations from './pages/Reservations'

import RoomAssignment from './pages/RoomAssignment'
import RoomSettings from './pages/RoomSettings'
import Templates from './pages/Templates'
import Login from './pages/Login'
import UserManagement from './pages/UserManagement'
import Settings from './pages/Settings'
import ActivityLogs from './pages/ActivityLogs'
import PartyCheckin from './pages/PartyCheckin'
import EventSms from './pages/EventSms'
import SalesReport from './pages/SalesReport'
import ConsecutiveStays from './pages/ConsecutiveStays'
import NotFound from './pages/NotFound'

// 스태프 전용 리다이렉트: staff 계정은 /party-checkin 으로만 이동
function StaffRedirect({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (user?.role === 'staff') {
    return <Navigate to="/party-checkin" replace />
  }
  if (user?.role === 'cleancrew') {
    return <Navigate to="/clean" replace />
  }
  return <>{children}</>
}

// cleancrew 는 /party-checkin 에 와도 /clean 로 강제 이동
function CleanCrewBlock({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (user?.role === 'cleancrew') {
    return <Navigate to="/clean" replace />
  }
  return <>{children}</>
}

function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)
  const loadTenants = useTenantStore((s) => s.loadTenants)

  useEffect(() => {
    loadFromStorage()
    loadTenants()
  }, [loadFromStorage, loadTenants])

  // Phase 3.2 — 다중 탭 인증 상태 동기화.
  // 같은 origin 의 다른 탭에서 sms-auth (또는 legacy 키) 변경 시 storage 이벤트 발화.
  // logout 만이 아닌 token refresh / 재로그인까지 모두 rehydrate 로 반영.
  // 같은 탭 내 변경에는 storage 이벤트 미발화 (브라우저 spec) → 자기 탭 무한 루프 없음.
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      // sms-auth 또는 legacy 키 변경에 모두 반응
      if (e.key === 'sms-auth' || e.key === 'sms-token' || e.key === 'sms-refresh-token' || e.key === 'sms-user' || e.key === null) {
        // 전체 storage 클리어(e.key === null) 도 포함
        useAuthStore.persist.rehydrate()
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  return (
    <ThemeProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <Layout>
                    <Outlet />
                  </Layout>
                </ProtectedRoute>
              }
            >
              {/* 스태프는 / 에 접근하면 /party-checkin 으로 리다이렉트 */}
              <Route path="/" element={<StaffRedirect><Dashboard /></StaffRedirect>} />
              <Route path="/reservations" element={<StaffRedirect><Reservations /></StaffRedirect>} />
              <Route path="/rooms" element={<StaffRedirect><RoomAssignment /></StaffRedirect>} />
              <Route path="/rooms/manage" element={<StaffRedirect><RoomSettings /></StaffRedirect>} />
              <Route path="/templates" element={<StaffRedirect><Templates /></StaffRedirect>} />
              <Route path="/settings" element={<StaffRedirect><Settings /></StaffRedirect>} />
              <Route path="/activity-logs" element={<StaffRedirect><ActivityLogs /></StaffRedirect>} />
              <Route path="/event-sms" element={<StaffRedirect><EventSms /></StaffRedirect>} />
              <Route path="/sales-report" element={<StaffRedirect><SalesReport /></StaffRedirect>} />
              <Route
                path="/users"
                element={
                  <ProtectedRoute requiredRoles={['superadmin', 'admin']}>
                    <UserManagement />
                  </ProtectedRoute>
                }
              />
              {/* 파티 체크인: 모든 역할 접근 가능 (cleancrew 만 /clean 로 리다이렉트) */}
              <Route path="/party-checkin" element={<CleanCrewBlock><PartyCheckin /></CleanCrewBlock>} />
              {/* 연박 객실: cleancrew 전용 (superadmin URL 직접 접근 허용, 사이드바 미노출) */}
              <Route
                path="/clean"
                element={
                  <ProtectedRoute requiredRoles={['superadmin', 'cleancrew']}>
                    <ConsecutiveStays />
                  </ProtectedRoute>
                }
              />
              {/* 404: 인증된 사용자가 잘못된 URL 진입 시. 미인증은 ProtectedRoute 가 /login 으로 먼저 리다이렉트 */}
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </Router>
        <Toaster position="top-right" richColors />
    </ThemeProvider>
  )
}

export default App
