# 단계 #10: DragOverlay 컴팩트 카드 (GuestDragCard 신규)

> 작성일: 2026-05-16
> 단계: 10 / 11
> 섹션: E. UX 정리
> 동작 변화: ⚫ 시각 개선만 — 이동 로직 영향 없음
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

단계 #7의 텍스트 placeholder를 `GuestDragCard` 컴팩트 카드로 교체.
이름 + suffix(N회/M세) + 파티/성별 인원 표시.

---

## 2. 변경 대상 코드

### 2-1. 신규 `frontend/src/pages/RoomAssignment/components/shared/GuestDragCard.tsx`

```tsx
import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import type { Reservation } from '../../types';

interface GuestDragCardProps {
  reservation: Reservation;
}

/**
 * DragOverlay 내용물 — 드래그 중 마우스 위에 떠다니는 컴팩트 카드.
 */
export function GuestDragCard({ reservation }: GuestDragCardProps) {
  const gp = formatGenderPeople(reservation);
  const suffix = formatGuestSuffix(reservation);

  return (
    <div className="rounded-xl bg-white dark:bg-[#1E1E24] shadow-lg border border-[#3182F6]/30 dark:border-[#3182F6]/30 px-3 py-2 flex items-center gap-2 whitespace-nowrap min-w-[120px]">
      <span className="font-medium text-body text-[#191F28] dark:text-white">
        {reservation.customer_name}
      </span>
      {suffix && (
        <span className="text-caption text-[#8B95A1] dark:text-[#4E5968]">{suffix}</span>
      )}
      {gp && (
        <span className="text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>
      )}
    </div>
  );
}
```

### 2-2. `RoomAssignment.tsx` import 추가

**Before** (component imports 부근, 47-48 줄 부근):
```tsx
import { GuestRow } from './RoomAssignment/components/shared/GuestRow';
import { CompactGuestCell } from './RoomAssignment/components/shared/CompactGuestCell';
```

**After**:
```tsx
import { GuestRow } from './RoomAssignment/components/shared/GuestRow';
import { CompactGuestCell } from './RoomAssignment/components/shared/CompactGuestCell';
import { GuestDragCard } from './RoomAssignment/components/shared/GuestDragCard';
```

### 2-3. DragOverlay placeholder 교체

**Before** (단계 #7 placeholder):
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

**After**:
```tsx
      <DragOverlay>
        {activeResId !== null
          ? (() => {
              const res =
                reservations.find((r) => r.id === activeResId)
                ?? nextDayReservations.find((r) => r.id === activeResId);
              return res ? <GuestDragCard reservation={res} /> : null;
            })()
          : null}
      </DragOverlay>
```

---

## 3. 동작 동등성 / 변화

| 케이스 | #9 후 | 이 단계 이후 |
|---|---|---|
| 드래그 시작 | 텍스트만 표시 | 이름 + suffix + 인원 표시 카드 ✅ |
| 이동 로직 | 정상 | 동일 ✅ |
| 모달 z-index | drag 종료 시 unmount로 충돌 없음 | 동일 ✅ |

---

## 4. 영향받지 않음을 확인할 코드 경로

- `handleDropOnRoom/Pool/Party` — 변경 없음
- `useGuestMove`, `useGuestSelection`, `useGuestDropTarget` — 변경 없음
- 다른 GuestRow/CompactGuestCell 렌더 — 영향 없음 (DragOverlay 내용물만 변경)

---

## 5. 검증 체크리스트

- [ ] 드래그 시작 → 마우스 따라 컴팩트 카드 표시
- [ ] 카드 내 이름/suffix/인원이 데이터와 일치
- [ ] 드롭 또는 ESC 시 카드 사라짐
- [ ] 다크 모드 색상 정상
- [ ] TypeScript 빌드 오류 없음
