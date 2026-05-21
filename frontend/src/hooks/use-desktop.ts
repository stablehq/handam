import { useEffect, useState } from 'react'

const DESKTOP_BREAKPOINT = 1024
const DESKTOP_QUERY = `(min-width: ${DESKTOP_BREAKPOINT}px)`

/**
 * 1024px 이상 = 데스크톱 판단. PC 드래그/단축키 활성화 등에 사용.
 *
 * `window.innerWidth` 대신 `matchMedia` 의 결과를 사용한다 — Chrome dev tools 모바일
 * emulation 에서는 visual viewport(`window.innerWidth`) 가 큰 채로 유지되고 layout
 * viewport 만 device 크기로 바뀌어서, `window.innerWidth` 기반 비교는 emulation 을
 * 인식하지 못한다.
 */
export function useIsDesktop() {
  // 초기값을 lazy initializer 로 즉시 계산 — 첫 렌더링부터 올바른 모드로 그려서
  // PC 로드 직후 모바일 → 데스크톱 mode 깜빡임(Circle → GripVertical 등) 방지.
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches,
  )

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_QUERY)
    const onChange = () => setIsDesktop(mql.matches)
    mql.addEventListener('change', onChange)
    setIsDesktop(mql.matches)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isDesktop
}
