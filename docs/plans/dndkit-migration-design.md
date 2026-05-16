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

## 3. 추가 조건 7개 (확정)

| # | 조건 | 영향 범위 |
|---|------|-----------|
| 1 | **그립 전용 드래그** — `useDraggable.listeners` 를 그립 div에만 연결. 행 나머지 부분 클릭은 드래그 미발동 | `GuestRow.tsx`, `CompactGuestCell.tsx` |
| 2 | **PC 단일클릭 편집** — `InlineInput.onDoubleClick` → `onClick` 전환 (PC 한정). `singleClick` prop으로 분기 | `InlineInput.tsx`, `GuestRow.tsx` |
| 3 | **편집→드래그 자동저장** — `onDragStart` 에서 `document.activeElement.blur()` → `commit()` 자동 호출 | `RoomAssignment.tsx` |
| 4 | **모바일 변경 없음** — `useIsDesktop()` (1024px breakpoint) 으로 전체 gate. 모바일은 클릭-선택 시스템 유지 | 전체 |
| 5 | **우클릭 배경 방어** — `InlineInput` span의 `focus:` → `focus-visible:` | `InlineInput.tsx` |
| 6 | **그립 영역 분리** — 그립 div(`Circle` span)는 PC에서 드래그 트리거 전용. `onClick` 핸들러 미설치. `activationConstraint: { distance: 4 }` 로 그립 단순 클릭만으로는 drag start/end 사이클 미발동 + DragOverlay 깜빡임 차단 | `GuestRow.tsx`, `CompactGuestCell.tsx`, `RoomAssignment.tsx` |
| 7 | **편집 중 우클릭 컨텍스트 메뉴 차단** — `useContextMenu.canOpen` 조건에 InlineInput 편집 상태 추가. #9 단일클릭 편집 활성화로 인한 편집 진입 빈도 증가 → 편집 중 우클릭 시 컨텍스트 메뉴가 열리는 기존 버그를 사전 차단 | `useContextMenu.ts`, `InlineInput.tsx`, `RoomAssignment.tsx` |

**추가 구조 조건 (Phase F)**:

| # | 조건 | 영향 범위 |
|---|------|-----------|
| 8 | **선택 시스템 진입점 일원화** — `useGuestSelection` + `useHoverZone` 호출을 `useSelectionSystem` 래퍼로 통합. PC에서는 `EMPTY_SELECTION_PROPS` fixture 반환 → 미래 모바일 자체 레이아웃 도입 시 import 한 줄로 선택 시스템 전체 제거 가능 | `useSelectionSystem.ts` (신규), `RoomAssignment.tsx` |

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
    activationConstraint: { distance: 4 },  // 4px 이동 전까지 클릭으로 인식 (그립/입력 영역 분리되어 더 작은 임계 가능)
  })
);

<DndContext
  sensors={sensors}
  onDragStart={handleDragStart}
  onDragEnd={handleDragEnd}
  onDragCancel={handleDragCancel}  // ESC / 드롭 영역 밖에서 떼기 → activeResId 정리
>
  {/* 전체 페이지 콘텐츠 */}
  <DragOverlay>
    {activeResId && <GuestDragCard resId={activeResId} reservations={reservations} />}
  </DragOverlay>
