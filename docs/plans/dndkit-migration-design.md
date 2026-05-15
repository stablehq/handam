# dnd-kit 드래그 마이그레이션 설계안

> 작성일: 2026-05-15
> 상태: 검토 대기
> 관련 마이그레이션 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 배경 — 왜 dnd-kit 드래그인가

### 현재 이동 방식 (클릭-선택 시스템)

```
①  그립 또는 행 클릭 → 선택 모드 진입 (상단 toast 표시)
②  목적 영역으로 마우스 이동 → 호버 시 배경색 변경
③  목적 영역 클릭 → 이동 실행
```

### 문제점

| 문제 | 영향 |
|------|------|
| 이동이 선택 → 클릭 2단계로 분리 | UX 직관성 저하, 모든 이동에 toast 등장 |
| 행 전체가 선택 트리거 | 편집하려다 실수로 선택 모드 진입 잦음 |
| 더블클릭으로만 인라인 편집 진입 | 편집 진입 기준이 불명확, 드래그 인지 편집 인지 모호 |
| 그립과 행 onClick 이 동일 핸들러 공유 | 단일클릭 편집 전환 시 충돌 발생 |
| 우클릭 시 InlineInput 배경 활성화 | 편집 의도 없는 포커스로 UI 노이즈 |

---

## 2. 현재 구조 사전점검 (코드 라인 기준)

### 2-1. 선택 시스템 (`useGuestSelection.ts`)

| 심볼 | 역할 | 위치 |
|------|------|------|
| `selectedGuestIds` | Set<number> — 현재 선택된 예약 ID 집합 | 전체 |
| `selectionActive` | `size > 0` — 선택 모드 활성 여부 | 전체 |
| `onGripClick` | 그립/행 클릭 시 선택/해제, 250ms 지연 해제 | L86-111 |
| `deselectTimerRef` | 250ms 지연 해제 타이머 | L26 |
| `cancelDeselect` | 타이머 취소 (InlineInput.onActivate 에서 호출) | L27-32 |
| ESC 핸들러 | 전역 keydown → 선택 해제 | L77-84 |
| toast | `selectionActive` 시 Infinity toast 표시 | L35-55 |

**호출 경로**:
- `GuestRow.tsx:157-162` 행 `onClick` → 비인터랙티브 영역 → `onGripClick(e, res.id)`
- `GuestRow.tsx:165-179` 그립 div → 별도 onClick 없음, 행 onClick 버블링으로 처리됨

### 2-2. 호버/드롭 시스템

| 파일 | 역할 |
|------|------|
| `useHoverZone.ts` | hover 상태 discriminated union (none/room/next-room/pool/party/next-pool/next-party) |
| `useGuestDropTarget.ts` | `data-drop-zone` attr + `onMouseEnter`/`onMouseLeave` → setHover/clearHover |
| `RoomAssignment.tsx:561-602` | `onDropZoneClick` — event.target chain에서 `data-drop-zone` 파싱 → 이동 핸들러 라우팅 |

**GuestZone.tsx:89-93** — `enabled: accept && !!zoneId && selectionActive` 로 `selectionActive` 가 false 이면 드롭존 전체 비활성:

```tsx
const main = useGuestDropTarget({
  zoneId: zoneId ?? '', hover, setHover, clearHover,
  enabled: accept && !!zoneId && selectionActive,
});
```

**RoomRow.tsx** — 동일 패턴, `enabled: selectionActive && isActive`

### 2-3. 이동 핸들러 (`useGuestMove.ts`)

| 함수 | 역할 | 위치 |
|------|------|------|
| `handleDropOnRoom` | 객실 배정 + 연박 처리 + optimistic + undo | L440-545 |
| `handleDropOnPool` | 미배정 (unassign) | L549-639 |
| `handleDropOnParty` | 파티만 | L643-733 |
| `onDropZoneClick` | data-drop-zone 파싱 → 위 3개 함수로 라우팅 | L735-808 |

**이 3개 함수(handleDropOnRoom/Pool/Party)는 본 마이그레이션에서 변경하지 않는다.**
dnd-kit은 routing 방식만 대체하고 API 호출은 그대로 유지한다.

### 2-4. 인라인 편집 (`InlineInput.tsx`)

| 동작 | 코드 |
|------|------|
| 편집 진입 (PC) | `onDoubleClick={activate}` (L113) |
| 편집 진입 (키보드) | `tabIndex={0}`, `onFocus` + `:focus-visible` 매칭 → activate (L121-123) |
| 우클릭 배경 버그 | span `focus:bg-[#F2F4F6]` — 우클릭 시 focus 이벤트 발생 → 배경 활성화됨 (L131) |
| 편집 저장 | `onBlur → commit()`, `Enter → commit() + blur()` | L69-74 |

**버그**: 우클릭 시 `:focus`는 매칭되지만 `:focus-visible`은 매칭 안 됨. 배경만 켜지고 editing 모드는 진입 안 함. `focus:` → `focus-visible:` 로 고치면 해결.

---

