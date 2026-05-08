import React from 'react'
import ReactDOM from 'react-dom/client'
import * as Sentry from '@sentry/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import App from './App.tsx'
import './index.css'
import { queryClient } from './lib/queryClient'

// Sentry 초기화 (VITE_SENTRY_DSN 환경변수 설정 시).
// 동적 import 가 아닌 동기 import — 부트 시점부터 ErrorBoundary 가 가용해야 첫 렌더 크래시도 화이트아웃 없이 잡음.
const sentryDsn = import.meta.env.VITE_SENTRY_DSN
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
  })
}

function ErrorFallback({ error, resetError }: { error: unknown; resetError: () => void }) {
  const message = error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다.'
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#F2F4F6] px-4 text-center dark:bg-[#17171C]">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#F04452]/10 text-[#F04452]">
        <span className="text-display font-bold">!</span>
      </div>
      <div>
        <h1 className="text-title font-bold text-[#191F28] dark:text-white">오류가 발생했습니다</h1>
        <p className="mt-2 text-label text-[#8B95A1] dark:text-gray-400">{message}</p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={resetError}
          className="rounded-lg bg-[#F2F4F6] px-4 py-2 text-body font-medium text-[#4E5968] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-200 dark:hover:bg-[#35353E]"
        >
          다시 시도
        </button>
        <button
          onClick={() => window.location.reload()}
          className="rounded-lg bg-[#3182F6] px-4 py-2 text-body font-medium text-white hover:bg-[#1B64DA]"
        >
          새로고침
        </button>
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/* Sentry.ErrorBoundary 는 DSN 없어도 일반 ErrorBoundary 처럼 동작 (보고만 미발생). 부트 시점부터 보호. */}
    <Sentry.ErrorBoundary fallback={(props) => <ErrorFallback error={props.error} resetError={props.resetError} />}>
      <QueryClientProvider client={queryClient}>
        <App />
        <ReactQueryDevtools initialIsOpen={false} />
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>,
)
