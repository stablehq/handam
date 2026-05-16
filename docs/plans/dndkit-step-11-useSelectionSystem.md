# 단계 #11: useSelectionSystem 래퍼 + EMPTY_SELECTION_PROPS

> 작성일: 2026-05-16
> 단계: 11 / 11
> 섹션: F. 모바일 분리 준비
> 동작 변화: ⚪ 없음 — PC fixture는 #1~#10 cascade 비활성과 동일 결과
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`useGuestSelection` + `useHoverZone` 호출을 `useSelectionSystem` 래퍼로 통합.
PC에서는 fixture 반환 → cascade 비활성을 "분기 가드"가 아닌 "값 자체가 noop"으로 강화.
미래 모바일 자체 레이아웃 도입 시 `<RoomAssignmentDesktop>` 진입점에서 fixture만 import → 선택 시스템 일괄 제거 가능.

---

## 2. hook order 보장

useSelectionSystem 내부에서 `useGuestSelection`, `useHoverZone` 모두 **항상** 호출. 분기는 **반환값**에만 적용.
조건부 hook 호출 금지 (React hook rules).

```tsx
export function useSelectionSystem(props) {
  const isDesktop = useIsDesktop();
  const selection = useGuestSelection(props);  // 항상 호출
  const hover = useHoverZone();                 // 항상 호출

  if (isDesktop) return EMPTY_FIXTURE;
  return { ...selection, ...hover };
}
```

---

## 3. PC fixture의 부수 효과 검증 (사실 기반)

PC에서 `useGuestSelection` 내부 effect는 등록되지만 모두 noop으로 수렴:

| effect | PC 동작 |
|---|---|
| toast `useEffect` (L35-55) | `selectionActive=false` 분기 → `toast.dismiss('selection-mode')` (idempotent) |
| 날짜 전환 reset `useEffect` (L58-60) | `setSelectedGuestIds(new Set())` — reference 변경, 부담 미미 |
| timer cleanup `useEffect` (L63) | `deselectTimerRef.current=null` 유지 → noop |
| valid IDs filter `useEffect` (L66-75) | `prev.size===next.size` 분기 → reference 유지, no re-render |
| ESC handler `useEffect` (L78-84) | keydown 등록. ESC 시 `setSelectedGuestIds(new Set())` → re-render 1회 (사용자 명시 액션, 무시) |
| `onGripClick` | PC에서 호출 0 (#8 가드) |

→ **누적 부담**: 페이지 마운트 시 effect 등록 비용 + ESC 시 빈 setState 1회. 무시 가능.

---

## 4. 변경 대상 코드

### 4-1. 신규 `frontend/src/pages/RoomAssignment/hooks/useSelectionSystem.ts`

```tsx
import type { Dayjs } from 'dayjs';
import { useGuestSelection } from './useGuestSelection';
import { useHoverZone, type HoverZoneState } from './useHoverZone';
import { useIsDesktop } from '../../../hooks/use-desktop';
import type { Reservation } from '../types';

interface UseSelectionSystemProps {
  selectedDate: Dayjs;
  reservations: Reservation[];
  nextDayReservations: Reservation[];
}

const EMPTY_SET = new Set<number>();
const NONE_HOVER: HoverZoneState = { type: 'none' };
const NOOP_SET_STATE: React.Dispatch<React.SetStateAction<Set<number>>> = () => {};
const NOOP_SET_HOVER: (s: HoverZoneState) => void = () => {};
const NOOP_GRIP: (e: React.MouseEvent | React.PointerEvent, resId: number) => void = () => {};
const NOOP_VOID: () => void = () => {};

/**
 * useGuestSelection + useHoverZone 통합 래퍼.
 *
 * - **PC** (isDesktop=true): fixture 반환 → cascade 비활성을 값 자체로 강화.
 *   (#1~#10에서 PC selectionActive가 false로 유지되는 것과 결과 동일)
 * - **모바일**: 실제 훅 결과 반환 → 기존 클릭-선택 시스템 보존.
 *
 * 미래 모바일 자체 레이아웃 도입 시점에 `<RoomAssignmentDesktop>` 진입점에서
 * 이 훅 대신 EMPTY_SELECTION_PROPS 상수를 import하면 useGuestSelection / useHoverZone /
 * QuickMenuBar selection 액션 등을 일괄 제거 가능.
 */
export function useSelectionSystem(props: UseSelectionSystemProps) {
  const isDesktop = useIsDesktop();
  // hook order 보장: 항상 두 훅 호출
  const selection = useGuestSelection(props);
  const hover = useHoverZone();

  if (isDesktop) {
    return {
      selectedGuestIds: EMPTY_SET,
      setSelectedGuestIds: NOOP_SET_STATE,
      selectionActive: false,
      cancelDeselect: NOOP_VOID,
      onGripClick: NOOP_GRIP,
      hover: NONE_HOVER,
      setHover: NOOP_SET_HOVER,
      clearHover: NOOP_VOID,
    };
  }

  return {
    selectedGuestIds: selection.selectedGuestIds,
    setSelectedGuestIds: selection.setSelectedGuestIds,
    selectionActive: selection.selectionActive,
    cancelDeselect: selection.cancelDeselect,
    onGripClick: selection.onGripClick,
    hover: hover.hover,
    setHover: hover.setHover,
    clearHover: hover.clearHover,
  };
}
```

### 4-2. `RoomAssignment.tsx` import 변경

**Before**:
```tsx
import { useHoverZone } from './RoomAssignment/hooks/useHoverZone';
...
import { useGuestSelection } from './RoomAssignment/hooks/useGuestSelection';
```

**After**:
```tsx
import { useSelectionSystem } from './RoomAssignment/hooks/useSelectionSystem';
```

(useHoverZone, useGuestSelection import 제거)

### 4-3. 188줄 useHoverZone 호출 제거 + 192-195줄 교체

**Before**:
```tsx
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');
  const { hover, setHover, clearHover } = useHoverZone();

  // dnd-kit (PC 전용 드래그) — sensors + state. handleDragStart/End/Cancel은 useGuestMove 직후에 정의 (클로저 의존성).
  const [activeResId, setActiveResId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 4 },
    }),
  );

  const isMobile = useIsMobile();

  const {
    selectedGuestIds, setSelectedGuestIds, selectionActive,
    cancelDeselect, onGripClick,
  } = useGuestSelection({ selectedDate, reservations, nextDayReservations });
```

**After**:
```tsx
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');

  // dnd-kit (PC 전용 드래그) — sensors + state. handleDragStart/End/Cancel은 useGuestMove 직후에 정의 (클로저 의존성).
  const [activeResId, setActiveResId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 4 },
    }),
  );

  const isMobile = useIsMobile();

  // useGuestSelection + useHoverZone 통합 — PC는 fixture(noop) 반환, 모바일은 실제 훅
  const {
    selectedGuestIds, setSelectedGuestIds, selectionActive,
    cancelDeselect, onGripClick,
    hover, setHover, clearHover,
  } = useSelectionSystem({ selectedDate, reservations, nextDayReservations });
```

---

## 5. 동작 동등성

| 케이스 | #10 후 | 이 단계 이후 |
|---|---|---|
| 모바일 — 그립 클릭 → 선택 토글 | 정상 | 동일 ✅ (useSelectionSystem이 실제 selection 반환) |
| 모바일 — 호버 → 배경 표시 | 정상 | 동일 ✅ |
| 모바일 — toast 표시 | 정상 | 동일 ✅ |
| 모바일 — 날짜 전환 시 선택 해제 | 정상 | 동일 ✅ |
| 모바일 — ESC 키 | 선택 해제 | 동일 ✅ |
| 모바일 — InlineInput cancelDeselect | 정상 호출 | 동일 ✅ |
| PC — 모든 selection cascade | #8 가드로 selectionActive=false | fixture로 selectionActive=false ✅ |
| PC — toast | dismiss | dismiss ✅ |
| PC — onGripClick | #8 가드로 호출 안 됨 | NOOP ✅ |
| PC — hover/setHover/clearHover | useHoverZone 결과 (useGuestDropTarget enabled=false라 호출 안 됨) | NONE_HOVER fixture ✅ |
| PC — useGuestMove 내부 onDropZoneClick | `selectedGuestIds.size === 0` early return | 동일 ✅ |

---

## 6. 영향받지 않음을 확인할 코드 경로

- `useGuestSelection`, `useHoverZone` 원본 — 변경 없음
- `useGuestMove({selectedGuestIds, setSelectedGuestIds, ...})` — 시그니처 그대로. PC fixture 전달 시 자동으로 onDropZoneClick noop, 모바일은 정상
- `useContextMenu({selectedGuestIds})` — 시그니처 그대로. PC에서 size=0이라 [resId] 단일 ID 처리 (모바일도 사실상 동일)
- `sharedRowProps`, `sharedNextProps` — 변경 없음 (selection 값들이 fixture)
- `GuestRow`, `CompactGuestCell`, `RoomRow`, `GuestZone` — 변경 없음 (받는 prop은 동일 시그니처)
- `QuickMenuBar` — `selectionActive && isMobile` 조건. PC selectionActive=false → 모바일 액션 미표시 (#1~#10과 동일)
- `useGuestSelection.onGripClick`이 받는 deps에서 selectedGuestIds 사용 — 모바일에서만 활성, PC fixture에서는 noop이라 무관

---

## 7. 검증 체크리스트

- [ ] 모바일 viewport (<1024):
  - 그립 클릭 → 선택 토글 + toast 표시
  - 다른 zone 클릭 → 이동 동작
  - 호버 시 배경 변경
  - 날짜 전환 시 선택 자동 해제
  - ESC 키 → 선택 해제
  - InlineInput cancelDeselect → 편집 진입 시 deselect 타이머 취소
  - 롱프레스 → 컨텍스트 메뉴
  - QuickMenuBar 모바일 선택 액션 (Menu/Phone/Trash2) 정상
- [ ] PC viewport (≥1024):
  - 그립 클릭 → 아무 일 안 함 (#8 + fixture 합산)
  - 그립 드래그 → DragOverlay + 정상 드롭
  - InlineInput 단일클릭 편집 (#9)
  - 편집 중 우클릭 차단 (#9)
  - toast / cursor-pointer / hover 미표시
  - 우클릭 → 컨텍스트 메뉴 (편집 중 아닐 때)
- [ ] TypeScript 빌드 오류 없음
- [ ] 콘솔 경고 없음 (특히 hook order)