## 3. 추가 조건 5개 (확정)

| # | 조건 | 영향 범위 |
|---|------|-----------|
| 1 | **그립 전용 드래그** — `useDraggable.listeners` 를 그립 div에만 연결. 행 나머지 부분 클릭은 드래그 미발동 | `GuestRow.tsx` |
| 2 | **PC 단일클릭 편집** — `InlineInput.onDoubleClick` → `onClick` 전환 (PC 한정). `singleClick` prop으로 분기 | `InlineInput.tsx`, `GuestRow.tsx` |
| 3 | **편집→드래그 자동저장** — `onDragStart` 에서 `document.activeElement.blur()` → `commit()` 자동 호출 | `RoomAssignment.tsx` |
| 4 | **모바일 변경 없음** — `useIsDesktop()` (1024px breakpoint) 으로 전체 gate. 모바일은 클릭-선택 시스템 유지 | 전체 |
| 5 | **우클릭 배경 방어** — `InlineInput` span의 `focus:` → `focus-visible:` | `InlineInput.tsx` |

---

## 4. 제안 구조

### 4-1. 이동 시스템 비교

```
현재 (PC + 모바일 공통):
  그립/행 클릭 ──▶ useGuestSelection(selectedGuestIds) ──▶ toast 표시
  마우스 hover ──▶ useHoverZone + useGuestDropTarget
  영역 클릭   ──▶ onDropZoneClick → handleDropOnRoom/Pool/Party

제안 (PC):
  그립 drag   ──▶ DndContext onDragEnd → handleDropOnRoom/Pool/Party (직결)

제안 (모바일): 현재와 동일 (변경 없음)
```

### 4-2. DndContext 구조

```tsx
// RoomAssignment.tsx 최상위 JSX 래핑
const sensors = useSensors(
  useSensor(PointerSensor, {
    activationConstraint: { distance: 8 },  // 8px 이동 전까지 클릭으로 인식
  })
);

<DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
  {/* 전체 페이지 콘텐츠 */}
  <DragOverlay>
    {activeResId && <GuestDragCard resId={activeResId} reservations={reservations} />}
  </DragOverlay>
</DndContext>
```

**activationConstraint: { distance: 8 }** — 8px 이상 이동 전에는 dragevent 미발동.
단일클릭(8px 미만)은 dnd-kit이 무시 → InlineInput onClick으로 편집 진입 정상 동작.

### 4-3. useDraggable (GuestRow 그립 div)

```tsx
// GuestRow.tsx
const isDesktop = useIsDesktop();
const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
  id: res.id,
  disabled: !isDesktop || isCancelled,
});

// 그립 div에만 연결 — 행 전체가 아님 (조건 #1)
<div ref={setNodeRef} {...attributes} {...listeners} className={`... ${isDragging ? 'opacity-50' : ''}`}>
  <Circle size={18} ... />
</div>
```

### 4-4. useDroppable (각 드롭 존)

```tsx
// RoomRow.tsx
const { setNodeRef, isOver } = useDroppable({
  id: `room-${room_id}`,
  disabled: !isDesktop || !isActive,
});

// GuestZone.tsx
const { setNodeRef: mainRef, isOver: mainIsOver } = useDroppable({
  id: zoneId ?? '',
  disabled: !isDesktop || !accept || !zoneId,
});
const { setNodeRef: nextRef, isOver: nextIsOver } = useDroppable({
  id: nextZoneId ?? '',
  disabled: !isDesktop || !accept || !nextZoneId || !nextDayExpanded,
});
```

### 4-5. onDragEnd 라우팅

```tsx
const handleDragEnd = ({ active, over }: DragEndEvent) => {
  setActiveResId(null);
  if (!over) return;
  const resId = Number(active.id);
  const zoneId = String(over.id);

  if (zoneId.startsWith('room-')) {
    const roomId = Number(zoneId.replace('room-', ''));
    const entry = activeRoomEntries.find(e => e.room_id === roomId);
    if (entry) handleDropOnRoom(resId, roomId, entry.room_number);
  } else if (zoneId === 'pool' || zoneId === 'next-pool') {
    handleDropOnPool(resId);
  } else if (zoneId === 'party' || zoneId === 'next-party') {
    handleDropOnParty(resId);
  }
};
```

### 4-6. InlineInput 단일클릭 분기 (조건 #2, PC only)

```tsx
// InlineInput.tsx — singleClick prop 신규
interface InlineInputProps {
  ...
  singleClick?: boolean;  // PC에서 단일클릭 편집 진입 (더블클릭 미사용)
}

// span 렌더
<span
  onClick={singleClick ? activate : undefined}          // PC: 단일클릭
  onDoubleClick={!singleClick ? activate : undefined}   // 모바일: 더블클릭
  ...
```

```tsx
// GuestRow.tsx — isDesktop 전달
<InlineInput ... singleClick={isDesktop} />
```

### 4-7. PC에서 선택 시스템 비활성화 방법

`selectionActive`는 `selectedGuestIds.size > 0` 으로 결정됨.
`selectedGuestIds`는 `onGripClick`을 통해서만 Set에 추가됨.

