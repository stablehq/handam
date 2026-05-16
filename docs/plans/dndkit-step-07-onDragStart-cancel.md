# 단계 #7: onDragStart + blur + onDragCancel + DragOverlay 활성화

> 작성일: 2026-05-16
> 단계: 7 / 11
> 섹션: C. 드래그 → 드롭 실제 연결
> 동작 변화: 🔵 의도된 변화 — 드래그 시 DragOverlay 표시 + 편집 중 InlineInput 자동 저장
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

- `handleDragStart`: `setActiveResId(resId)` + `document.activeElement.blur()` (편집 중 InlineInput 자동 commit).
- `handleDragCancel`: `setActiveResId(null)`.
- `handleDragEnd` 시작에 `setActiveResId(null)` 추가 (drag 종료 시 DragOverlay 즉시 사라짐).
- `DragOverlay` 임시 placeholder 활성화 (단계 #10에서 `GuestDragCard`로 교체).

---

## 2. 모달 z-index vs DragOverlay portal 검증

- `DragOverlay`: dnd-kit 자체 React portal로 document.body 직속 렌더. 기본 z-index 매우 높음(~999).
- 앱 모달 (`Modal` 컴포넌트 + `MultiNightConfirmModal` 등): createPortal로 body 직속.
- **drag 중에 모달이 동시 표시되는 경로**:
  - drop → `handleDropOnRoom` → `is_long_stay`면 `setMultiNightConfirm({open:true})` 호출 → 다음 렌더에 모달 표시
  - 같은 렌더에 `handleDragEnd` 시작의 `setActiveResId(null)` → DragOverlay 사라짐
  - **타이밍**: 모달이 보이는 시점에 DragOverlay는 이미 unmount → 충돌 없음
- **확인 절차** (사전조사 검증): 빌드 후 PC에서 연박 예약 드래그 → 모달 표시 → DragOverlay 미렌더 확인.

---

## 3. 변경 대상 코드

### 3-1. `RoomAssignment.tsx` handleDragStart 본문

**Before**:
```tsx
  const handleDragStart = (_event: DragStartEvent) => {
    // #7: setActiveResId(active.id) + document.activeElement.blur()
  };
```

**After**:
```tsx
  const handleDragStart = (event: DragStartEvent) => {
    const activeStr = String(event.active.id);
    let resId: number;
    if (activeStr.startsWith('guest-next-')) {
      resId = Number(activeStr.replace('guest-next-', ''));
    } else if (activeStr.startsWith('guest-')) {
      resId = Number(activeStr.replace('guest-', ''));
    } else {
      return;
    }
    if (!Number.isFinite(resId)) return;
    setActiveResId(resId);
    // 편집 중인 InlineInput 자동 저장 — onBlur → commit() → mutation
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };
```

### 3-2. handleDragCancel 본문

**Before**:
```tsx
  const handleDragCancel = () => {
    // #7: setActiveResId(null)
  };
```

**After**:
```tsx
  const handleDragCancel = () => {
    setActiveResId(null);
  };
```

### 3-3. handleDragEnd 시작에 `setActiveResId(null)` 추가

**Before** (handleDragEnd 시작 부근):
```tsx
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    // PC #8 전 중간 상태: 클릭 선택 후 드래그 시 toast 잔존 방지 안전망
    setSelectedGuestIds(new Set());
    if (!over) return;
```

**After**:
```tsx
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    // drag 종료 시 DragOverlay 즉시 unmount
    setActiveResId(null);
    // PC #8 전 중간 상태: 클릭 선택 후 드래그 시 toast 잔존 방지 안전망
    setSelectedGuestIds(new Set());
    if (!over) return;
```

### 3-4. DragOverlay placeholder 활성화

**Before** (return 의 마지막 부근):
```tsx
      <DragOverlay>
        {activeResId !== null ? null : null}
      </DragOverlay>
```

**After**:
```tsx
      <DragOverlay>
        {activeResId !== null ? (
          <div className="rounded-xl bg-white dark:bg-[#1E1E24] shadow-lg border border-[#E5E8EB] dark:border-gray-700 px-3 py-2 text-body font-medium text-[#191F28] dark:text-white whitespace-nowrap">
            {reservations.find((r) => r.id === activeResId)?.customer_name
              ?? nextDayReservations.find((r) => r.id === activeResId)?.customer_name
              ?? '게스트'}
          </div>
        ) : null}
      </DragOverlay>
```

> 단계 #10에서 `GuestDragCard` 컴포넌트로 교체 (이름 + 파티/성별 인원 표시 컴팩트 카드).

---

## 4. 동작 동등성 / 의도된 변화

| 케이스 | #6 후 | 이 단계 이후 |
|---|---|---|
| PC — 드래그 시작 | 그립 opacity-40만 변화 | DragOverlay 표시 + 게스트 이름 표시 + opacity-40 ✅ |
| PC — 편집 중 드래그 시작 | (편집 중 그립 드래그는 어색했음) | `document.activeElement.blur()` → onBlur commit → 편집 내용 저장 + drag 시작 ✅ |
| PC — drop 영역 밖 release | setSelectedGuestIds만, activeResId 잔존 (DragOverlay 잔존) | `setActiveResId(null)` → DragOverlay 즉시 사라짐 ✅ |
| PC — ESC | (drag 시작 후 ESC 시 cancel) | `handleDragCancel` → `setActiveResId(null)` ✅ |
| PC — 정상 드롭 | DragOverlay 잔존 | handleDragEnd 시작에서 `setActiveResId(null)` → 즉시 사라짐 ✅ |
| 모바일 — drag 미발동 | useDraggable disabled | onDragStart/Cancel 미발화 ✅ |
| 연박 예약 드래그 → 모달 | (#6 기준 setMultiNightConfirm은 trigger되나 DragOverlay 잔존 가능성) | `setActiveResId(null)` 우선 → DragOverlay 사라짐 → 모달 표시 ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `useGuestMove`의 mutation들 — 변경 없음
- 모달 트리거 (`setMultiNightConfirm` 등) — 변경 없음
- 컨텍스트 메뉴 — drag 중 발화 없음, 변경 없음
- InlineInput.commit (L69-74) — `document.activeElement.blur()`가 발화하는 `onBlur` → `commit()` → 기존 동작 그대로 (저장 + 모드 종료)
- editing state — InlineInput 내부 관리, 외부 영향 없음
- 모바일 onTouchStart/Move/End — useDraggable disabled → 영향 없음
- `useGuestSelection.cancelDeselect` — 영향 없음 (drag와 별개)

---

## 6. 검증 체크리스트

- [ ] PC:
  - 드래그 시작 → DragOverlay placeholder가 마우스 따라 표시 (이름)
  - InlineInput 편집 중 → 그립 드래그 → 편집 내용 자동 저장 (`onBlur`/`commit`) + 드래그 진행
  - drop 영역 밖 release → DragOverlay 즉시 사라짐
  - 정상 드롭 → DragOverlay 즉시 사라짐 + handleDropOnRoom/Pool/Party 동작
  - ESC 키 (drag 중) → DragOverlay 사라짐 (`handleDragCancel`)
  - 연박 예약 드래그 → MultiNightConfirmModal 표시 + DragOverlay 사라짐
  - cross-day 모달 → 표시 정상 + DragOverlay 사라짐
- [ ] 모바일:
  - drag 미발동, 기존 클릭-선택 정상
- [ ] TypeScript 빌드 오류 없음
- [ ] 콘솔 경고 없음
