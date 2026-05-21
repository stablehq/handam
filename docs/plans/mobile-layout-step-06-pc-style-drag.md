# Mobile Layout Step #06 — 모바일 인터랙션을 PC 와 동일화 (drag 기반)

> 작성일: 2026-05-20
> 부모: [mobile-layout-migration-plan.md](./mobile-layout-migration-plan.md)
> 직전: Step #03b/#04/#05 (모바일 카드 레이아웃)
> 동작 변화: **모바일 인터랙션 패러다임 전환** (selection → drag)

---

## 목표

모바일 인터랙션을 PC 와 1:1 동일하게:

| 인터랙션 | PC (현재) | 모바일 (현재) | 모바일 (목표) |
|---------|----------|--------------|---------------|
| 게스트 이동 | grip drag → drop | 탭 선택 → 목적지 탭 | grip drag → drop (PC 와 동일) |
| 인라인 편집 진입 | 셀 단일 클릭 | 셀 탭 후 선택모드 진입 시 차단 | 셀 단일 탭 (PC 와 동일) |
| 컨텍스트 메뉴 | 우클릭 | 롱프레스 (500ms) | **롱프레스 유지** (= 우클릭 대용) |
| 다중 선택 | 없음 | 탭으로 다중 선택 가능 | **없음** (트레이드오프) |
| ESC | 해당 없음 (선택 없음) | 선택 해제 | 해당 없음 |

---

## 충돌 분석 (핵심)

### 1. dnd-kit `useDraggable` × 페이지 스크롤 (해결됨)

**우려**: 터치 드래그가 활성되면 페이지 세로 스크롤이 막힘.

**실제**: `useDraggable` 의 `{...listeners}` 는 **grip 요소에만** 부착됨. 사용자가 grip 이외 영역(이름/전화/메모 등)을 터치하면 dnd-kit 이 pointerdown 을 받지 않음 → 페이지 정상 스크롤.

→ **충돌 없음.** grip 만 드래그 영역.

### 2. 드래그 vs 롱프레스 동시 트리거 (완화책 필요)

**시나리오**: 사용자가 grip 을 누르고 500ms 이상 가만히 있다가 움직이기 시작.

- 0~500ms 가만히 있음: 롱프레스 타이머 미발화, 드래그 미활성 (4px 미달)
- 500ms 시점 발화: **컨텍스트 메뉴 열림** (의도치 않음)
- 그 후 손가락 움직임: 드래그 활성하려 하지만 컨텍스트 메뉴 떠 있음

**완화책 A**: `handleDragStart` 에서 longPressTimerRef 클리어 (parent 의 핸들러에서). 단 이미 컨텍스트 메뉴가 fired 된 후엔 무의미.

**완화책 B**: `onTouchMove` 가 longPressTimer 를 이미 클리어 — 4px 이내의 미세 움직임도 클리어 트리거. 정상 드래그는 보통 즉시 움직이므로 자연스럽게 timer 클리어. **현재 코드 그대로 OK.**

**잔여 케이스**: "grip 을 정확히 500ms 이상 가만히 잡고 움직이려는" 시도 — 컨텍스트 메뉴가 나오면 사용자가 dismiss 하고 다시 시도. **수용 가능 UX**.

### 3. 단일 탭 vs 드래그 시작

**시나리오**: grip 을 잠시 탭 (이동 < 4px).
- 드래그 미활성 (distance 4px 미달)
- 합성 click 이벤트 발화
- 현재: grip 에 onClick 이 onGripClick (선택 토글) 호출 — **이걸 제거해야 함**
- 변경 후: 아무 동작 안 함 (의도)

### 4. 셀 탭 → InlineInput 편집

PC `singleClick={isDesktop}` 가 true → 단일 클릭으로 편집 진입. 모바일에선 false → 더블 탭 필요했음.

**변경**: 모든 호출처에서 `singleClick={true}` (또는 prop 제거). 모바일도 단일 탭 = 편집.

### 5. SmsCell 탭

`SmsCell` 은 자체 onClick 으로 드롭다운 열기. 변경 불필요.

---

## 파일별 변경 명세

### `frontend/src/hooks/use-mobile.ts` — 변경 없음
- 이미 fix 됨 (mql.matches 사용)

### `frontend/src/pages/RoomAssignment.tsx`
- **sensors 추가**: 현재 `PointerSensor` 만 등록. 터치 안정성을 위해 `TouchSensor` 도 추가 검토.
  - 권장: `PointerSensor + TouchSensor` 조합. dnd-kit 의 표준 패턴.
  - `TouchSensor` 의 `activationConstraint` 도 `{distance: 4}` 로 설정 (delay 없이).
  - 또는 **PointerSensor 만 유지** — 모던 브라우저는 PointerSensor 가 터치도 처리. 충분.

### `frontend/src/pages/RoomAssignment/hooks/useSelectionSystem.ts`
- 현재: PC=fixture, 모바일=real selection. → 모바일도 fixture 사용.
- 변경:
  ```tsx
  if (isDesktop) { ... fixture ... }
  // ↓ 변경 후
  // 항상 fixture — selection 시스템 폐기
  ```
