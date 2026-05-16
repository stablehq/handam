# 단계 #5: useDroppable 연결 (RoomRow + GuestZone)

> 작성일: 2026-05-16
> 단계: 5 / 11
> 섹션: B. dnd-kit 골격 설치
> 동작 변화: ⚪ 시각 보강 — PC에서 drag 중 `isOver` 시 기존과 동일한 배경 표시. `onDragEnd` noop이라 이동 없음
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`RoomRow.tsx` / `GuestZone.tsx` 의 드롭 영역 div에 `useDroppable` 연결.
dnd-kit이 drop zone을 인식하기 시작 → drag 중 `isOver` 시각 표시 활성.

---

## 2. ref 합성 / 핸들러 충돌 결론

| 항목 | 기존 (`useGuestDropTarget`) | dnd-kit (`useDroppable`) | 충돌 여부 |
|---|---|---|---|
| ref | 미사용 | `setNodeRef` (div ref) | **없음** — 별도 슬롯 |
| `data-drop-zone` attr | 있음 | 없음 | **없음** |
| `onMouseEnter`/`Leave` | 있음 (enabled=true 시) | 없음 (dnd-kit 자체 hit-test) | **없음** |
| isOver/isDragOver | `isDragOver` (호버 매칭) | `isOver` (drag 중) | **OR 처리** — 두 시스템 시각 효과 합집합 |

**결론**: ref 충돌 없음. 기존 `dropZoneProps` (`data-drop-zone`, mouse handlers) 그대로 spread + dnd-kit `setNodeRef`를 div ref에 별도 연결.

---

## 3. dnd-kit id 충돌 회피

`useDroppable.id`는 `UniqueIdentifier` 필수 (`string | number`). undefined / 빈 문자열 불가.

- **RoomRow**: 항상 `room-${room_id}` / `next-room-${room_id}` 사용 (room_id 항상 존재).
- **GuestZone**: `zoneId`/`nextZoneId`가 optional이므로 noop id fallback 필요. `disabled: true`라도 id는 unique 필요.
  - main fallback: `__noop-zone-${title}-main`
  - next fallback: `__noop-zone-${title}-next`

---

## 4. 변경 대상 코드

### 4-1. `RoomRow.tsx` — import + useDroppable 호출 + ref 연결

**Before** (1-7줄):
```tsx
import React from 'react';
import type { Reservation } from '../types';
import type { HoverZoneState } from '../hooks/useHoverZone';
import { useGuestDropTarget } from '../hooks/useGuestDropTarget';
```

**After**:
```tsx
import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { Reservation } from '../types';
import type { HoverZoneState } from '../hooks/useHoverZone';
import { useGuestDropTarget } from '../hooks/useGuestDropTarget';
import { useIsDesktop } from '../../../hooks/use-desktop';
```

**Before** (130-139줄):
```tsx
  const main = useGuestDropTarget({
    zoneId: `room-${room_id}`,
    hover, setHover, clearHover,
    enabled: selectionActive && isActive,
  });
  const next = useGuestDropTarget({
    zoneId: `next-room-${room_id}`,
    hover, setHover, clearHover,
    enabled: nextDayExpanded && selectionActive && isActive,
  });
```

**After**:
```tsx
  const isDesktop = useIsDesktop();
  const main = useGuestDropTarget({
    zoneId: `room-${room_id}`,
    hover, setHover, clearHover,
    enabled: selectionActive && isActive,
  });
  const next = useGuestDropTarget({
    zoneId: `next-room-${room_id}`,
    hover, setHover, clearHover,
    enabled: nextDayExpanded && selectionActive && isActive,
  });
  const dropMain = useDroppable({
    id: `room-${room_id}`,
    disabled: !isDesktop || !isActive,
  });
  const dropNext = useDroppable({
    id: `next-room-${room_id}`,
    disabled: !isDesktop || !isActive || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;
```

**Before** (141-151줄):
```tsx
    <div
      className={`group relative flex select-none transition-colors
        ${main.isDragOver
          ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
          : ''
        } ${selectionActive && isActive ? 'cursor-pointer' : ''}`}
      style={{ minHeight: `${totalRows * rowHeight}px`, ...(main.isDragOver ? {} : stripeBgStyle) }}
      {...main.dropZoneProps}
      onClick={isActive ? onDropZoneClick : undefined}
    >
```

