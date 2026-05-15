# 단계 #1: useIsDesktop 훅 신규 생성

> 작성일: 2026-05-15
> 단계: 1 / 10
> 섹션: A. 기초 인프라
> 동작 변화: ⚪ 없음 (아무 컴포넌트도 import 안 함)
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

dnd-kit 드래그 시스템은 PC(1024px 이상)에서만 동작하고, 모바일은 기존 클릭-선택 시스템을 그대로 유지한다.
이를 위해 **PC 여부를 판단하는 훅**이 필요하다. 이 단계에서 훅 파일만 추가하고, 실제 import는 단계 #4부터 시작한다.

**이 단계에서는 어떤 기존 파일도 수정하지 않는다.**

---

## 2. 변경 대상 코드

### 2-1. 참조: `frontend/src/hooks/use-mobile.ts` (변경 없음)

기존 훅의 패턴을 그대로 따른다.

```ts
import { useEffect, useState } from 'react'

const MOBILE_BREAKPOINT = 768

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    mql.addEventListener('change', onChange)
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
```

### 2-2. 신규 생성: `frontend/src/hooks/use-desktop.ts`

**Before**: 파일 없음.

**After** (신규 파일 전체):

```ts
import { useEffect, useState } from 'react'

const DESKTOP_BREAKPOINT = 1024

export function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${DESKTOP_BREAKPOINT}px)`)
    const onChange = () => setIsDesktop(window.innerWidth >= DESKTOP_BREAKPOINT)
    mql.addEventListener('change', onChange)
    setIsDesktop(window.innerWidth >= DESKTOP_BREAKPOINT)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isDesktop
}
```

**변경 의도**: dnd-kit drag를 PC에서만 활성화하기 위한 breakpoint 판단 훅.
단계 #4(Grip useDraggable), #8(행 onClick 가드), #9(InlineInput singleClick)에서 import한다.

---

## 3. 동작 동등성 근거

이 단계에서는 **아무 기존 파일도 수정하지 않으며**, **신규 파일을 어디서도 import하지 않는다.**
따라서 UI 동작 변화는 정의상 0이다.

케이스별 비교:

| 케이스 | 기존 결과 | 이 단계 이후 결과 |
|--------|-----------|-------------------|
| PC에서 게스트 이동 | 클릭-선택 | 클릭-선택 (변화 없음) ✅ |
| 모바일에서 게스트 이동 | 클릭-선택 | 클릭-선택 (변화 없음) ✅ |
| 인라인 편집 진입 | 더블클릭 | 더블클릭 (변화 없음) ✅ |
| 모든 RoomAssignment 기능 | 기존과 동일 | 기존과 동일 ✅ |

---

## 4. 설계 결정 기록

### 왜 `useIsMobile`의 역(逆)이 아닌가?

`useIsMobile`은 768px 미만을 모바일로 판단한다.
`useIsDesktop`은 1024px 이상을 데스크탑으로 판단한다.

따라서 **769px ~ 1023px 구간은 모바일도 데스크탑도 아니다.**

이 범위(태블릿/넓은 모바일)에서는:
- `useIsMobile() = false` (모바일 아님)
- `useIsDesktop() = false` (데스크탑 아님)
- → dnd-kit 비활성, 클릭-선택 시스템 활성

이것이 의도된 동작이다. 태블릿에서는 터치 기반 드래그가 불안정하므로, 클릭-선택 시스템(모바일 경험)을 유지하는 게 안전하다.

### 왜 `useState(false)` 초기값인가?

`use-mobile.ts`와 동일한 패턴. SSR이 없는 Vite+React SPA이므로 초기 렌더에서 `false`로 시작하고, `useEffect` 마운트 시점에 실제 viewport를 읽어 `isDesktop`을 보정한다.

PC에서는 마운트 직후 한 번 re-render가 발생한다(false → true). 이 단계에서는 아무도 이 훅을 사용하지 않으므로 실질적 영향 없음. 단계 #4에서 import될 때 `useDraggable({ disabled: !isDesktop })`이 false → true로 전환되는 첫 렌더가 발생하지만, 초기 렌더에서는 단순히 "비활성 드래그블"로 표시될 뿐 UX 문제 없음.

### 왜 `min-width: 1024px`인가?

`(min-width: 1024px)` 쿼리와 `window.innerWidth >= 1024` 조건이 일치한다.
`(max-width: 1023px)` 역방향 쿼리보다 의미가 명확하고, `useIsMobile`의 `(max-width: 767px)` 패턴과 대칭 관계가 시각적으로 이해하기 쉽다.

---

## 5. 후속 단계에서의 사용 위치 (참고)

이 단계에서는 연결하지 않음. 단계별 import 예정 파일:

| 단계 | 파일 | 용도 |
|------|------|------|
| #4 | `GuestRow.tsx` | `useDraggable({ disabled: !isDesktop })` |
| #5 | `RoomRow.tsx`, `GuestZone.tsx` | `useDroppable({ disabled: !isDesktop })` |
| #8 | `GuestRow.tsx` | 행 `onClick`에서 `if (isDesktop) return` |
| #9 | `GuestRow.tsx` | `<InlineInput singleClick={isDesktop} />` |

Import 방식 (두 가지 모두 사용 가능, 기존 파일의 alias 방식에 맞춰 선택):
```ts
import { useIsDesktop } from '@/hooks/use-desktop'      // alias 방식
import { useIsDesktop } from '../../../../hooks/use-desktop'  // 상대경로 방식
```

---

## 6. 영향받지 않음을 확인할 코드 경로

- `useGuestSelection`, `useGuestMove`, `useGuestDropTarget`, `useHoverZone` — 전부 미변경
- `GuestRow.tsx`, `RoomRow.tsx`, `GuestZone.tsx`, `InlineInput.tsx` — 전부 미변경
- `RoomAssignment.tsx` — 미변경
- `use-mobile.ts` — 미변경. `useIsMobile`과 `useIsDesktop`은 독립적으로 공존
- Backend 전체 — 미변경

---

## 7. 검증 체크리스트

- [ ] `frontend/src/hooks/use-desktop.ts` 파일이 생성됨
- [ ] `use-mobile.ts`와 구조가 동일함 (useEffect + mql + cleanup)
- [ ] **아무 기존 파일도 수정하지 않음** — `git diff`에 `use-desktop.ts` 하나만 표시됨
- [ ] TypeScript 빌드 오류 없음 (`npm run build`)
- [ ] 브라우저에서 RoomAssignment 페이지 동작 기존과 동일 — PC/모바일 모두 클릭-선택 시스템 작동