- 또는 useSelectionSystem 자체 제거하고 부모에서 직접 fixture 상수 사용.
- **단**: hover/setHover/clearHover 는 drop zone hover 표시에 여전히 필요. 이건 유지.
- 권장: useGuestSelection 호출 제거, useHoverZone 만 유지.

### `frontend/src/pages/RoomAssignment/components/shared/GuestRow.tsx`
- **line 88** `disabled: !isDesktop || isCancelled` → `disabled: isCancelled` (모바일도 드래그 활성)
- **line 163-176** 외곽 `onClick` (selection 호출) — 제거 (드래그가 대체)
- **line 183** className 의 `cursor-grab active:cursor-grabbing` 조건 — 항상 적용
- **line 189-198** grip 아이콘 분기 — 항상 `GripVertical` (Circle 제거)
- **line 204, 212, 215, 218, 227** `singleClick={isDesktop}` → `singleClick` (true 고정, prop 자체 제거 또는 always true)
- **롱프레스 / 컨텍스트 메뉴 onTouchStart/End/Move/Cancel** — **유지** (우클릭 대용)

### `frontend/src/pages/RoomAssignment/components/shared/MobileGuestRow.tsx`
- 동일하게 처리:
  - useDraggable `disabled: isCancelled` 만 유지
  - 외곽 onClick (선택) 제거
  - grip 의 onClick (최근 fix 한 것) 제거
  - grip 아이콘 GripVertical 로 고정 (Circle 제거)
  - InlineInput singleClick 항상 true
  - 롱프레스 핸들러 유지

### `frontend/src/pages/RoomAssignment/components/shared/CompactGuestCell.tsx`
- **line 48** `disabled: !isDesktop` → `disabled: false` (또는 prop 자체 제거)
- **line 84-86** onClick (선택 호출) — 제거
- **line 87, 93-101** grip 아이콘 분기 → 항상 GripVertical
- **line 109, 117, 122, 127** singleClick → true

### `frontend/src/pages/RoomAssignment/components/RoomRow.tsx`
- **line 138** `disabled: !isDesktop || !isActive` → `disabled: !isActive`
- **line 142** `disabled: !isDesktop || !isActive || !nextDayExpanded` → `disabled: !isActive || !nextDayExpanded`

### `frontend/src/pages/RoomAssignment/components/MobileRoomCard.tsx`
- **line 112** `disabled: !isDesktop || !isActive` → `disabled: !isActive`
- **line 116** `disabled: !isDesktop || !isActive || !nextDayExpanded` → `disabled: !isActive || !nextDayExpanded`

### `frontend/src/pages/RoomAssignment/components/zones/GuestZone.tsx`
- **line 108** `disabled: !isDesktop || !accept || !zoneId` → `disabled: !accept || !zoneId`
- **line 112** `disabled: !isDesktop || !accept || !nextZoneId || !nextDayExpanded` → `disabled: !accept || !nextZoneId || !nextDayExpanded`

### `frontend/src/pages/RoomAssignment/components/zones/MobileGuestZone.tsx`
- 동일 (line 58, 62)

### `frontend/src/pages/RoomAssignment/components/InlineInput.tsx`
- `singleClick` prop 인터페이스 변경 검토. 모든 호출처가 true 가 되면 prop 자체 제거 가능. 단 점진 마이그레이션 위해 prop 유지 + 호출처에서 true 고정 권장.

### `frontend/src/pages/RoomAssignment/hooks/useContextMenu.ts`
- `mobileContextMenuOpen` / `mobileContextBtnRef` 관련 상태 제거 검토.
- 롱프레스 컨텍스트 메뉴 자체는 유지 (longPressTimerRef, longPressFiredRef).
- 단순화: mobile-specific 분기 다 제거, 단일 컨텍스트 메뉴 흐름만.

### `frontend/src/pages/RoomAssignment/components/QuickMenuBar.tsx`
- `isMobile`, `selectionActive`, `selectedCount`, `mobileContextBtnRef`, `mobileContextMenuOpen`, `onToggleMobileContext`, `onCallSelected`, `onDeleteSelected` props 제거.
- 단순화: 되돌리기 / 자동배정 / 파티추가 버튼만.
- RoomAssignment.tsx 의 QuickMenuBar 호출부도 props 정리.

### `frontend/src/pages/RoomAssignment.tsx`
- selectedGuestIds, setSelectedGuestIds 관련 코드 — 제거 가능 여부 검토.
- selectionActive 사용처 — drop zone hover 등에서 참조. selectionActive=false 로 고정 가능.
- contextMenuActions — selection 의존 부분 제거 후 단일 게스트 기준으로 단순화 필요.
  - 현재 선택된 게스트들에 대한 일괄 작업 (색상 일괄 변경, 일괄 삭제, 일괄 unstable 복사 등) 다중 처리 로직이 있는데, 다중 선택 없어지면 단일 처리만.
- useGuestMove 의 selectedGuestIds 의존 분기 — 제거 또는 단일 게스트 기준 재작성.

---

## 트레이드오프

