# 단계 #3: DndContext + DragOverlay 골격 (noop)

> 작성일: 2026-05-16
> 단계: 3 / 11
> 섹션: B. dnd-kit 골격 설치
> 동작 변화: ⚪ 없음 — useDraggable 미연결 → drag event 미발동
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`RoomAssignment.tsx` 최상위에 `DndContext` + `DragOverlay` + `PointerSensor`(distance:4) 골격을 추가.
이번 단계는 골격만 — `useDraggable` 연결이 없으므로 drag event 발생 안 함. handleDragStart/End/Cancel은 noop 자리잡기.

---

## 2. 변경 대상 코드

### 2-1. import 추가 (`frontend/src/pages/RoomAssignment.tsx` 상단)

**Before**: 30번 라인 부근 (lucide-react import 직후)
```tsx
} from 'lucide-react';
import { useIsMobile } from '../hooks/use-mobile';
```

**After**:
```tsx
} from 'lucide-react';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core';
import { useIsMobile } from '../hooks/use-mobile';
```

### 2-2. activeResId state + sensors + noop 핸들러 추가 (RoomAssignment 함수 본문)

`nextDayExpanded` state 선언 부근(181~187줄) 다음에 추가:

```tsx
// dnd-kit (PC 전용 드래그) — 단계 #3 골격, #6/#7에서 구현 채움
const [activeResId, setActiveResId] = useState<number | null>(null);
const sensors = useSensors(
  useSensor(PointerSensor, {
    activationConstraint: { distance: 4 },
  }),
);
const handleDragStart = (_event: DragStartEvent) => {
  // #7: setActiveResId(active.id) + document.activeElement.blur()
};
const handleDragEnd = (_event: DragEndEvent) => {
  // #6: over.id 파싱 → handleDropOnRoom/Pool/Party 라우팅 + setSelectedGuestIds(new Set())
};
const handleDragCancel = () => {
  // #7: setActiveResId(null)
};
```

### 2-3. return JSX 최상위에 DndContext 래핑 (783줄~)

**Before**:
```tsx
return (
  <div className={`space-y-4 pb-14 min-w-0 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>
    <PageHeader />
    ...
  </div>
);
```

**After**:
```tsx
return (
  <DndContext
    sensors={sensors}
    onDragStart={handleDragStart}
    onDragEnd={handleDragEnd}
    onDragCancel={handleDragCancel}
  >
    <div className={`space-y-4 pb-14 min-w-0 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>
      <PageHeader />
      ...
    </div>
    <DragOverlay>
      {activeResId !== null ? null : null}
    </DragOverlay>
  </DndContext>
);
```

**DragOverlay 내용물**: 단계 #10에서 `GuestDragCard` 컴포넌트로 채움. 본 단계에서는 `null`.

---

## 3. 동작 동등성

| 케이스 | 기존 결과 | 이 단계 이후 |
|---|---|---|
| PC/모바일 — 게스트 클릭-선택 시스템 | 정상 동작 | 정상 동작 ✅ (useDraggable 연결 없음) |
| PC/모바일 — InlineInput 편집 | 정상 동작 | 정상 동작 ✅ |
| PC/모바일 — 모달 / QuickMenuBar / ContextMenu | 정상 동작 | 정상 동작 ✅ |
| PC — 그립 클릭 | 선택 토스트 | 선택 토스트 ✅ (#8 전까지 유지) |
| PC — drag event 발화 | 없음 (HTML5 미사용) | 없음 ✅ (useDraggable 미연결) |
| DragOverlay 렌더 | 미존재 | `activeResId=null` → null 렌더 → 시각 변화 0 |

---

## 4. 영향받지 않음을 확인할 코드 경로

라인단위 검증:
- **`useGuestSelection`/`useHoverZone`/`useGuestMove`/`useGuestDropTarget`** — 호출/시그니처 그대로. 영향 0.
- **모달(createPortal로 document.body)** — `MultiNightConfirmModal`, `ExtendStayConflictModal`, `DateChangeModal`, `ReservationFormModal`, `StayGroupChainModal`, `TableSettingsModal`, `AutoAssignConfirmModal`, `SendConfirmModal`, `ConfirmDialog` — 모두 RoomAssignment.tsx 의 return 안에 렌더되지만 portal로 body 직속 → `DndContext` 외부에 위치 → 영향 0
- **QuickMenuBar** — createPortal → 외부
- **GuestContextMenu** — RoomAssignment.tsx 내부 (1198줄) → DndContext 내부지만 drag 영역 아님. 영향 0
- **`window.__diagAction`** — useGuestMove가 자체 설정, 이번 단계와 무관
- **`useColumnResize.startResize`/`tableContainerRef`** — mousedown 기반 컬럼 리사이즈. 본 단계는 PointerSensor를 RoomAssignment 영역에 묶지만 useDraggable이 없어 drag event 미발동 → 충돌 0

---

## 5. 검증 체크리스트

- [ ] `git diff` — RoomAssignment.tsx 한 파일만 표시
- [ ] TypeScript 빌드 오류 없음
- [ ] 브라우저:
  - PC 기존 클릭-선택 시스템 정상
  - 모바일 기존 클릭-선택/롱프레스 정상
  - 모든 모달 정상
  - 드래그 시도 시 아무 일도 안 일어남 (useDraggable 미연결)
  - 콘솔 에러/경고 없음
