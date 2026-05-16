# 단계 #4: Grip div에 useDraggable 연결 (GuestRow + CompactGuestCell)

> 작성일: 2026-05-16
> 단계: 4 / 11
> 섹션: B. dnd-kit 골격 설치
> 동작 변화: ⚪ 시각 변화만 — `onDragEnd` noop이라 드래그 후에도 이동 없음. `isDragging` 시 grip div `opacity-50`
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`GuestRow.tsx` / `CompactGuestCell.tsx` 의 grip div에 `useDraggable` 연결.
PC에서 그립 드래그 시 dnd-kit이 drag start/end 사이클 인식. `onDragEnd` 는 아직 noop이라 실제 이동은 안 일어남.

---

## 2. dnd-kit id 네임스페이스 결정

연박 예약은 오늘/다음날 컬럼에 동시에 존재 → `GuestRow`(오늘)와 `CompactGuestCell`(다음날) 양쪽에서 `useDraggable({ id: res.id })`로 동일 ID 사용 시 dnd-kit 내부 ID 충돌(dev warning + 마지막 mount만 유효).

**해결**:
- `GuestRow` → `id: \`guest-${res.id}\`` (오늘 컬럼)
- `CompactGuestCell` → `id: \`guest-next-${guest.id}\`` (다음날 컬럼)
- `onDragEnd`(#6)에서 prefix로 출발지 판별, 숫자 부분만 추출하여 `handleDropOnRoom/Pool/Party`에 전달

---

## 3. 변경 대상 코드

### 3-1. `GuestRow.tsx` — import + useDraggable 호출 + grip div 적용

**Before** (1-3줄):
```tsx
import React from 'react';
import type { Dayjs } from 'dayjs';
import { Circle } from 'lucide-react';
```

**After**:
```tsx
import React from 'react';
import type { Dayjs } from 'dayjs';
import { Circle } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { useIsDesktop } from '../../../../hooks/use-desktop';
```

**Before** (함수 본문 상단 81~89줄):
```tsx
  const genderPeople = formatGenderPeople(res);
  const longStay = !!res.is_long_stay;
  const isCancelled = res.status === 'cancelled';
```

**After**:
```tsx
  const genderPeople = formatGenderPeople(res);
  const longStay = !!res.is_long_stay;
  const isCancelled = res.status === 'cancelled';
  const isDesktop = useIsDesktop();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `guest-${res.id}`,
    disabled: !isDesktop || isCancelled,
  });
```

**Before** (grip div 165-180줄):
```tsx
{showGrip && !isCancelled && (
  <div
    className={`flex items-center justify-center w-10 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
      isSelected
        ? 'text-[#3182F6] dark:text-[#3182F6]'
        : longStay ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
    }`}
  >
```

**After**:
```tsx
{showGrip && !isCancelled && (
  <div
    ref={setNodeRef}
    {...attributes}
    {...listeners}
    className={`flex items-center justify-center w-10 px-0.5 flex-shrink-0 ${isDesktop ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'} text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
      isDragging ? 'opacity-40' : ''
    } ${
      isSelected
        ? 'text-[#3182F6] dark:text-[#3182F6]'
        : longStay ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
    }`}
  >
```

### 3-2. `CompactGuestCell.tsx` — 동일 패턴, prefix 다름

**Before** (1-3줄):
```tsx
import React from 'react';
import type { Dayjs } from 'dayjs';
import { Circle } from 'lucide-react';
```

**After**:
```tsx
import React from 'react';
import type { Dayjs } from 'dayjs';
import { Circle } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { useIsDesktop } from '../../../../hooks/use-desktop';
```

**Before** (함수 본문 상단 41줄 부근):
```tsx
}: CompactGuestCellProps) {
  const gp = formatGenderPeople(guest);
```

**After**:
```tsx
}: CompactGuestCellProps) {
  const gp = formatGenderPeople(guest);
  const isDesktop = useIsDesktop();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `guest-next-${guest.id}`,
    disabled: !isDesktop,
  });
```

**Before** (grip div 67-81줄):
```tsx
<div
  onClick={(e: React.MouseEvent) => onGripClick(e, guest.id)}
  className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
    isSelected
      ? 'text-[#3182F6] dark:text-[#3182F6]'
      : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
  }`}
>
```

**After**:
```tsx
<div
  ref={setNodeRef}
  {...attributes}
  {...listeners}
  onClick={(e: React.MouseEvent) => onGripClick(e, guest.id)}
  className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 ${isDesktop ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'} text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
    isDragging ? 'opacity-40' : ''
  } ${
    isSelected
      ? 'text-[#3182F6] dark:text-[#3182F6]'
      : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
  }`}
>
```

> **참고**: CompactGuestCell의 onClick은 #8에서 PC 가드(`if (isDesktop) return`) 추가. 본 단계에서는 유지.

---

## 4. 동작 동등성 / 변화

| 케이스 | 기존 | 이 단계 이후 |
|---|---|---|
| PC — 그립 단순 클릭(이동<4px) | 행 onClick 버블링/직접 → 선택 토글 | onClick 정상 발화 → 선택 토글 ✅ (#8 전까지 유지) |
| PC — 그립 드래그(이동≥4px) | 선택 토글 (드래그 인식 없음) | `useDraggable` drag start → grip `opacity-40` → drop 영역 없음 → `onDragEnd`(noop) → 시각 복원. **이동 안 일어남** ✅ (#6 전까지) |
| 모바일 — 그립 클릭 | 선택 토글 | `disabled: !isDesktop` → useDraggable 비활성. 선택 토글 그대로 ✅ |
| 모바일 — 그립 롱프레스 | 컨텍스트 메뉴 | 동일 (롱프레스 핸들러는 행 onTouchStart/End) ✅ |
| 취소 행(isCancelled) | grip 미렌더 | grip 미렌더 + `disabled` ✅ |
| CompactGuestCell — 모바일 그립 클릭 | onClick → 선택 토글 | onClick → 선택 토글 ✅ |
| CompactGuestCell — PC 그립 드래그 | 선택 토글 | drag start → opacity-40 → drop 영역 없음 → 미이동 ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `useGuestSelection`/`useGuestMove`/`useGuestDropTarget` — 시그니처 변경 없음
- 다른 InlineInput / SmsCell / context menu — 영향 없음
- showGrip prop — 그대로
- isSelected, selectionActive — 그대로
- longStay 색상 클래스 — 그대로
- 모바일 onTouchStart/Move/End/Cancel (롱프레스) — 행 자체에 바인딩 (107-149줄), grip div와 별개 → 영향 없음

---

## 6. 검증 체크리스트

- [ ] PC 데스크탑 viewport:
  - 그립을 4px 이상 드래그 시 grip opacity-40, drag 사이클 확인 (콘솔에 dnd-kit 동작 확인 가능)
  - 드롭 영역 없으므로 release 시 onDragEnd noop → 원위치
  - 그립 단순 클릭 시 선택 토스트 표시 (기존 동작)
- [ ] 모바일 viewport(<1024px):
  - 기존 클릭-선택, 롱프레스 컨텍스트 메뉴 동작 정상
  - 드래그 시도해도 useDraggable disabled → 아무 일도 안 일어남
- [ ] 취소 행: grip 미렌더 + 드래그 시도 안 됨
- [ ] 연박 예약: 오늘과 다음날 컬럼에 동시 표시 → useDraggable id 충돌 경고 없음 (prefix 분리)
- [ ] TypeScript 빌드 오류 없음