**After**:
```tsx
    <div
      ref={dropMain.setNodeRef}
      className={`group relative flex select-none transition-colors
        ${isMainOver
          ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
          : ''
        } ${selectionActive && isActive ? 'cursor-pointer' : ''}`}
      style={{ minHeight: `${totalRows * rowHeight}px`, ...(isMainOver ? {} : stripeBgStyle) }}
      {...main.dropZoneProps}
      onClick={isActive ? onDropZoneClick : undefined}
    >
```

**Before** (174줄, 186줄 — 빈 슬롯 표시):
```tsx
{main.isDragOver ? '여기에 놓으세요' : ''}
```

**After** (2곳):
```tsx
{isMainOver ? '여기에 놓으세요' : ''}
```

**Before** (193-203줄 — 다음날 컬럼 div):
```tsx
      <div
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none border-b transition-all duration-200 ${
          next.isDragOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30'
            : ''
        } ${selectionActive ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, ...(next.isDragOver ? {} : { ...borderStyle, ...stripeBgStyle }) }}
        {...next.dropZoneProps}
        onClick={nextDayExpanded ? onDropZoneClick : undefined}
      >
```

**After**:
```tsx
      <div
        ref={dropNext.setNodeRef}
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none border-b transition-all duration-200 ${
          isNextOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30'
            : ''
        } ${selectionActive ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, ...(isNextOver ? {} : { ...borderStyle, ...stripeBgStyle }) }}
        {...next.dropZoneProps}
        onClick={nextDayExpanded ? onDropZoneClick : undefined}
      >
```

### 4-2. `GuestZone.tsx` — 동일 패턴 + noop id fallback

**Before** (1-5줄):
```tsx
import React from 'react';
import type { Reservation } from '../../types';
import type { HoverZoneState } from '../../hooks/useHoverZone';
import { useGuestDropTarget } from '../../hooks/useGuestDropTarget';
import { ZONE_ROW_HEIGHT } from '../../utils/layoutConstants';
```

**After**:
```tsx
import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { Reservation } from '../../types';
import type { HoverZoneState } from '../../hooks/useHoverZone';
import { useGuestDropTarget } from '../../hooks/useGuestDropTarget';
import { ZONE_ROW_HEIGHT } from '../../utils/layoutConstants';
import { useIsDesktop } from '../../../../hooks/use-desktop';
```

**Before** (87-100줄):
```tsx
  // 메인 zone 의 드롭존 동작 — 게스트 선택 시에만 활성.
  const main = useGuestDropTarget({
    zoneId: zoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!zoneId && selectionActive,
  });

  // 다음날 컬럼의 드롭존 동작 (펼침 + nextZoneId 있을 때만)
  const next = useGuestDropTarget({
    zoneId: nextZoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!nextZoneId && nextDayExpanded && selectionActive,
  });
```

**After**:
```tsx
  const isDesktop = useIsDesktop();
  // 메인 zone 의 드롭존 동작 — 게스트 선택 시에만 활성.
  const main = useGuestDropTarget({
    zoneId: zoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!zoneId && selectionActive,
  });

  // 다음날 컬럼의 드롭존 동작 (펼침 + nextZoneId 있을 때만)
  const next = useGuestDropTarget({
    zoneId: nextZoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!nextZoneId && nextDayExpanded && selectionActive,
  });

  // dnd-kit useDroppable — PC 드래그. id는 항상 unique 필요 → zoneId 없으면 noop fallback.
  const dropMain = useDroppable({
    id: zoneId || `__noop-zone-${title}-main`,
    disabled: !isDesktop || !accept || !zoneId,
  });
  const dropNext = useDroppable({
    id: nextZoneId || `__noop-zone-${title}-next`,
    disabled: !isDesktop || !accept || !nextZoneId || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;
```

**Before** (102-112줄):
```tsx
    <div
      className={`group flex select-none transition-colors ${
        accept && main.isDragOver
          ? hoverBgClass ?? ''
          : guests.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
      } ${selectionActive && accept ? 'cursor-pointer' : ''} ${zoneClassName ?? ''}`}
      style={{ minHeight: `${Math.max(Math.max(1, guests.length), Math.max(1, nextDayGuests.length)) * ZONE_ROW_HEIGHT}px` }}
      {...main.dropZoneProps}
      onClick={accept ? onDropZoneClick : undefined}
    >
```

