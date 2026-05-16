# 단계 #6: onDragEnd 라우팅 구현

> 작성일: 2026-05-16
> 단계: 6 / 11
> 섹션: C. 드래그 → 드롭 실제 연결
> 동작 변화: 🔵 의도된 변화 — PC에서 드래그 → 드롭으로 게스트 이동이 동작
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`handleDragEnd` 본문을 구현. `over.id` 파싱 후 `handleDropOnRoom`/`handleDropOnPool`/`handleDropOnParty` 라우팅.
선언 위치를 useGuestMove 이후로 이동(클로저 캡처).

---

## 2. 클로저 의존성 / 위치 이동

`handleDragEnd`는 `setSelectedGuestIds`, `selectedDate`, `showConfirm`, `handleDropOnRoom`, `handleDropOnPool`, `handleDropOnParty`를 참조.

선언 시점에 모두 정의되어 있어야 함:
- `setSelectedGuestIds`: `useGuestSelection` (192-195) 결과
- `handleDropOnRoom/Pool/Party`: `useGuestMove` (232-251) 결과
- `showConfirm`: `useConfirmDialog` (209) 결과
- `selectedDate`: useState (101) 결과

→ 단계 #3에서 188 부근에 둔 `handleDragStart/End/Cancel` 함수 3개를 **useGuestMove 호출 직후로 이동**.
`activeResId` state와 `sensors` 선언은 188 부근에 그대로 유지.

---

## 3. 변경 대상 코드

### 3-1. 188 부근 — handler 3개 제거 (state + sensors는 유지)

**Before**:
```tsx
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

**After**:
```tsx
  const [activeResId, setActiveResId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 4 },
    }),
  );
  // handleDragStart/End/Cancel은 useGuestMove 직후에 정의 (클로저 의존성)
```

### 3-2. useGuestMove 호출 직후 — handler 3개 정의

`useGuestMove({...})` 호출(232-251) 끝 다음 위치에 추가:

```tsx
  // dnd-kit handlers — useGuestMove 결과(handleDropOnRoom 등)에 의존하므로 이 위치
  const handleDragStart = (_event: DragStartEvent) => {
    // #7에서 setActiveResId(active.id) + document.activeElement.blur() 구현
  };
  const handleDragCancel = () => {
    // #7에서 setActiveResId(null) 구현
  };
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    // PC #8 전 중간 상태: 클릭 선택 후 드래그 시 toast 잔존 방지 안전망
    setSelectedGuestIds(new Set());
    if (!over) return;

    const activeStr = String(active.id);
    const overStr = String(over.id);

    // active.id prefix로 출발지 판별
    let resId: number;
    let sourceIsNextDay: boolean;
    if (activeStr.startsWith('guest-next-')) {
      resId = Number(activeStr.replace('guest-next-', ''));
      sourceIsNextDay = true;
    } else if (activeStr.startsWith('guest-')) {
      resId = Number(activeStr.replace('guest-', ''));
      sourceIsNextDay = false;
    } else {
      return;
    }
    if (!Number.isFinite(resId)) return;

    // over.id 분기 — 기존 onDropZoneClick과 동일 cross-day 모달 패턴
    if (overStr.startsWith('next-room-')) {
      const roomId = Number(overStr.replace('next-room-', ''));
      const targetDate = selectedDate.add(1, 'day');
      if (!sourceIsNextDay) {
        // 오늘 → 내일 cross-day
        showConfirm(
          '날짜 이동 확인',
          '오늘 체크인 게스트를 내일 방에 배정하시겠습니까?\n예약 날짜가 내일로 변경됩니다.',
          () => handleDropOnRoom(resId, roomId, targetDate),
        );
        return;
      }
      handleDropOnRoom(resId, roomId, targetDate);
    } else if (overStr.startsWith('room-')) {
      const roomId = Number(overStr.replace('room-', ''));
      if (sourceIsNextDay) {
        // 내일 → 오늘 cross-day
        showConfirm(
          '날짜 이동 확인',
          '내일 체크인 게스트를 오늘 방에 배정하시겠습니까?\n예약 날짜가 오늘로 변경됩니다.',
          () => handleDropOnRoom(resId, roomId),
        );
        return;
      }
      handleDropOnRoom(resId, roomId);
    } else if (overStr === 'next-pool') {
      handleDropOnPool(resId, selectedDate.add(1, 'day'));
    } else if (overStr === 'next-party') {
      handleDropOnParty(resId, selectedDate.add(1, 'day'));
    } else if (overStr === 'pool') {
      handleDropOnPool(resId);
    } else if (overStr === 'party') {
      handleDropOnParty(resId);
    }
  };
