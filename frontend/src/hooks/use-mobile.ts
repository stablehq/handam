import { useEffect, useState } from 'react'

const MOBILE_BREAKPOINT = 768

/**
 * 768px 미만 = 모바일 판단.
 *
 * `window.innerWidth` 대신 `matchMedia` 의 결과(`mql.matches`)를 사용한다.
 * 이유: Chrome dev tools 모바일 emulation 에서는 visual viewport(`window.innerWidth`) 가
 *      실제 브라우저 창 크기로 유지되고 layout viewport(`clientWidth` / media query) 만
 *      device 폭으로 바뀐다. `window.innerWidth` 로 비교하면 emulation 중에도 false 가
 *      유지되어 mobile 분기가 작동하지 않는다. CSS media query 와 동일한 기준이 더 정확.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => setIsMobile(mql.matches)
    mql.addEventListener('change', onChange)
    setIsMobile(mql.matches)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
