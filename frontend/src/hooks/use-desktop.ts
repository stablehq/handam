import { useEffect, useState } from 'react'

const DESKTOP_BREAKPOINT = 1024

export function useIsDesktop() {
  // 초기값을 lazy initializer 로 즉시 계산 — 첫 렌더링부터 올바른 모드로 그려서
  // PC 로드 직후 모바일 → 데스크톱 mode 깜빡임(Circle → GripVertical 등) 방지.
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.innerWidth >= DESKTOP_BREAKPOINT,
  )

  useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${DESKTOP_BREAKPOINT}px)`)
    const onChange = () => setIsDesktop(window.innerWidth >= DESKTOP_BREAKPOINT)
    mql.addEventListener('change', onChange)
    setIsDesktop(window.innerWidth >= DESKTOP_BREAKPOINT)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isDesktop
}