### ❌ 잃는 것: 다중 선택 → 일괄 작업
PC 는 단일 드래그만. 모바일도 동일하게 됨 → 한 번에 여러 게스트를 같은 객실로 이동 / 같은 색상 적용 / 일괄 삭제 등 불가.

**대안**:
- 컨텍스트 메뉴에서 "이 객실의 모두 선택" 같은 옵션 추가 (별도 기능)
- 또는 keep current PC behavior — PC 도 다중 선택 없으니 기능 일관성

### ✅ 얻는 것
- PC/모바일 코드 일관 — 분기 80% 감소
- 모바일 UX 가 익숙한 패턴 (스마트폰 OS 와 동일: 길게 누르면 메뉴, 끌어서 이동)
- selection mode 진입/해제 같은 추가 step 제거 → 빠른 작업

---

## 단계 분해 옵션

전체 변경량 큰 편(8개 파일, ~100줄 수정). 안전을 위해 분할 권장.

### 옵션 1 — 한 번에 (Step #06 단일 PR)
- 👍 빠름, 일관된 시점에 전환
- 👎 회귀 시 디버깅 영역 큼

### 옵션 2 — 3 sub-step (권장)

#### Step #06a: drag 인프라 활성화 (동작 추가, 기존 제거 X)
- 모든 `disabled: !isDesktop` 가드 제거 → 모바일 드래그/드롭 활성
- InlineInput `singleClick` 모두 true 로
- 아이콘 분기 (GripVertical / Circle) → 항상 GripVertical
- **selection 시스템은 일단 유지** (코드 그대로) — 모바일에서 드래그 가능해지지만 선택도 여전히 가능
- 검증: 모바일에서 grip 드래그 가능, 단일 탭 편집 가능

#### Step #06b: selection 시스템 제거 (mobile 만)
- useSelectionSystem 의 모바일 분기를 fixture (PC 와 동일) 로 변경
- 외곽 onClick (선택 호출) 제거 — GuestRow, MobileGuestRow, CompactGuestCell
- 그립의 onClick (최근 fix) 제거 — MobileGuestRow
- 검증: 모바일에서 탭으로 선택 안 됨, 드래그만 작동

#### Step #06c: 잔재 정리
- useContextMenu mobile 분기 제거
- QuickMenuBar 의 mobile 컨텍스트 버튼 제거
- contextMenuActions 단일 처리화
- selectedGuestIds 관련 dead code 정리
- 검증: 전체 회귀 0

### 옵션 3 — Step #06a 만 (점진 전환)
- 드래그 활성 + 단일 탭 편집만 적용
- selection mode 도 공존 (사용자가 둘 다 사용 가능)
- 충돌 가능성: grip 의 onClick 이 셀렉트 → 의도치 않은 선택. 이건 #06a 에서 grip onClick 제거.
- 👍 가장 안전, 사용자가 점진 적응
- 👎 코드 일관성 떨어짐 (selection 시스템 dead/alive 혼재)

---

## 추천: 옵션 2

각 단계가 독립 롤백 가능. #06a 만 끝나도 핵심 기능 (드래그, 단일 탭 편집) 작동.

---

## 검증 체크리스트 (Step #06 전체 완료 후)

### PC (≥1024px)
- [ ] 기존 동작 0 변화: 드래그/우클릭/단일 클릭 편집 동일

### 모바일 (<768px)
- [ ] grip 잡고 드래그 → 객실/zone 으로 이동
- [ ] 다음날 컬럼으로 cross-day 드래그
- [ ] 셀 단일 탭 → InlineInput 편집 진입
- [ ] SMS 칩 탭 → 드롭다운
- [ ] 롱프레스 (500ms) → 컨텍스트 메뉴
- [ ] 페이지 세로 스크롤 (grip 외부 swipe) — 정상
- [ ] 빈 객실 영역 탭 (selectionActive 항상 false 이므로 노액션) — 정상
- [ ] dark mode

### 경계
- [ ] 빠른 드래그 (즉시 이동) — 컨텍스트 메뉴 안 뜸
- [ ] 느린 드래그 (잡고 600ms 후 이동) — 컨텍스트 메뉴 한 번 뜨고 사라짐 (수용 UX)
- [ ] 짧은 탭 — 셀이면 편집, grip 이면 무동작
- [ ] cancelled 게스트 grip — 드래그 비활성 (현행 유지)

---

## 환각 방지 메모

본 사전조사 작성 시 직접 확인된 사항:
- 모든 `disabled: !isDesktop || ...` 위치 grep 으로 6곳 식별
- 모든 `singleClick={isDesktop}` 위치 grep 으로 8곳 식별
- `useSelectionSystem.ts` 실제 fixture 분기 read 로 확인 (line 37-48 PC 분기)
- `GuestRow.tsx` 의 onClick 흐름 (line 163-176) read 확인
- `MobileGuestRow.tsx` 의 grip onClick (최근 fix) — 이 단계에서 제거 대상

dnd-kit 의 PointerSensor + useDraggable 동작은 공식 문서 + 기존 PC 동작 관찰 기반.
