import { useState, useEffect, createContext, useContext } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Sidebar,
  SidebarItem,
  SidebarItemGroup,
  SidebarItems,
  Navbar,
  Tooltip,
  Drawer,
} from 'flowbite-react'
import { useIsMobile } from '@/hooks/use-mobile'
import {
  LayoutDashboard,
  CalendarRange,
  BedDouble,
  Settings2,
  FileText,
  MessageSquareText,
  Zap,
  PanelLeftClose,
  PanelLeft,
  Menu,
  Sun,
  Moon,
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
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: '운영 관리',
    items: [
      { path: '/', label: '대시보드', icon: <LayoutDashboard size={18} /> },
      { path: '/reservations', label: '예약 관리', icon: <CalendarRange size={18} /> },
      { path: '/rooms', label: '객실 배정', icon: <BedDouble size={18} /> },
      { path: '/rooms/manage', label: '객실 설정', icon: <Settings2 size={18} /> },
      { path: '/templates', label: '템플릿 관리', icon: <FileText size={18} /> },
    ],
  },
  {
    title: 'SMS 자동화',
    items: [
      { path: '/messages', label: '메시지', icon: <MessageSquareText size={18} /> },
      { path: '/auto-response', label: '자동 응답', icon: <Zap size={18} /> },
    ],
  },
]

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

  const isActive = (path: string) => location.pathname === path

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-30 flex flex-col bg-white transition-all duration-300 dark:bg-[#17171C] ${
        collapsed ? 'w-[68px]' : 'w-60'
      }`}
    >
      <Sidebar aria-label="Navigation sidebar" className="h-full w-full">
        {/* Logo */}
        <div
          className={`flex h-14 items-center px-4 ${
            collapsed ? 'justify-center' : 'gap-2.5'
          }`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#3182F6] text-white">
            <span className="text-label font-bold">S</span>
          </div>
          {!collapsed && (
            <span className="text-subheading font-bold text-[#191F28] dark:text-white">
              SMS
            </span>
          )}
        </div>

        <SidebarItems className="mt-1">
          {NAV_GROUPS.map((group, gi) => (
            <SidebarItemGroup key={group.title}>
              {gi > 0 && !collapsed && (
                <div className="mx-3 my-2 h-px bg-[#F2F4F6] dark:bg-gray-800" />
              )}
              {!collapsed && (
                <p className="mb-1 px-3 text-overline font-semibold tracking-wide text-[#B0B8C1] dark:text-gray-600">
                  {group.title}
                </p>
              )}
              {group.items.map((item) => {
                const sidebarItem = (
                  <SidebarItem
                    key={item.path}
                    href="#"
                    icon={() => <>{item.icon}</>}
                    active={isActive(item.path)}
                    onClick={(e) => {
                      e.preventDefault()
                      navigate(item.path)
                    }}
                  >
                    {!collapsed ? item.label : null}
                  </SidebarItem>
                )

                if (collapsed) {
                  return (
                    <Tooltip key={item.path} content={item.label} placement="right">
                      {sidebarItem}
                    </Tooltip>
                  )
                }

                return sidebarItem
              })}
            </SidebarItemGroup>
          ))}
        </SidebarItems>

        {/* Footer */}
        <div
          className={`mt-auto flex items-center p-3 ${
            collapsed ? 'justify-center' : 'justify-between'
          }`}
        >
          <ThemeToggleButton />
          <button
            onClick={onToggle}
            className="rounded-xl p-2 text-[#B0B8C1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]"
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>
      </Sidebar>
    </aside>
  )
}

// ── Mobile Sidebar ──
function MobileSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)

  const isActive = (path: string) => location.pathname === path

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-xl p-2 text-[#4E5968] hover:bg-[#F2F4F6] dark:text-gray-400 dark:hover:bg-[#1E1E24]"
      >
        <Menu size={20} />
      </button>

      <Drawer open={open} onClose={() => setOpen(false)} position="left">
        <div className="flex h-14 items-center gap-2.5 px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#3182F6] text-white">
            <span className="text-label font-bold">S</span>
          </div>
          <span className="text-subheading font-bold text-[#191F28] dark:text-white">
            SMS
          </span>
        </div>

        <Sidebar aria-label="Mobile navigation sidebar" className="w-full">
          <SidebarItems>
            {NAV_GROUPS.map((group, gi) => (
              <SidebarItemGroup key={group.title}>
                {gi > 0 && (
                  <div className="mx-3 my-2 h-px bg-[#F2F4F6] dark:bg-gray-800" />
                )}
                <p className="mb-1 px-3 text-overline font-semibold tracking-wide text-[#B0B8C1] dark:text-gray-600">
                  {group.title}
                </p>
                {group.items.map((item) => (
                  <SidebarItem
                    key={item.path}
                    href="#"
                    icon={() => <>{item.icon}</>}
                    active={isActive(item.path)}
                    onClick={(e) => {
                      e.preventDefault()
                      navigate(item.path)
                      setOpen(false)
                    }}
                  >
                    {item.label}
                  </SidebarItem>
                ))}
              </SidebarItemGroup>
            ))}
          </SidebarItems>
        </Sidebar>
      </Drawer>
    </>
  )
}

// ── Page Title Map ──
const PAGE_TITLES: Record<string, string> = {
  '/': '대시보드',
  '/reservations': '예약 관리',
  '/rooms': '객실 배정',
  '/rooms/manage': '객실 설정',
  '/templates': '템플릿 관리',
  '/messages': '메시지',
  '/auto-response': '자동 응답',
}

// ── Layout ──
interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false)
  const isMobile = useIsMobile()
  const location = useLocation()

  const pageTitle = PAGE_TITLES[location.pathname] || ''

  return (
    <div className="flex min-h-screen bg-white dark:bg-[#17171C]">
      {/* Desktop Sidebar */}
      {!isMobile && (
        <DesktopSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
        />
      )}

      {/* Main Area */}
      <div
        className={`flex flex-1 flex-col transition-all duration-300 ${
          isMobile ? '' : collapsed ? 'ml-[68px]' : 'ml-60'
        }`}
      >
        {/* Header */}
        <Navbar fluid className="sticky top-0 z-20 h-14 bg-white/90 backdrop-blur-md dark:bg-[#17171C]/90">
          <div className="flex w-full items-center justify-between">
            <div className="flex items-center gap-3">
              {isMobile && <MobileSidebar />}
              <h1 className="text-subheading font-semibold text-[#191F28] dark:text-white">
                {pageTitle}
              </h1>
            </div>
            <div className="flex items-center gap-1">
              <ThemeToggleButton />
            </div>
          </div>
        </Navbar>

        {/* Content */}
        <main className="flex-1 p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
