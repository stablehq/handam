# Mobile Layout Step #03a — MobileLayout 확장 (wrapper → full JSX copy)

> 작성일: 2026-05-20
> 상태: 사전조사 검토 대기
> 부모 plan: [mobile-layout-migration-plan.md](./mobile-layout-migration-plan.md)
> 직전 단계: [Step #02 — MobileLayout 빈 골격](./mobile-layout-step-02-mobile-skeleton.md) (완료)
> 동작 변화: **없음** (mobile JSX 가 DesktopLayout 과 라인 단위 동일)

---

## 목표

현재 wrapper 인 `MobileLayout.tsx` (19줄) 을 **DesktopLayout 의 JSX 본문 전체를 인라인으로 펼친 독립 컴포넌트** (~300줄) 로 확장.

- MobileLayout 이 렌더하는 JSX 가 DesktopLayout 과 line-by-line 동일
- 시각/동작 변화 0 (모바일 시각도 Step #02 와 동일)
- Step #03b 이후 모바일 JSX 를 독립적으로 수정할 base 마련

---

## 왜 이 단계가 필요한가

Step #02 의 wrapper 는 `<DesktopLayout {...props}/>` 한 줄. 모바일 JSX 를 바꾸려면 DesktopLayout 안을 직접 손대거나, DesktopLayout 에 mobile toggle 을 추가해야 함. 둘 다 PC 영향 위험이 있어 부모 plan 의 "DesktopLayout 불변" 원칙 위반.

MobileLayout 을 독립 JSX 로 만들면:
- Step #03b ~ #06 의 모든 모바일 변화는 MobileLayout 안에서만 이루어짐
- **DesktopLayout 은 Step #01 이후 한 줄도 안 변함** → PC 동작 보장이 코드 구조로 강제됨

---

## 원칙

1. **PC(≥768px) 동작 0 변경** — DesktopLayout 손대지 않음
2. **모바일(<768px) 동작 0 변경** — JSX 가 DesktopLayout 과 line-by-line 동일
3. **MobileLayoutProps = DesktopLayoutProps** — Step #03a 단독으로는 동일. Step #03b 이후 필요 시 별도 인터페이스로 분리
4. **import 도 1:1 일치** — DesktopLayout 이 import 하는 모든 항목을 MobileLayout 도 import (단, MobileLayout 자체는 import 하지 않음)

---

## 의도된 동작 변화

**없음.** 단계 전후로 PC/모바일 user 모두 인지 가능한 차이 0.

| 화면 폭 | Step #02 후 | Step #03a 후 | 차이 |
|---------|-------------|--------------|------|
| ≥768px (PC) | DesktopLayout 렌더 | DesktopLayout 렌더 (분기 false) | 없음 |
| <768px (모바일) | MobileLayout → DesktopLayout 렌더 | MobileLayout 렌더 (DesktopLayout 호출 없음) | 컴포넌트 트리 1단 줄어듦, **시각 동일** |

### 부수효과 비교 (Step #02 와 차이)

| 항목 | Step #02 (wrapper) | Step #03a (full copy) |
|------|--------------------|-----------------------|
| 컴포넌트 트리 (모바일) | `MobileLayout > DesktopLayout > ...` | `MobileLayout > ...` (1단 줄음) |
| isMobile 분기 전환 시 remount | DesktopLayout 인스턴스가 새로 mount | MobileLayout 의 자식들이 새로 mount (수는 동일) |
| useColumnResize ref attach | DesktopLayout 안의 `<div ref=...>` | MobileLayout 안의 동일 `<div ref=...>` |

---

## 현재 구조 (Step #02 직후)

### `frontend/src/pages/RoomAssignment/layouts/MobileLayout.tsx` (19 lines)

```tsx
/**
 * RoomAssignment 페이지의 모바일(<768px) 레이아웃.
 *
 * Mobile Layout Step #02: 분기 도입 단계.
 * 이 단계의 MobileLayout 은 DesktopLayout 을 그대로 호출하는 wrapper 에 불과하다.
 * ...
 */
import { DesktopLayout, type DesktopLayoutProps } from './DesktopLayout';

export function MobileLayout(props: DesktopLayoutProps) {
  return <DesktopLayout {...props} />;
}
```

### `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` (315 lines)

```tsx
import React from 'react';
import type { Dayjs } from 'dayjs';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import dayjs from 'dayjs';
import { TextInput } from '@/components/ui/input';
import { PageHeader } from '../components/PageHeader';
import { SummaryCards } from '../components/SummaryCards';
import { CampaignToolbar } from '../components/CampaignToolbar';
import { BuildingGroup, type BuildingGroupData } from '../components/BuildingGroup';
import type { RoomEntry } from '../components/RoomRow';
import { UnassignedZone } from '../components/zones/UnassignedZone';
import { PartyZone } from '../components/zones/PartyZone';
import { UnstableZone } from '../components/zones/UnstableZone';
import { CancelledZone } from '../components/zones/CancelledZone';
import type { ColWidths } from '../hooks/useColumnResize';
import type { Reservation, Summary } from '../types';

// ... 42 props interface ...

export function DesktopLayout({
  // ... destructured props ...
}: DesktopLayoutProps) {
  return (
    <>
      <PageHeader />
      <SummaryCards ... />
      <CampaignToolbar ... />
      <div className="section-card !overflow-visible w-max min-w-full">
        ... full JSX body ...
      </div>
    </>
  );
}
```

---

## Before / After 코드 인용

### MobileLayout.tsx (Before, 19 lines)

```tsx
import { DesktopLayout, type DesktopLayoutProps } from './DesktopLayout';

export function MobileLayout(props: DesktopLayoutProps) {
  return <DesktopLayout {...props} />;
}
```

### MobileLayout.tsx (After, ~315 lines)

```tsx
/**
 * RoomAssignment 페이지의 모바일(<768px) 레이아웃.
 *
 * Mobile Layout Step #03a (2026-05-20): wrapper 를 full JSX copy 로 확장.
 * 이 단계에서는 DesktopLayout 의 JSX 본문을 라인 단위 1:1 로 복사.
 * 시각/동작 변화 0 — Step #02 와 동일하게 렌더.
 *
 * 향후 단계:
 *  - Step #03b: MobileRoomCard 도입 + 컬럼 헤더 제거 + 객실 영역 카드화
 *  - Step #04+: Zones, Header 등 추가 모바일화
 *  - DesktopLayout 은 손대지 않음 (PC 동작 보장)
 *
 * 사전조사: docs/plans/mobile-layout-step-03a-mobile-expand.md
 */

import React from 'react';
import type { Dayjs } from 'dayjs';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import dayjs from 'dayjs';
import { TextInput } from '@/components/ui/input';
import { PageHeader } from '../components/PageHeader';
import { SummaryCards } from '../components/SummaryCards';
import { CampaignToolbar } from '../components/CampaignToolbar';
import { BuildingGroup } from '../components/BuildingGroup';
import { UnassignedZone } from '../components/zones/UnassignedZone';
import { PartyZone } from '../components/zones/PartyZone';
import { UnstableZone } from '../components/zones/UnstableZone';
import { CancelledZone } from '../components/zones/CancelledZone';
import { type DesktopLayoutProps } from './DesktopLayout';

export function MobileLayout({
  // SummaryCards
  summary,
  hasUnstable,
  // CampaignToolbar
  templateLabels,
  selectedTemplateKey,
  setSelectedTemplateKey,
  campaignDropdownOpen,
  setCampaignDropdownOpen,
  campaignDropdownRef,
  targets,
  clearTargets,
  sending,
  loadTargets,
  requestSendCampaign,
  onOpenTableSettings,
  onAddPartyGuest,
  // Date nav
  selectedDate,
  setSelectedDate,
  navigateDate,
  animDirection,
  // Column resize / sticky
  dateHeaderRef,
  tableContainerRef,
  dateHeaderH,
  resizeGuideX,
  startResize,
  colWidths,
  GUEST_COLS,
  NEXT_GUEST_COLS,
  NEXT_DAY_EXPANDED_WIDTH,
  nextDayExpanded,
  setNextDayExpanded,
  // BuildingGroup loop
  buildingGroups,
  collapsedBuildings,
  toggleBuildingCollapse,
  renderRoomRow,
  loading,
  // Zones
  unassigned,
  nextDayUnassigned,
  partyOnly,
  nextDayPartyOnly,
  unstableGuests,
  cancelledGuests,
  sharedZoneProps,
}: DesktopLayoutProps) {
  return (
    <>
      <PageHeader />

      <SummaryCards summary={summary} hasUnstable={hasUnstable} />

      <CampaignToolbar
        templateLabels={templateLabels}
        selectedTemplateKey={selectedTemplateKey}
        setSelectedTemplateKey={setSelectedTemplateKey}
        campaignDropdownOpen={campaignDropdownOpen}
        setCampaignDropdownOpen={setCampaignDropdownOpen}
        campaignDropdownRef={campaignDropdownRef}
        targets={targets}
        clearTargets={clearTargets}
        sending={sending}
        loadTargets={loadTargets}
        requestSendCampaign={requestSendCampaign}
        onOpenTableSettings={onOpenTableSettings}
        onAddPartyGuest={onAddPartyGuest}
      />

      {/* Main grid card */}
      <div className="section-card !overflow-visible w-max min-w-full">
        {/* Date navigation header — sticky */}
        <div ref={dateHeaderRef} className="sticky top-0 z-20">
          ... (DesktopLayout 와 line-by-line 동일) ...
        </div>

        <div className="section-body !pt-2">
          ... (DesktopLayout 와 line-by-line 동일) ...

          <div ref={tableContainerRef} className="relative rounded-xl border ...">
            ... (column header, BuildingGroup loop, 4 zones — DesktopLayout 와 line-by-line 동일) ...
          </div>
        </div>
      </div>
    </>
  );
}
```

**핵심**: JSX 의 모든 `className`, `key`, `ref`, prop 명, prop 값, 들여쓰기, 줄바꿈, 주석까지 DesktopLayout 과 1:1 일치.

---

## 동작 동등성 증명

### 1) MobileLayout 의 렌더 결과
- 들어가는 props 가 DesktopLayout 과 동일
- JSX 가 line-by-line 동일
- 결과: 동일 DOM 트리

### 2) RoomAssignment.tsx 의 분기
- 분기 자체는 변경 없음: `{isMobile ? <MobileLayout/> : <DesktopLayout/>}`
- isMobile=false (PC): DesktopLayout 그대로 — 영향 없음
- isMobile=true (모바일): MobileLayout 이 독립 JSX 렌더 — Step #02 의 `MobileLayout→DesktopLayout` 와 동일 DOM 출력

### 3) Ref / Sticky / Column resize
- `dateHeaderRef`, `tableContainerRef` 는 parent 에서 생성되어 MobileLayout 에 prop 으로 전달
- MobileLayout 안의 `<div ref={dateHeaderRef}>` 가 부착됨 → DesktopLayout 안의 동일 `<div>` 와 동일 ref 인스턴스
- useColumnResize 의 ResizeObserver 는 어느 layout 이 렌더되든 동일 DOM 을 관찰

### 4) Fragment containing block
- MobileLayout 도 DesktopLayout 처럼 `<>...</>` 로 감쌈
- sticky positioning 의 containing block 은 부모(`<div className="space-y-4 pb-14 min-w-0">`) 이며 변하지 않음

### 5) DnD / 모달 / 단축키 / SSE / 컨텍스트 메뉴 / DragOverlay
- 모두 RoomAssignment.tsx 의 outer JSX 에 있음 (분기 바깥)
- MobileLayout 변경과 무관

---

## 시나리오 비교

| # | 시나리오 | Step #02 후 | Step #03a 후 | 차이 |
|---|---------|-------------|--------------|------|
| 1 | PC 페이지 로드 | DesktopLayout 렌더 | 동일 (isMobile=false) | 없음 |
| 2 | 모바일 페이지 로드 (초기 isMobile=false → mount 후 true) | DesktopLayout → MobileLayout(=DesktopLayout) 트리 교체 | DesktopLayout → MobileLayout(독립) 트리 교체 | 없음 (출력 동일) |
| 3 | 모바일 매트릭스 시각 | DesktopLayout 출력 | MobileLayout 출력 (line-by-line 동일) | 없음 |
| 4 | 모바일 모든 인터랙션 (드래그/편집/SMS/우클릭/모달) | 정상 | 동일 | 없음 |
| 5 | 컬럼 폭 리사이즈 (모바일) | 정상 | 동일 (ref 동일 인스턴스) | 없음 |
| 6 | sticky 헤더 (모바일 스크롤) | 정상 | 동일 (Fragment containing block 보존) | 없음 |
| 7 | 다음날 컬럼 펼침/접힘 | 정상 | 동일 | 없음 |
| 8 | BuildingGroup 접기/펴기 | 정상 | 동일 | 없음 |
| 9 | 4 zones 표시 | 정상 | 동일 | 없음 |
| 10 | dark mode | 정상 | 동일 (className 동일) | 없음 |
| 11 | isMobile 경계 전환 (PC ↔ 모바일) | DesktopLayout ↔ MobileLayout(=Desktop) 트리 교체 | DesktopLayout ↔ MobileLayout(독립) 트리 교체 | 없음 |

---

## 변경 파일 명세

### 수정
- `frontend/src/pages/RoomAssignment/layouts/MobileLayout.tsx`
  - 19줄 → 약 315줄 (~+296)
  - JSX 본문은 DesktopLayout 과 line-by-line 동일

### 영향 없음
- `RoomAssignment.tsx`
- `DesktopLayout.tsx`
- `types.ts`
- 모든 하위 컴포넌트 / hooks / 모달 / utils

---

## 검증 체크리스트

### 정적 분석
- [ ] `npx tsc --noEmit` 통과 (에러 0)
- [ ] `npm run build` 성공
- [ ] **MobileLayout 과 DesktopLayout 의 JSX body 가 라인 단위 동일** (`diff` 도구로 비교, import/함수 시그니처/주석 제외)

### PC 환경 (≥768px) — Step #02 시나리오와 동일
- [ ] 페이지 로드 — Step #02 직후와 시각/동작 동일
- [ ] React DevTools — DesktopLayout 만 렌더되는지 (MobileLayout 표시 안 됨)

### 모바일 환경 (<768px)
- [ ] 페이지 로드 — Step #02 직후와 시각/동작 동일 (가로 매트릭스 그대로)
- [ ] React DevTools — 컴포넌트 트리가 `MobileLayout > [PageHeader, SummaryCards, CampaignToolbar, ...]` (이전엔 `MobileLayout > DesktopLayout > [...]` 였음)
- [ ] 매트릭스 / 컬럼 헤더 / 다음날 컬럼 / sticky / 드래그 / 인라인 편집 / SMS / 모달 — 모두 PC 와 동일하게 동작

### Transition (PC ↔ 모바일)
- [ ] 브라우저 윈도우 좁히기 → 768px 경계에서 분기 전환
- [ ] 전환 시 시각 변화 없음 (둘 다 동일 JSX 렌더)
- [ ] 전환 시 콘솔 에러 없음
- [ ] 전환 시 sticky / 드래그 / 모달 상태 안정 (편집 중이면 unmount — 알려진 부수효과, Step #02 와 동일)

### 라인 단위 검증 (중요 ★)

PR 머지 전에 다음을 수행:
1. `git diff main..HEAD -- frontend/src/pages/RoomAssignment/layouts/MobileLayout.tsx` 의 added 영역 추출
2. `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` 의 동일 영역과 line-by-line 비교
3. 차이는 다음 항목만 허용:
   - 함수명 `DesktopLayout` → `MobileLayout`
   - 파일 상단 docstring 주석
   - import 에서 `DesktopLayoutProps` 가 `type` import 인지 여부 (기능 동일)
4. 그 외 모든 JSX (className, key, ref, prop명, prop값, 들여쓰기, 줄바꿈) 가 동일해야 함

---

## Step #03a 이후 미리보기

| Step | 작업 | 영향 | PR |
|------|------|------|-----|
| **#03b** | MobileRoomCard 신규 + MobileLayout 의 객실 영역 카드화 + 컬럼 헤더 제거 | 모바일 객실 영역 시각 변화 (첫 실질 변화) | 별도 PR |
| **#04** | MobileZones (Unassigned/Party/Unstable/Cancelled 카드화) | 모바일 zones 시각 변화 | 별도 PR |
| **#05** | Mobile PageHeader / SummaryCards / CampaignToolbar | 모바일 헤더 영역 시각 변화 | 별도 PR |
| **#06** | 마무리 (필요 시 bottom sheet, 터치 타겟) | 모바일 인터랙션 | 별도 PR |

**Step #03a 이후의 모든 단계는 MobileLayout 만 수정** — DesktopLayout, RoomAssignment.tsx, 하위 컴포넌트 영향 없음. PC 동작 0 변화가 코드 구조로 강제됨.

---

## 결정 사항

| 질문 | 결정 |
|------|------|
| MobileLayoutProps 타입 | **DesktopLayoutProps 재사용**. Step #03a 단독으로는 동일. Step #03b 에서 필요 시 별도 인터페이스로 분리. |
| import 순서 / 그룹화 | DesktopLayout 의 import 그룹과 동일 순서로 작성 (검증 용이성) |
| 함수 시그니처 (destructure 방식) | DesktopLayout 의 destructured props 와 동일 순서/그룹화 |
| 주석 docstring | MobileLayout 전용 docstring (Step #03a 작업 명시 + 향후 단계 안내) |

---

## 환각 방지 메모

본 사전조사는 Step #02 완료 직후의 다음 파일을 직접 grep/Read 로 확인하며 작성:

- `frontend/src/pages/RoomAssignment.tsx` (1201 lines, isMobile 분기 line 911)
- `frontend/src/pages/RoomAssignment/layouts/MobileLayout.tsx` (19 lines, wrapper)
- `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` (315 lines, 본체)

DesktopLayout 의 import 명세 (Step #03a 에서 MobileLayout 이 따라야 할 목록):
- `React` (default)
- `Dayjs` (type-only, from dayjs)
- `ChevronLeft`, `ChevronRight`, `ChevronsLeft`, `ChevronsRight` (lucide-react)
- `dayjs` (default)
- `TextInput` (from @/components/ui/input)
- `PageHeader`, `SummaryCards`, `CampaignToolbar`, `BuildingGroup`, `BuildingGroupData` (type), `RoomEntry` (type)
- `UnassignedZone`, `PartyZone`, `UnstableZone`, `CancelledZone`
- `ColWidths` (type-only, from ../hooks/useColumnResize)
- `Reservation`, `Summary` (type-only, from ../types)
- `CampaignToolbarProps`, `SharedZoneProps` (type aliases derived from ComponentProps)

**주의**: MobileLayout 이 `DesktopLayoutProps` 만 import 하면 충분 — JSX 안에서 직접 쓰이는 컴포넌트만 import 하면 됨. `BuildingGroupData`, `RoomEntry`, `Reservation` 등 type-only import 는 props 인터페이스 정의용이므로 MobileLayout 이 인터페이스를 재정의하지 않는 한 import 불필요.
