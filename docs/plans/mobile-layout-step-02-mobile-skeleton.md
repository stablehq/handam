# Mobile Layout Step #02 — MobileLayout 빈 골격 + isMobile 분기

> 작성일: 2026-05-20
> 상태: 사전조사 검토 대기
> 부모 plan: [mobile-layout-migration-plan.md](./mobile-layout-migration-plan.md)
> 직전 단계: [Step #01 — PC JSX 추출](./mobile-layout-step-01-desktop-extract.md) (완료)
> 동작 변화: **없음** (옵션 A — wrapper, 모바일이 렌더하는 게 literally DesktopLayout)

---

## 목표

`RoomAssignment.tsx` 에서 `<DesktopLayout {...props}/>` 직접 호출하는 부분을 `isMobile` 기반 분기로 교체. 모바일은 `MobileLayout` 을 렌더하지만, 이 단계의 `MobileLayout` 은 **그저 DesktopLayout 을 그대로 재호출하는 wrapper**.

분기 메커니즘만 도입, JSX/스타일 변경 0. 이후 Step #02.5 ~ Step #06 에서 모바일만 점진적으로 변경할 base 를 마련.

---

## 원칙

1. **PC(≥768px) 동작 0 변경**
2. **모바일(<768px) 동작 0 변경** — wrapper 가 DesktopLayout 그대로 호출하므로 자명
3. **신규 파일 한 개** — `layouts/MobileLayout.tsx` (15줄 내외)
4. **RoomAssignment.tsx 변경 최소** — `isMobile` 은 이미 line 180 에 존재, 추가 import + 단일 분기 (~5줄)

---

## 의도된 동작 변화

**없음.** 모바일/PC 둘 다 Step #01 직후와 시각/동작 100% 동일.

| 화면 폭 | Step #01 후 | Step #02 후 | 차이 |
|---------|-------------|-------------|------|
| ≥768px (PC) | `<DesktopLayout/>` 렌더 | `<DesktopLayout/>` 렌더 (분기 false) | 없음 |
| <768px (모바일) | `<DesktopLayout/>` 렌더 | `<MobileLayout/>` → 내부에서 `<DesktopLayout/>` 렌더 | 컴포넌트 트리에 wrapper 1단 추가, 시각 동일 |

---

## 현재 구조 (Step #01 직후)

### `RoomAssignment.tsx` (1196 lines)

```tsx
// line 24
import { useIsMobile } from '../hooks/use-mobile';
// line 41
import { DesktopLayout } from './RoomAssignment/layouts/DesktopLayout';

// line 180 (이미 존재)
const isMobile = useIsMobile();

// line 856-907 (현재)
<div className={...}>
  <DesktopLayout
    summary={summary}
    hasUnstable={hasUnstable}
    ... (42 props) ...
    sharedZoneProps={sharedZoneProps}
  />
  {/* 모달들 ... */}
</div>
```

### `useIsMobile()` (`hooks/use-mobile.ts`)
- 768px 기준 `window.matchMedia('(max-width: 767px)')`
- **SSR/초기 렌더는 false** (PC 와 동일) → 모바일 user 도 첫 paint 는 PC 레이아웃, mount 후 resize listener 가 발화하면 mobile 로 전환

---

## Before / After 코드 인용

### 신규: `layouts/MobileLayout.tsx`

```tsx
/**
 * RoomAssignment 페이지의 모바일(<768px) 레이아웃.
 *
 * Mobile Layout Step #02 (2026-05-20): 분기 도입 단계.
 * 이 단계의 MobileLayout 은 DesktopLayout 을 그대로 호출하는 wrapper 에 불과하다.
 * 따라서 PC/모바일 시각/동작은 Step #01 직후와 완전 동일.
 *
 * 향후 단계:
 *  - Step #03 ~ #05: 이 wrapper 를 모바일 친화 JSX 로 점진적 교체
 *    (MobileRoomCard, MobileZones, mobile-friendly header)
 *  - 각 단계마다 DesktopLayout 은 손대지 않음 (PC 동작 보장)
 *
 * 사전조사: docs/plans/mobile-layout-step-02-mobile-skeleton.md
 */
import { DesktopLayout, type DesktopLayoutProps } from './DesktopLayout';

export function MobileLayout(props: DesktopLayoutProps) {
  return <DesktopLayout {...props} />;
}
```

### `RoomAssignment.tsx`

#### Before (Step #01 직후, line 41 + line 856-907 부근)

```tsx
import { DesktopLayout } from './RoomAssignment/layouts/DesktopLayout';

// ...

      <DesktopLayout
        // SummaryCards
        summary={summary}
        ... (42 props) ...
        sharedZoneProps={sharedZoneProps}
      />
```

#### After

```tsx
import { DesktopLayout } from './RoomAssignment/layouts/DesktopLayout';
import { MobileLayout } from './RoomAssignment/layouts/MobileLayout';

// ...

      {isMobile ? (
        <MobileLayout
          // SummaryCards
          summary={summary}
          ... (42 props 동일) ...
          sharedZoneProps={sharedZoneProps}
        />
      ) : (
        <DesktopLayout
          // SummaryCards
          summary={summary}
          ... (42 props 동일) ...
          sharedZoneProps={sharedZoneProps}
        />
      )}
```

### 더 깔끔한 대안: 변수에 props 묶기

42개 prop 을 두 번 적기 부담스러우면, 동일 props 객체를 변수로 추출:

```tsx
const layoutProps: DesktopLayoutProps = {
  summary,
  hasUnstable,
  ...42개...
  sharedZoneProps,
};

return (
  <DndContext ...>
    <div ...>
      {isMobile ? <MobileLayout {...layoutProps} /> : <DesktopLayout {...layoutProps} />}
      {/* 모달들 */}
    </div>
    <DragOverlay>...</DragOverlay>
  </DndContext>
);
```

**선호: 후자**. 중복 제거 + TypeScript 가 props 누락 시 즉시 에러.

---

## 동작 동등성 증명

### 1) MobileLayout wrapper 의 결과
- `<MobileLayout {...props}/>` 의 렌더 결과 = `<DesktopLayout {...props}/>` 의 렌더 결과
- React 가 보는 컴포넌트 트리: `MobileLayout > DesktopLayout > ...` (1단 더 깊지만 렌더 출력 동일)
- prop 전달은 spread 로 1:1, 손실 없음
- `MobileLayout` 자체는 state/effect/ref 없음 → re-render 비용 사실상 0

### 2) `isMobile` 분기의 결과
- `useIsMobile()` 은 초기 렌더 시 false → PC user 든 모바일 user 든 **첫 paint 는 항상 DesktopLayout** (PC 와 동일)
- mount 후 resize listener 가 발화하면:
  - PC user: 그대로 DesktopLayout (변화 없음)
  - 모바일 user: re-render 되어 `<DesktopLayout/>` → `<MobileLayout/>` 로 컴포넌트 type 변경
- React 가 컴포넌트 type 변경을 보면 자식 트리 unmount + remount
- 단, MobileLayout 이 즉시 DesktopLayout 을 다시 렌더하므로, 새 DesktopLayout 인스턴스가 mount 됨

### 3) Unmount → Remount 부수효과 (모바일 한정, 첫 mount 시점에만)
초기 mount 시 useIsMobile false → true 로 바뀌는 1 tick 사이에:
- `dateHeaderRef`, `tableContainerRef` 가 한 번 떼어졌다 붙음
- `useColumnResize` 의 ResizeObserver 가 재구독
- InlineInput 의 편집 상태 있으면 lose (사용자 편집 직전이라면 손실)
- DragOverlay 진행 중이면 cancel

**현실 영향**: 페이지 첫 로드 시 모바일 한정으로 1회 발생. 사용자가 인터랙션 시작하기 전이라 사실상 무영향.

**완화책 (선택)**: `useIsMobile` 초기값을 `window.innerWidth < 768` 로 sync 평가하여 첫 paint 부터 정확한 분기. 단 SSR 시 에러. 클라이언트 전용 SPA 이므로 안전.
→ 이 변경은 Step #02 범위 밖. **현 useIsMobile 그대로 사용**.

### 4) DnD / 모달 / 단축키 / SSE — Parent 유지
- 모두 `<RoomAssignment>` 의 RootJSX 에 있음 (분기 바깥)
- 분기는 매트릭스 영역에만 적용. DragOverlay, GuestContextMenu, 모달 11종 모두 영향 없음

---

## 시나리오 비교

| # | 시나리오 | Step #01 후 | Step #02 후 | 차이 |
|---|---------|-------------|-------------|------|
| 1 | PC 페이지 로드 | DesktopLayout 렌더 | 동일 (isMobile=false 분기) | 없음 |
| 2 | 모바일 페이지 로드 | DesktopLayout 렌더 | MobileLayout → DesktopLayout 렌더 | 컴포넌트 트리 1단 차이, 시각 동일 |
| 3 | 모바일 페이지 첫 paint (useIsMobile 초기 false) | DesktopLayout | DesktopLayout (분기 false 로 평가) | 없음 |
| 4 | 모바일 mount 후 isMobile true 로 전환 | (해당 없음 — 분기 없었음) | DesktopLayout → MobileLayout 트리 교체 발생 | DOM 한 번 재마운트 (모바일 첫 로드 시점) |
| 5 | PC 에서 윈도우 좁혀 768px 미만으로 | (분기 없음) | MobileLayout 로 전환 | 컴포넌트 재마운트, 단 렌더 출력 동일 |
| 6 | PC 에서 모든 인터랙션 (드래그/편집/모달/단축키 등) | 정상 | 동일 | 없음 |
| 7 | 모바일 long-press 선택 + QuickMenuBar | 정상 | 동일 (QuickMenuBar 는 분기 바깥) | 없음 |
| 8 | DragOverlay 표시 | DndContext 안 | 동일 | 없음 |

---

## 변경 파일 명세

### 신규
- `frontend/src/pages/RoomAssignment/layouts/MobileLayout.tsx` (+15 lines)

### 수정
- `frontend/src/pages/RoomAssignment.tsx`
  - import `MobileLayout` 추가 (+1 line)
  - layoutProps 변수 도입 + `isMobile ? Mobile : Desktop` 분기 (~50 lines, 단 들여쓰기/중괄호 위주이고 prop 명세는 동일)
  - 순 증가: ~5-10 lines

### 영향 없음
- `DesktopLayout.tsx`
- `types.ts`
- 모든 하위 컴포넌트, hooks, 모달, utils

---

## 검증 체크리스트

### 정적 분석
- [ ] `npx tsc --noEmit` 통과 (에러 0)
- [ ] `npm run build` 성공
- [ ] `MobileLayout` 이 `DesktopLayoutProps` 와 동일 타입 받음 (re-export 또는 import)

### PC 환경 (≥768px) — Step #01 시나리오 20개와 동일하게 동작
- [ ] 페이지 로드 — DesktopLayout 만 렌더 (React DevTools 로 확인)
- [ ] 매트릭스 / 드래그 / 인라인 편집 / SMS / 컨텍스트 메뉴 / 모달 / 단축키 — Step #01 직후와 시각/동작 동일
- [ ] 윈도우 폭을 768px 이상에서 변화시켰을 때 분기 변동 없음

### 모바일 환경 (<768px)
- [ ] 페이지 로드 — 최종 렌더가 `MobileLayout > DesktopLayout` 트리 (React DevTools)
- [ ] 시각: PC 와 동일한 가로 매트릭스가 그대로 보임 (overflow 도 그대로)
- [ ] long-press 선택 → QuickMenuBar 컨텍스트 버튼
- [ ] 모달 11종 정상 동작

### Transition (PC ↔ 모바일)
- [ ] 브라우저 윈도우를 좁히면 768px 경계에서 분기 전환
- [ ] 전환 시 시각 변화 없음 (둘 다 동일 JSX)
- [ ] 전환 시 콘솔 에러 없음
- [ ] 전환 시 sticky / 드래그 / 모달 상태 안정 (편집 중이면 unmount 됨 — 알려진 부수효과)

---

## Step #02 이후 미리보기

| Step | 작업 | MobileLayout 변화 | DesktopLayout 변화 |
|------|------|------------------|------------------|
| **#02 (이번)** | wrapper 도입 | wrapper (DesktopLayout 호출) | 변경 없음 |
| **#02.5 (선택)** | wrapper 를 full copy 로 펼치기 | DesktopLayout JSX 1:1 사본 | 변경 없음 |
| **#03** | MobileRoomCard 도입 | RoomRow 영역만 카드로 교체 | 변경 없음 |
| **#04** | MobileZones | 4 zones 카드 그리드 | 변경 없음 |
| **#05** | 모바일 헤더 영역 | PageHeader/SummaryCards/CampaignToolbar 모바일화 | 변경 없음 |
| **#06** | 마무리 (필요 시) | 인터랙션 다듬기 | 변경 없음 |

**핵심**: Step #02 부터 #06 까지 **DesktopLayout 은 불변**. PC 영향 0 보장.

---

## 결정 사항

| 질문 | 결정 |
|------|------|
| MobileLayout 첫 모양 | **옵션 A — wrapper (DesktopLayout 그대로 호출)** ★ 사용자 확정 |
| Props 전달 방식 | `layoutProps` 변수로 묶어 양쪽 분기에 spread (TypeScript 누락 검출) |
| `DesktopLayoutProps` export | DesktopLayout.tsx 에서 이미 `export interface DesktopLayoutProps` → MobileLayout 이 import 해서 사용 |
| `useIsMobile` 초기값 | 변경 없음 (false). 첫 paint 후 1 tick 내 분기 전환은 알려진 부수효과 |

---

## 환각 방지 메모

본 사전조사는 Step #01 완료 직후의 `RoomAssignment.tsx` (1196 lines) 와 `DesktopLayout.tsx` (315 lines) 를 직접 grep 으로 확인하며 작성:

- `useIsMobile` 호출 위치: `RoomAssignment.tsx:180` (이미 존재, Step #01 이전부터)
- `DesktopLayout` 호출 위치: `RoomAssignment.tsx:858` (Step #01 에서 추가)
- `DesktopLayoutProps` export: `DesktopLayout.tsx:42` (Step #01 에서 추가, `export interface`)
- `layouts/` 폴더 존재: Step #01 에서 `DesktopLayout.tsx` 와 함께 생성됨
