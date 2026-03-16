import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Outlet } from 'react-router-dom'
import Layout, { ThemeProvider } from './components/Layout'
import FlowbiteWrapper from './components/FlowbiteTheme'
import ProtectedRoute from './components/ProtectedRoute'
import { Toaster } from '@/components/ui/Sonner'
import { useAuthStore } from '@/stores/auth-store'
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

function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)

  useEffect(() => {
    loadFromStorage()
  }, [loadFromStorage])

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
              <Route path="/" element={<Dashboard />} />
              <Route path="/reservations" element={<Reservations />} />
              <Route path="/rooms" element={<RoomAssignment />} />
              <Route path="/rooms/manage" element={<RoomSettings />} />
              <Route path="/messages" element={<Messages />} />
              <Route path="/auto-response" element={<AutoResponse />} />
              <Route path="/templates" element={<Templates />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/activity-logs" element={<ActivityLogs />} />
              <Route
                path="/users"
                element={
                  <ProtectedRoute requiredRoles={['superadmin', 'admin']}>
                    <UserManagement />
                  </ProtectedRoute>
                }
              />
            </Route>
          </Routes>
        </Router>
        <Toaster position="top-right" richColors />
      </FlowbiteWrapper>
    </ThemeProvider>
  )
}

export default App
