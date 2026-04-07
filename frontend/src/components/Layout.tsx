import { useState, useEffect, createContext, useContext } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'
import { useAuthStore } from '@/stores/auth-store'
import { useTenantStore } from '@/stores/tenant-store'
import { Badge } from '@/components/ui/badge'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  CalendarRange,
  BedDouble,
  Settings2,
  Settings,
  FileText,
  Megaphone,
  PanelLeftClose,
  PanelLeft,
  Menu,
  Sun,
  Moon,
  Users,
  LogOut,
  History,
  PartyPopper,
  X,
  ChevronsUpDown,
} from 'lucide-react'

// ── Theme Context ──
const ThemeContext = createContext<{
  theme: 'light' | 'dark'
  toggle: () => void
}>({ theme: 'light', toggle: () => {} })

export const useTheme = () => useContext(ThemeContext)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('sms-theme')
    return (saved === 'dark' ? 'dark' : 'light') as 'light' | 'dark'
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('sms-theme', theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

// ── Theme Toggle Button ──
function ThemeToggleButton() {
  const { theme, toggle } = useTheme()
  return (
    <button
      onClick={toggle}
      className="rounded-xl p-2 text-[#B0B8C1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
      aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
    >
      {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

// ── Navigation Config ──
interface NavItem {
  path: string
  label: string
  icon: React.ReactNode
}

interface NavGroup {
  title: string
  items: NavItem[]
  requiredRoles?: string[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: '파티',
    items: [
      { path: '/party-checkin', label: '파티 입장 체크', icon: <PartyPopper size={18} /> },
    ],
    requiredRoles: ['staff'],
  },
  {
    title: '',
    items: [
      { path: '/', label: '대시보드', icon: <LayoutDashboard size={18} /> },
    ],
    requiredRoles: ['superadmin', 'admin'],
  },
  {
    title: '객실 / 파티',
    items: [
      { path: '/reservations', label: '예약 관리', icon: <CalendarRange size={18} /> },
      { path: '/rooms', label: '객실 배정', icon: <BedDouble size={18} /> },
      { path: '/party-checkin', label: '파티 입장 체크', icon: <PartyPopper size={18} /> },
    ],
    requiredRoles: ['superadmin', 'admin'],
  },
  {
    title: '운영 / 관리',
    items: [
      { path: '/activity-logs', label: '활동 로그', icon: <History size={18} /> },
      { path: '/rooms/manage', label: '객실 설정', icon: <Settings2 size={18} /> },
      { path: '/templates', label: '템플릿 설정', icon: <FileText size={18} /> },
      { path: '/event-sms', label: '이벤트 문자', icon: <Megaphone size={18} /> },
    ],
    requiredRoles: ['superadmin', 'admin'],
  },
  {
    title: '시스템',
    items: [
      { path: '/settings', label: '연동 설정', icon: <Settings size={18} /> },
      { path: '/users', label: '계정 설정', icon: <Users size={18} /> },
    ],
    requiredRoles: ['superadmin', 'admin'],
  },
]

// ── Role Badge ──
const ROLE_BADGE_COLORS: Record<string, 'purple' | 'info' | 'gray'> = {
  superadmin: 'purple',
  admin: 'info',
  staff: 'gray',
}

const ROLE_LABELS: Record<string, string> = {
  superadmin: '슈퍼관리자',
  admin: '관리자',
  staff: '직원',
}

// ── Tenant Switcher (superadmin only) ──
function TenantSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const { tenants, currentTenantId } = useTenantStore()
  const [open, setOpen] = useState(false)

  if (tenants.length <= 1) return null

  const current = tenants.find(t => String(t.id) === currentTenantId)
  const currentLabel = current?.slug === 'stable' ? '스테이블' : current?.slug === 'handam' ? '한담누리' : (current?.name || '선택')

  const handleSelect = (tenantId: number) => {
    localStorage.setItem('sms-tenant-id', String(tenantId))
    setOpen(false)
    window.location.reload()
  }

  if (collapsed) {
    return (
      <Tooltip content={currentLabel} placement="right">
        <button
          onClick={() => setOpen(!open)}
          className="relative flex h-9 w-9 items-center justify-center rounded-xl text-[#4E5968] hover:bg-[#F2F4F6] dark:text-gray-400 dark:hover:bg-[#1E1E24]"
        >
          <ChevronsUpDown size={16} />
          {open && (
            <div className="absolute bottom-full left-0 mb-1 w-40 rounded-xl border border-[#E5E8EB] bg-white py-1 shadow-lg dark:border-gray-800 dark:bg-[#1E1E24]">
              {tenants.map(t => (
                <button
                  key={t.id}
                  onClick={() => handleSelect(t.id)}
                  className={cn(
                    'w-full px-3 py-2 text-left text-body transition-colors',
                    String(t.id) === currentTenantId
                      ? 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/10'
                      : 'text-[#191F28] hover:bg-[#F2F4F6] dark:text-white dark:hover:bg-[#2C2C34]',
                  )}
                >
                  {t.slug === 'stable' ? '스테이블' : t.slug === 'handam' ? '한담누리' : t.name}
                </button>
              ))}
            </div>
          )}
        </button>
      </Tooltip>
    )
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-body text-[#4E5968] hover:bg-[#F2F4F6] dark:text-gray-400 dark:hover:bg-[#1E1E24] transition-colors"
      >
        <span className="truncate font-medium">{currentLabel}</span>
        <ChevronsUpDown size={14} className="shrink-0 text-[#B0B8C1]" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 right-0 mb-1 rounded-xl border border-[#E5E8EB] bg-white py-1 shadow-lg dark:border-gray-800 dark:bg-[#1E1E24] z-50">
          {tenants.map(t => (
            <button
              key={t.id}
              onClick={() => handleSelect(t.id)}
              className={cn(
                'w-full px-3 py-2 text-left text-body transition-colors',
                String(t.id) === currentTenantId
                  ? 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/10'
                  : 'text-[#191F28] hover:bg-[#F2F4F6] dark:text-white dark:hover:bg-[#2C2C34]',
              )}
            >
              {t.slug === 'stable' ? '스테이블' : t.slug === 'handam' ? '한담누리' : t.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Nav Item Component ──
function SidebarNavItem({
  item,
  active,
  collapsed,
  onClick,
}: {
  item: NavItem
  active: boolean
  collapsed: boolean
  onClick: () => void
}) {
  const content = (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-xl p-2.5 text-body font-medium transition-colors",
        active
          ? "bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/10 dark:text-[#3182F6]"
          : "text-[#8B95A1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]",
        collapsed && "justify-center",
      )}
    >
      <span className={cn("shrink-0", active && "text-[#3182F6]")}>{item.icon}</span>
      {!collapsed && <span>{item.label}</span>}
    </button>
  )

  if (collapsed) {
    return (
      <Tooltip content={item.label} placement="right">
        {content}
      </Tooltip>
    )
  }

  return content
}

// ── Desktop Sidebar ──
function DesktopSidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)

  const isActive = (path: string) => location.pathname === path

  const visibleGroups = NAV_GROUPS.filter(
    (g) => !g.requiredRoles || (user && g.requiredRoles.includes(user.role))
  )

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-30 flex flex-col bg-white shadow-[2px_0_6px_rgba(0,0,0,0.02)] transition-all duration-300 dark:bg-[#17171C] dark:shadow-[2px_0_8px_rgba(0,0,0,0.2)]",
        collapsed ? 'w-[68px]' : 'w-60',
      )}
    >
      {/* Logo */}
      <div className={cn("flex h-14 items-center px-4", collapsed ? 'justify-center' : 'gap-2.5')}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#3182F6] text-white">
          <span className="text-label font-bold">S</span>
        </div>
        {!collapsed && (
          <span className="text-subheading font-bold text-[#191F28] dark:text-white">
            SMS
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="mt-1 flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        {visibleGroups.map((group, gi) => (
          <div key={group.title}>
            {gi > 0 && !collapsed && (
              <div className="mx-0 my-2 h-px bg-[#F2F4F6] dark:bg-gray-800" />
            )}
            {!collapsed && (
              <p className="mb-1 px-2.5 text-overline font-semibold tracking-wide text-[#B0B8C1] dark:text-gray-600">
                {group.title}
              </p>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.path}>
                  <SidebarNavItem
                    item={item}
                    active={isActive(item.path)}
                    collapsed={collapsed}
                    onClick={() => navigate(item.path)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-[#F2F4F6] dark:border-gray-800">
        {user?.role === 'superadmin' && (
          <div className="px-3 pt-3">
            <TenantSwitcher collapsed={collapsed} />
          </div>
        )}
        <div className={cn("flex items-center p-3", collapsed ? 'justify-center' : 'justify-between')}>
          <ThemeToggleButton />
          <button
            onClick={onToggle}
            className="rounded-xl p-2 text-[#B0B8C1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>
      </div>
    </aside>
  )
}

// ── Mobile Sidebar (Drawer) ──
function MobileSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)

  const isActive = (path: string) => location.pathname === path

  const visibleGroups = NAV_GROUPS.filter(
    (g) => !g.requiredRoles || (user && g.requiredRoles.includes(user.role))
  )

  // Prevent body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-xl p-2 text-[#4E5968] hover:bg-[#F2F4F6] dark:text-gray-400 dark:hover:bg-[#1E1E24]"
      >
        <Menu size={20} />
      </button>

      {/* Overlay + Drawer (portal to body to escape stacking context) */}
      {open && createPortal(
        <div className="fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-gray-900/50 dark:bg-gray-900/80"
            onClick={() => setOpen(false)}
          />
          {/* Panel */}
          <div className="relative z-10 flex h-full w-72 flex-col bg-white shadow-xl dark:bg-[#17171C]">
            {/* Header */}
            <div className="flex h-14 items-center justify-between px-4">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#3182F6] text-white">
                  <span className="text-label font-bold">S</span>
                </div>
                <span className="text-subheading font-bold text-[#191F28] dark:text-white">
                  SMS
                </span>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="rounded-xl p-2 text-[#8B95A1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
              >
                <X size={18} />
              </button>
            </div>

            {/* Nav */}
            <nav className="flex-1 overflow-y-auto px-3 py-2">
              {visibleGroups.map((group, gi) => (
                <div key={group.title}>
                  {gi > 0 && (
                    <div className="mx-0 my-2 h-px bg-[#F2F4F6] dark:bg-gray-800" />
                  )}
                  <p className="mb-1 px-2.5 text-overline font-semibold tracking-wide text-[#B0B8C1] dark:text-gray-600">
                    {group.title}
                  </p>
                  <ul className="space-y-0.5">
                    {group.items.map((item) => (
                      <li key={item.path}>
                        <SidebarNavItem
                          item={item}
                          active={isActive(item.path)}
                          collapsed={false}
                          onClick={() => {
                            navigate(item.path)
                            setOpen(false)
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </nav>
            {user?.role === 'superadmin' && (
              <div className="border-t border-[#F2F4F6] dark:border-gray-800 px-3 py-3">
                <TenantSwitcher />
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

// ── Header ──
function AppHeader({
  isMobile,
}: {
  isMobile: boolean
}) {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="sticky top-0 z-20 flex h-14 w-full items-center justify-between bg-[#FAFBFC]/90 px-4 py-2.5 backdrop-blur-md dark:bg-[#17171C]/90">
      <div className="flex items-center gap-3">
        {isMobile && <MobileSidebar />}
      </div>
      <div className="flex items-center gap-2">
        {user && (
          <>
            <span className="hidden text-label text-[#4E5968] dark:text-gray-300 sm:inline">
              {user.name}
            </span>
            <Badge color={ROLE_BADGE_COLORS[user.role]} size="sm">
              {ROLE_LABELS[user.role] || user.role}
            </Badge>
          </>
        )}
        <ThemeToggleButton />
        <button
          onClick={handleLogout}
          className="rounded-xl p-2 text-[#B0B8C1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
          aria-label="로그아웃"
          title="로그아웃"
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  )
}

// ── Layout ──
interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false)
  const isMobile = useIsMobile()
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const isStaff = user?.role === 'staff'

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  // 스태프: 사이드바 없이 전체 화면 레이아웃
  if (isStaff) {
    return (
      <div className="flex min-h-screen flex-col bg-[#FAFBFC] dark:bg-[#17171C]">
        <header className="sticky top-0 z-20 flex h-14 w-full items-center justify-between bg-[#FAFBFC]/90 px-4 py-2.5 backdrop-blur-md dark:bg-[#17171C]/90">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#3182F6] text-white">
              <span className="text-label font-bold">S</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {user && (
              <>
                <span className="hidden text-label text-[#4E5968] dark:text-gray-300 sm:inline">
                  {user.name}
                </span>
                <Badge color={ROLE_BADGE_COLORS[user.role]} size="sm">
                  {ROLE_LABELS[user.role] || user.role}
                </Badge>
              </>
            )}
            <ThemeToggleButton />
            <button
              onClick={handleLogout}
              className="rounded-xl p-2 text-[#B0B8C1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
              aria-label="로그아웃"
              title="로그아웃"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          {children}
        </main>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-[#FAFBFC] dark:bg-[#17171C]">
      {/* Desktop Sidebar */}
      {!isMobile && (
        <DesktopSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
        />
      )}

      {/* Main Area */}
      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col transition-all duration-300",
          !isMobile && (collapsed ? 'ml-[68px]' : 'ml-60'),
        )}
      >
        <AppHeader isMobile={isMobile} />
        <main className="min-w-0 flex-1 p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
