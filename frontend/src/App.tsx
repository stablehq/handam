import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Outlet, Navigate } from 'react-router-dom'
import Layout, { ThemeProvider } from './components/Layout'
import FlowbiteWrapper from './components/FlowbiteTheme'
import ProtectedRoute from './components/ProtectedRoute'
import { Toaster } from '@/components/ui/Sonner'
import { useAuthStore } from '@/stores/auth-store'
import { useTenantStore } from '@/stores/tenant-store'
import Dashboard from './pages/Dashboard'
import Reservations from './pages/Reservations'
import Messages from './pages/Messages'
import AutoResponse from './pages/AutoResponse'
import RoomAssignment from './pages/RoomAssignment'
import RoomSettings from './pages/RoomSettings'
import Templates from './pages/Templates'
import Login from './pages/Login'
import UserManagement from './pages/UserManagement'
import Settings from './pages/Settings'
import ActivityLogs from './pages/ActivityLogs'
import PartyCheckin from './pages/PartyCheckin'

// 스태프 전용 리다이렉트: staff 계정은 /party-checkin 으로만 이동
function StaffRedirect({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (user?.role === 'staff') {
    return <Navigate to="/party-checkin" replace />
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

  return (
    <ThemeProvider>
      <FlowbiteWrapper>
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
              <Route path="/messages" element={<StaffRedirect><Messages /></StaffRedirect>} />
              <Route path="/auto-response" element={<StaffRedirect><AutoResponse /></StaffRedirect>} />
              <Route path="/templates" element={<StaffRedirect><Templates /></StaffRedirect>} />
              <Route path="/settings" element={<StaffRedirect><Settings /></StaffRedirect>} />
              <Route path="/activity-logs" element={<StaffRedirect><ActivityLogs /></StaffRedirect>} />
              <Route
                path="/users"
                element={
                  <ProtectedRoute requiredRoles={['superadmin', 'admin']}>
                    <UserManagement />
                  </ProtectedRoute>
                }
              />
              {/* 파티 체크인: 모든 역할 접근 가능 */}
              <Route path="/party-checkin" element={<PartyCheckin />} />
            </Route>
          </Routes>
        </Router>
        <Toaster position="top-right" richColors />
      </FlowbiteWrapper>
    </ThemeProvider>
  )
}

export default App
