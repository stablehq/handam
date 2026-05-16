# 단계 #8: PC에서 행 onClick → onGripClick 호출 차단

> 작성일: 2026-05-16
> 단계: 8 / 11
> 섹션: D. 클릭-선택 시스템 PC 비활성화 + 편집 단일클릭
> 동작 변화: 🔵 의도된 변화 — PC에서 클릭-선택 시스템 비활성 (모바일은 유지)
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`GuestRow.tsx` 행 `onClick` + `CompactGuestCell.tsx` grip div `onClick`에 `if (isDesktop) return` 가드 추가.
PC에서 `onGripClick` 호출 차단 → `selectedGuestIds` 빈 Set 유지 → cascade 비활성.

---

## 2. cascade 비활성 검증 (사실 기반)

| 영향 경로 | 상태 |
|---|---|
| `selectedGuestIds` 채워짐 | PC에서 `onGripClick` 미호출 → 빈 Set 유지 ✓ |
| `selectionActive` | `selectedGuestIds.size > 0` → 항상 false ✓ |
| `useGuestDropTarget.enabled` (RoomRow/GuestZone) | `selectionActive && ...` → false → `dropZoneProps = {}` (`data-drop-zone`, mouse handlers 미등록) ✓ |
| `cursor-pointer` 클래스 (RoomRow:147, GuestZone:108, 140) | `selectionActive && isActive` → false → 미적용 ✓ |
| toast (useGuestSelection useEffect L35-55) | `selectionActive=false` 분기 → `toast.dismiss('selection-mode')` ✓ |
| `onDropZoneClick` (useGuestMove L739) | `if (selectedGuestIds.size === 0) return` → early return ✓ |
| `RoomAssignment.tsx:592 onZoneHover` | `if (selectedGuestIds.size === 0) return` → 본체 미실행. 함수 자체 제거는 #11 |

---

## 3. 변경 대상 코드

### 3-1. `GuestRow.tsx` — 행 onClick 가드

**Before** (150-163줄):
```tsx
onClick={(e: React.MouseEvent) => {
  if (isCancelled) return;
  // long-press 직후 발화하는 합성 click 무시 (선택 토글 방지)
  if (longPressFiredRef.current) {
    longPressFiredRef.current = false;
    return;
  }
  if (showGrip && !(e.target as HTMLElement).closest('input, textarea, select, [data-interactive], button, a, [role="button"]')) {
    if (selectionActive && !isSelected) {
      return;
    }
    onGripClick(e, res.id);
  }
}}
```

**After**:
```tsx
onClick={(e: React.MouseEvent) => {
  if (isCancelled || isDesktop) return;
  // long-press 직후 발화하는 합성 click 무시 (선택 토글 방지)
  if (longPressFiredRef.current) {
    longPressFiredRef.current = false;
    return;
  }
  if (showGrip && !(e.target as HTMLElement).closest('input, textarea, select, [data-interactive], button, a, [role="button"]')) {
    if (selectionActive && !isSelected) {
      return;
    }
    onGripClick(e, res.id);
  }
}}
```

> `isDesktop` 은 단계 #4에서 `useDraggable` 호출 시 이미 정의됨.

### 3-2. `CompactGuestCell.tsx` — grip div onClick 가드

**Before** (68줄):
```tsx
onClick={(e: React.MouseEvent) => onGripClick(e, guest.id)}
```

**After**:
```tsx
onClick={(e: React.MouseEvent) => {
  if (isDesktop) return;
  onGripClick(e, guest.id);
}}
```

> `isDesktop` 은 단계 #4에서 정의됨.

---

## 4. 동작 동등성

| 케이스 | #7 후 | 이 단계 이후 |
|---|---|---|
| PC — 그립 단순 클릭 (이동<4px) | onClick → onGripClick → 선택 토글 | onClick → `if (isDesktop) return` → **아무 일 안 함** ✅ (의도된 변화) |
| PC — 그립 드래그 (이동≥4px) | useDraggable → onDragStart → setActiveResId → 드롭 시 handleDropOnRoom | 동일 ✅ |
| PC — 행 본문(이름/메모 등) 클릭 | (다음 단계 #9 이전) → 더블클릭으로 편집 | 동일 ✅ — #9 적용 전까지 더블클릭 진입 유지 |
| PC — toast 표시 | (그립 클릭 시 잠깐 toast) | toast 미발화 (selectionActive=false 유지) ✅ |
| PC — RoomRow/GuestZone cursor-pointer | (selectionActive 가능) | 영구 미적용 (selectionActive=false 유지) ✅ |
| PC — 우클릭 컨텍스트 메뉴 | 정상 | 동일 ✅ (onContextMenu는 isDesktop 가드 없음, #9에서 편집 상태 추가) |
| 모바일 — 행/그립 클릭 | 선택 토글 | 동일 ✅ (`isDesktop=false`) |
| 모바일 — 롱프레스 컨텍스트 메뉴 | 정상 | 동일 ✅ |
| CompactGuestCell — PC 그립 클릭 | onClick → 선택 토글 | `if (isDesktop) return` → 아무 일 안 함 ✅ |
| CompactGuestCell — PC 그립 드래그 | useDraggable → 정상 drag | 동일 ✅ |
| CompactGuestCell — 모바일 그립 클릭 | 선택 토글 | 동일 ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `useGuestSelection` 내부 — 변경 없음. PC에서는 `onGripClick` 미호출이라 timer/toast/ESC 핸들러 모두 dead state로 유지
- `useGuestDropTarget` — `enabled=false` 자동 비활성 (검증됨)
- `useGuestMove` — `onDropZoneClick`은 `selectedGuestIds.size === 0` early return으로 자동 dead
- `useContextMenu` — 영향 없음 (#9에서 canOpen 강화)
- `longPress*` — 모바일 onTouchStart/Move/End/Cancel만 발화 → PC에서 미사용
- 모바일 `QuickMenuBar` selection 영역 (`selectionActive && isMobile`) — 모바일 viewport에서 그대로

---

## 6. 검증 체크리스트

- [ ] PC viewport (≥1024):
  - 그립 단순 클릭 → toast 없음, 선택 표시 없음, 배경 변화 없음
  - 그립 드래그 → 정상 (dnd-kit drag)
  - 행 본문 클릭 → 단순 클릭은 아무 일 없음 (현재 단계), 더블클릭은 InlineInput 편집 (#9 적용 전까지)
  - 우클릭 → 컨텍스트 메뉴 정상
- [ ] 모바일 viewport (<1024):
  - 그립 클릭 → 선택 토글, toast 표시 정상
  - 다른 zone 클릭 → 이동 동작 정상
  - 롱프레스 → 컨텍스트 메뉴 정상
- [ ] TypeScript 빌드 오류 없음