**After**:
```tsx
    <div
      ref={dropMain.setNodeRef}
      className={`group flex select-none transition-colors ${
        accept && isMainOver
          ? hoverBgClass ?? ''
          : guests.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
      } ${selectionActive && accept ? 'cursor-pointer' : ''} ${zoneClassName ?? ''}`}
      style={{ minHeight: `${Math.max(Math.max(1, guests.length), Math.max(1, nextDayGuests.length)) * ZONE_ROW_HEIGHT}px` }}
      {...main.dropZoneProps}
      onClick={accept ? onDropZoneClick : undefined}
    >
```

**Before** (129줄 — empty 안내):
```tsx
{accept && main.isDragOver ? (emptyMessage ?? '') : ''}
```

**After**:
```tsx
{accept && isMainOver ? (emptyMessage ?? '') : ''}
```

**Before** (137-143줄 — 다음날 컬럼 div):
```tsx
      <div
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200 ${
          next.isDragOver ? hoverBgClass ?? '' : ''
        } ${selectionActive && accept && nextDayExpanded ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, minHeight: `${Math.max(1, nextDayGuests.length) * ZONE_ROW_HEIGHT}px` }}
        {...next.dropZoneProps}
        onClick={accept && nextDayExpanded ? onDropZoneClick : undefined}
      >
```

**After**:
```tsx
      <div
        ref={dropNext.setNodeRef}
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200 ${
          isNextOver ? hoverBgClass ?? '' : ''
        } ${selectionActive && accept && nextDayExpanded ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, minHeight: `${Math.max(1, nextDayGuests.length) * ZONE_ROW_HEIGHT}px` }}
        {...next.dropZoneProps}
        onClick={accept && nextDayExpanded ? onDropZoneClick : undefined}
      >
```

**Before** (158줄 — next empty 안내):
```tsx
{accept && next.isDragOver ? (emptyMessage ?? '') : ''}
```

**After**:
```tsx
{accept && isNextOver ? (emptyMessage ?? '') : ''}
```

---

## 5. 동작 동등성

| 케이스 | 기존 | 이 단계 이후 |
|---|---|---|
| 모바일 — 선택 모드 + 호버 | useGuestDropTarget isDragOver → 배경 | 동일 (useDroppable.isOver는 drag 없으니 false) ✅ |
| PC — 클릭-선택 + 호버 (#8 전) | useGuestDropTarget isDragOver → 배경 | 동일 ✅ (#8 전까지 PC도 선택 모드 가능) |
| PC — 드래그 + 그립 위 hover | (drag 미발동) | useDroppable.isOver → 배경 ✅ (의도된 새 시각 효과) |
| PC — 드래그 + drop 영역 밖 release | (drag 미발동) | onDragEnd noop → 이동 없음, 시각 복원 ✅ |
| 취소/언스테이블 zone | accept=false → 배경 안 켜짐 | 동일 (accept=false → dropMain disabled) ✅ |
| 다음날 컬럼 접힘 | nextDayExpanded=false → next disabled | 동일 ✅ |

---

## 6. 영향받지 않음을 확인할 코드 경로

- `handleDropOnRoom/Pool/Party` — 호출 안 됨 (onDragEnd noop)
- `onDropZoneClick` — onClick 그대로. 모바일 클릭-선택 경로 유지
- `selectionActive` — 동일하게 모든 분기 유지
- `data-drop-zone` attr — 그대로 → 모바일 onClick → onDropZoneClick → handleDropOnRoom 정상
- UnassignedZone / PartyZone / UnstableZone / CancelledZone 래퍼 — GuestZone props 변경 없음, 통과만 함
- `useGuestSelection`, `useGuestMove`, `useContextMenu` — 영향 없음

---

## 7. 검증 체크리스트

- [ ] PC 데스크탑:
  - 그립을 드래그하여 객실 위에 hover → 객실 배경 파랑 (`isMainOver`)
  - 미배정/파티 zone 위 hover → 해당 hoverBgClass 적용
  - 언스테이블/취소 zone 위 hover → 배경 변화 없음 (`accept=false`)
  - drop 영역 밖에서 release → onDragEnd noop → 이동 없음
- [ ] 모바일 viewport:
  - 기존 클릭-선택 시스템 정상
  - dropMain/dropNext disabled로 dnd-kit 미동작
- [ ] 콘솔 — useDroppable id 중복 경고 없음 (noop id fallback 정상)
- [ ] TypeScript 빌드 오류 없음