</DndContext>
```

**activationConstraint: { distance: 4 }** — 4px 이상 이동 전에는 drag event 미발동.
그립 단순 클릭만으로는 drag start/end 사이클 미발동 → DragOverlay 깜빡임 차단.
그립 div와 입력 영역(이름~메모)이 완전히 분리되어 있으므로(조건 #6) 보수적으로 큰 distance를 둘 필요 없음.

**`onDragCancel` 필수** — `setActiveResId(null)`. ESC/취소 시 DragOverlay 잔존 방지.

### 4-3. useDraggable (GuestRow + CompactGuestCell 그립 div)

**⚠️ 구조 차이 주의**: `GuestRow`는 행 전체 `onClick`에서 버블링으로 `onGripClick`을 호출하지만, `CompactGuestCell`(다음날 컬럼)은 grip div에 직접 `onClick={(e) => onGripClick(e, guest.id)}`가 바인딩되어 있음. 두 컴포넌트 모두 변경이 필요하지만 수정 위치가 다르다.

- `GuestRow`: 행 `onClick`의 조건 블록 앞에 `if (isDesktop) return` 추가
- `CompactGuestCell`: grip div의 `onClick` 핸들러 앞에 `if (isDesktop) return` 추가

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

| 파일 | 변경 내용 | 단계 |
|------|-----------|------|
| `src/hooks/use-desktop.ts` (신규) | useIsDesktop 훅 | #1 |
| `src/pages/RoomAssignment/components/InlineInput.tsx` | focus-visible 수정, singleClick prop 추가 | #2, #9 |
| `src/pages/RoomAssignment.tsx` | DndContext 래핑, sensors(distance:4), onDragStart+blur, onDragEnd, **onDragCancel**, DragOverlay, setSelectedGuestIds 안전망, useContextMenu.canOpen에 편집상태 추가 | #3, #6, #7, #9 |
| `src/pages/RoomAssignment/components/shared/GuestRow.tsx` | useDraggable 연결, 행 onClick isDesktop 가드, singleClick 전달 | #4, #8, #9 |
| `src/pages/RoomAssignment/components/shared/CompactGuestCell.tsx` | useDraggable 연결 (grip div 직접), grip onClick isDesktop 가드 (GuestRow와 위치 다름) | #4, #8 |
| `src/pages/RoomAssignment/components/RoomRow.tsx` | useDroppable 연결 | #5 |
| `src/pages/RoomAssignment/components/zones/GuestZone.tsx` | useDroppable 연결 (main + next) | #5 |
| `src/pages/RoomAssignment/components/shared/GuestDragCard.tsx` (신규) | DragOverlay 내용물 — 컴팩트 카드 (이름 + 파티/성별 인원) | #10 |
| `src/pages/RoomAssignment/hooks/useSelectionSystem.ts` (신규) | useGuestSelection + useHoverZone 통합 래퍼. PC에서 EMPTY_SELECTION_PROPS fixture 반환 | #11 |
| `src/pages/RoomAssignment/hooks/useContextMenu.ts` | canOpen 조건에 InlineInput 편집 상태 포함 | #9 |

**변경하지 않는 파일**:
- `useGuestMove.ts` — handleDropOnRoom/Pool/Party API 로직 전부 유지 (단, onDropZoneClick은 PC에서 dead path)
- `useGuestSelection.ts` — 모바일에서 그대로 사용 (PC는 useSelectionSystem fixture로 분리)
- `useGuestDropTarget.ts` — 모바일에서 그대로 사용 (PC는 enabled=false 자동 비활성)
- `useHoverZone.ts` — 모바일에서 그대로 사용
- `useReservationsData.ts` — 변경 없음
- `zones/UnassignedZone.tsx`, `PartyZone.tsx`, `UnstableZone.tsx`, `CancelledZone.tsx` — GuestZone props 변경 없음
- Backend 전체 — 변경 없음

---

## 7. 결정 사항 (2026-05-16 사용자 합의)

- **`DragOverlay` 내용물** — 컴팩트 카드. 이름 + 파티/성별 인원만 표시하는 30~40px 경량 카드. `GuestDragCard` 신규 컴포넌트 (#10).
- **다음날 컬럼 드롭 zoneId 네이밍** — `next-room-N` / `next-pool` / `next-party`. onDragEnd 분기에서 `startsWith` 매칭으로 처리.
- **activationConstraint 값** — `distance: 4`. 그립과 입력 영역이 완전히 분리되어 보수적으로 큰 distance가 불필요. 그립 단순 클릭만으로 drag start/end 사이클이 발동되어 DragOverlay 깜빡임이 생기는 것을 차단.
- **DndContext 위치** — RoomAssignment.tsx 최상위 JSX 직접 래핑. 중간 wrapper 컴포넌트 불필요.
- **`onDragCancel`** — `setActiveResId(null)` 호출. ESC, 드롭 영역 밖에서 떼기 등에서 DragOverlay 잔존 방지. #7에 포함.
- **키보드 드래그 (Accessibility)** — 본 마이그레이션 범위 외. distance 활성 제약 사용 시 Space/Enter 키보드 드래그 비활성. 후속 별도 트랙.
- **연박 예약 드래그** — `setMultiNightConfirm` 패턴 그대로. `onDragEnd`는 동기 콜백이고 `setState`로 모달 표시. dnd-kit active 상태는 onDragEnd 직후 자동 클리어 → 다음 드래그 정상. #6 사전조사에서 실제 동작 검증.
- **컨텍스트 메뉴 + 편집 모드 동시 활성 (기존 버그)** — 본 마이그레이션 범위 포함. #9에서 `useContextMenu.canOpen` 조건에 InlineInput 편집 상태 추가. 단일클릭 편집 활성화로 편집 진입 빈도 증가 → 사전 차단.
- **드래그 완료 후 toast 잔존** — #6에서 `setSelectedGuestIds(new Set())` 안전망 포함. #8 이후 PC에서 selectionActive 항상 false라 근본 해결.

## 8. 별도 트랙으로 분리된 항목

다음 항목은 본 마이그레이션 범위 외로 결정됨:

- **DELETE.md B-4 (멀티선택 dead code, ~30곳)** — 단계 #11 머지 후 PC에서 영구 dead 확정 시점에 별도 PR로 일괄 정리.
- **DELETE.md C (노재원 undo 회귀 5케이스)** — 본 마이그레이션과 무관한 별개 이슈. 5케이스 재현 + diag 로그 + API 응답 확인 후 별도 트랙.
- **room-assignment-cleanup-plan.md (백엔드 정리 PR1~PR4)** — dnd-kit과 독립. 수시 진행 가능 (PR1 sync_denormalized_field 제거, PR2 reconcile_dates 이름 공개화는 테스트 ImportError 즉시 해결 권장).
- **키보드 드래그 접근성** — Space/Enter 키보드 드래그. distance 제약과 상충하므로 별도 설계 필요.