```

---

## 4. 동작 동등성 / 의도된 변화

| 케이스 | 기존 (#5 후) | 이 단계 이후 |
|---|---|---|
| PC — 그립 드래그 → 객실 드롭 | drag 사이클 + onDragEnd noop → 이동 없음 | `handleDropOnRoom(resId, roomId)` → 객실 배정 ✅ (의도된 변화) |
| PC — 그립 드래그 → 미배정/파티 zone | 이동 없음 | `handleDropOnPool/Party(resId)` → 섹션 이동 ✅ |
| PC — 그립 드래그 → 다음날 컬럼 | 이동 없음 | cross-day 모달 → 확인 시 `handleDropOnRoom(resId, roomId, +1day)` ✅ |
| PC — 다음날 컬럼에서 드래그 → 오늘 | (다음날 컬럼은 #5 후 useDroppable.isOver 활성, drag 가능) | cross-day 모달 → 확인 시 `handleDropOnRoom(resId, roomId)` (today) ✅ |
| PC — drop 영역 밖에서 release | over=null | `setSelectedGuestIds(new Set())` 후 return ✅ |
| 모바일 — 클릭-선택 시스템 | 그대로 | useDraggable disabled → onDragEnd 미발화 ✅ |
| 연박 예약 cross-day | (선택 모드 이동 시) | `handleDropOnRoom` 내부 isMultiNight 체크 → toast 경고 + return (기존 동작 그대로 적용) ✅ |
| 연박 예약 same-day | (선택 모드 이동 시) | `handleDropOnRoom` 내부 `is_long_stay` 체크 → `setMultiNightConfirm` 모달 → onConfirm으로 `doAssignRoom` (기존 동작 그대로) ✅ |
| toast 잔존 (#8 전 PC 중간 상태) | 선택 후 드래그 시 toast 남음 | `setSelectedGuestIds(new Set())` 안전망 → 사라짐 ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `handleDropOnRoom/Pool/Party` 내부 구현 — 변경 없음. 동일 mutation 사용
- `onDropZoneClick` (useGuestMove.ts:737-808) — 변경 없음. 모바일 클릭-선택 경로 그대로
- `window.__diagAction`:
  - `doAssignRoom` → 'drag_guest_to_room:res=...,room=...' (useGuestMove.ts:244)
  - `unassignRoomMutation.mutationFn` → 'drop_on_party'/'drop_on_pool' (353-354)
  - dnd-kit 경유해도 동일 함수 호출 → prefix 보존 ✓
- 연박 모달 (`setMultiNightConfirm`) — `handleDropOnRoom` 내부 호출. dnd-kit `onDragEnd`는 동기 콜백이지만 `setState`로 모달 표시 → 다음 렌더에 정상 표시 ✓
- `useUndoStack.pushUndo` — `doAssignRoom`/`handleDropOnPool` 내부에서 호출, 변경 없음 ✓
- `ConfirmDialog` (`showConfirm` 모달) — `useConfirmDialog`로 관리, dnd-kit `onDragEnd` 내부 호출 안전 ✓

---

## 6. 검증 체크리스트

- [ ] PC:
  - 그립 → 객실 드롭: 배정 완료 toast, `Reservation.room_id` 갱신
  - 그립 → 미배정 zone: '미배정으로 이동' toast
  - 그립 → 파티 zone: '파티만으로 이동' toast
  - 그립 → 다음날 컬럼 객실: 'cross-day 확인' 모달 → 확인 시 날짜 + 객실 변경
  - 다음날 게스트 그립 → 오늘 객실: 'cross-day 확인' 모달 → 확인 시 날짜 + 객실 변경
  - drop 영역 밖 release: 아무 일도 안 일어남, toast 잔존 없음
  - 연박 예약 (`is_long_stay`) 드래그: MultiNightConfirmModal 표시 → 확인 시 처리
  - 비활성 객실 (`!isActive`): 드롭 비활성
  - 취소 행: 드래그 자체 불가
  - undo (Ctrl+Z): 드래그 후 정상 undo
- [ ] 모바일:
  - 기존 클릭-선택 동작 정상
- [ ] diag-golden:
  - 드래그 시 `window.__diagAction` prefix 'drag_guest_to_room:' / 'drop_on_pool' / 'drop_on_party' 정상 발화
- [ ] TypeScript 빌드 오류 없음
