import { useState, useEffect } from 'react'
import { TextInput } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/auth-store'
import { authAPI } from '@/services/api'

const SAVED_CREDENTIALS_KEY = 'sms-saved-credentials'

export default function Login() {
  const login = useAuthStore((s) => s.login)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Load saved username on mount + migrate (strip legacy password field)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(SAVED_CREDENTIALS_KEY)
      if (!saved) return
      const parsed = JSON.parse(saved)
      const u = typeof parsed?.username === 'string' ? parsed.username : ''
      const hadLegacyPassword = typeof parsed?.password === 'string' && parsed.password.length > 0
      if (u) {
        setUsername(u)
        setRememberMe(true)
      }
      // 1회성 마이그레이션: legacy 평문 password 필드 제거
      if (hadLegacyPassword) {
        if (u) {
          localStorage.setItem(SAVED_CREDENTIALS_KEY, JSON.stringify({ username: u }))
        } else {
          localStorage.removeItem(SAVED_CREDENTIALS_KEY)
        }
      }
    } catch { /* ignore */ }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await authAPI.login({ username, password })
      const { access_token, refresh_token, user } = res.data

      // Save username only (never password — security)
      if (rememberMe) {
        localStorage.setItem(SAVED_CREDENTIALS_KEY, JSON.stringify({ username }))
      } else {
        localStorage.removeItem(SAVED_CREDENTIALS_KEY)
      }

      login(access_token, refresh_token, user)
      // SPA navigate 대신 full reload — 신규 배포가 있을 때 캐시된 옛 번들 대신 fresh index.html
      // 받아 새 hash 번들 자동 적용. 토큰은 zustand persist 로 localStorage 저장돼 reload 후에도 유지.
      window.location.assign('/')
    } catch (err: any) {
      const msg = err?.response?.data?.detail
      setError(msg || '아이디 또는 비밀번호가 올바르지 않습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F2F4F6] dark:bg-[#17171C]">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#3182F6] text-white">
            <span className="text-heading font-bold">S</span>
          </div>
          <span className="text-subheading font-bold text-[#191F28] dark:text-white">
            SMS 예약 시스템
          </span>
        </div>

        {/* Card */}
        <div className="rounded-2xl bg-white p-8 shadow-sm dark:bg-[#1E1E24]">
          <h1 className="text-heading mb-6 font-semibold text-[#191F28] dark:text-white">
            로그인
          </h1>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <Label htmlFor="username" className="text-[#4E5968] dark:text-gray-300">
                아이디
              </Label>
              <TextInput
                id="username"
                type="text"
                placeholder="아이디를 입력하세요"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
              />
            </div>

            <div>
              <Label htmlFor="password" className="text-[#4E5968] dark:text-gray-300">
                비밀번호
              </Label>
              <TextInput
                id="password"
                type="password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>

            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-4 w-4 rounded border-[#E5E8EB] text-[#3182F6] focus:ring-[#3182F6] dark:border-gray-600 dark:bg-[#2C2C34]"
              />
              <span className="text-label text-[#8B95A1] dark:text-gray-400">아이디 저장</span>
            </label>

            {error && (
              <p className="text-label text-[#F04452]">{error}</p>
            )}

            <Button
              type="submit"
              color="blue"
              className="mt-2 w-full"
              disabled={loading}
            >
              {loading && <Spinner size="sm" className="mr-2" />}
              {loading ? '로그인 중...' : '로그인'}
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
