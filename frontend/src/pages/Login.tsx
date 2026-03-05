import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Label, TextInput, Spinner } from 'flowbite-react'
import { useAuthStore } from '@/stores/auth-store'
import { authAPI } from '@/services/api'

export default function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await authAPI.login({ username, password })
      const { access_token, user } = res.data
      login(access_token, user)
      navigate('/')
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
              <Label htmlFor="username" className="mb-1.5 block text-label font-medium text-[#4E5968] dark:text-gray-300">
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
              <Label htmlFor="password" className="mb-1.5 block text-label font-medium text-[#4E5968] dark:text-gray-300">
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