**핵심**: `GuestRow.tsx`의 행 `onClick`에서 PC일 때 `onGripClick` 호출을 막으면,
`selectionActive`는 항상 false → 하위 시스템(`useGuestDropTarget`, toast 등) 전체가 자동으로 비활성.

```tsx
// GuestRow.tsx:157 수정
onClick={(e) => {
  if (isCancelled || isDesktop) return;    // ← isDesktop 추가
  if (longPressFiredRef.current) { ... }
  if (showGrip && !e.target.closest(...)) {
    if (selectionActive && !isSelected) return;
    onGripClick(e, res.id);
  }
}}
```

이것만으로 cascade 비활성:
- `selectedGuestIds` 영원히 빈 Set → `selectionActive = false`
- `useGuestDropTarget enabled: ... && selectionActive` → false
- `GuestZone` / `RoomRow` 드롭존 cursor-pointer, onClick 비활성
- toast 비표시 (useEffect selectionActive false → toast.dismiss)

---

## 5. 현재 vs 제안 비교

| 항목 | 현재 (As-Is) | 제안 (To-Be, PC) | 모바일 |
|------|-------------|-----------------|--------|
| 이동 방식 | 선택 → 호버 → 클릭 (2단계) | 드래그 → 드롭 (1단계) | 변경 없음 |
| 드래그 트리거 영역 | 행 전체 (그립 포함) | 그립 div 만 | 변경 없음 |
| 인라인 편집 진입 | 더블클릭 | 단일클릭 | 더블클릭 유지 |
| 선택 시스템 | 항상 활성 | 비활성 (isDesktop 가드) | 유지 |
| toast 표시 | 선택 시 항상 | 표시 안 함 | 유지 |
| 호버 피드백 | useHoverZone/useGuestDropTarget | dnd-kit isOver | 유지 |
| 드롭 이동 핸들러 | onDropZoneClick → handleDropOnRoom/Pool/Party | onDragEnd → handleDropOnRoom/Pool/Party | 유지 |
| 우클릭 배경 | focus: (우클릭 시 활성화 버그) | focus-visible: (방어됨) | 동일 수정 |

---

## 6. 변경 대상 파일 전체 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/hooks/use-desktop.ts` (신규) | useIsDesktop 훅 |
| `src/pages/RoomAssignment.tsx` | DndContext 래핑, sensors, onDragStart, onDragEnd, DragOverlay, isDesktop 전달 |
| `src/pages/RoomAssignment/components/shared/GuestRow.tsx` | useDraggable 연결, isDesktop 가드, 행 onClick 수정, singleClick 전달 |
| `src/pages/RoomAssignment/components/InlineInput.tsx` | focus-visible 수정, singleClick prop 추가 |
| `src/pages/RoomAssignment/components/RoomRow.tsx` | useDroppable 연결 |
| `src/pages/RoomAssignment/components/zones/GuestZone.tsx` | useDroppable 연결 (main + next) |

**변경하지 않는 파일**:
- `useGuestMove.ts` — handleDropOnRoom/Pool/Party API 로직 전부 유지
- `useGuestSelection.ts` — 모바일에서 그대로 사용
- `useGuestDropTarget.ts` — 모바일에서 그대로 사용
- `useHoverZone.ts` — 모바일에서 그대로 사용
- `useReservationsData.ts` — 변경 없음
- `zones/UnassignedZone.tsx`, `PartyZone.tsx`, `UnstableZone.tsx`, `CancelledZone.tsx` — GuestZone props 변경 없음
- Backend 전체 — 변경 없음

---

## 7. 미결 검토 항목

- [ ] **`DragOverlay` 내용물** — 게스트 이름 텍스트만? 컴팩트 카드? 현재 GuestRow 복제?
  - 권장: 이름 + 파티인원만 표시하는 경량 카드 (30px 높이)
- [ ] **다음날 컬럼 드롭 zoneId 네이밍** — `next-room-5`, `next-pool`, `next-party`. onDragEnd 라우팅 분기 확인 필요
- [ ] **activationConstraint 값** — `distance: 8`이 터치패드 환경에서도 적절한지
  - 터치패드: 스크롤 제스처와 혼동 가능성 → `delay: 200` 또는 `distance: 5` 검토
- [ ] **DndContext 위치** — RoomAssignment.tsx 최상위 JSX vs. 별도 wrapper 컴포넌트
  - 권장: 최상위 JSX 직접 래핑 (중간 컴포넌트 불필요)
- [ ] **키보드 드래그 (Accessibility)** — `activationConstraint: distance` 사용 시 Space/Enter 키보드 드래그 비활성됨. 현재 범위 외로 결정 필요
- [ ] **연박 예약 드래그** — `handleDropOnRoom`에서 `isMultiNight` 감지 후 모달 표시. dnd-kit onDragEnd는 비동기 모달을 기다리지 않음. 현재 `setMultiNightConfirm` 패턴 그대로 동작하는지 확인 필요
