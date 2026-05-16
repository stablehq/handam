# 단계 #9: InlineInput singleClick + 편집 중 우클릭 컨텍스트 메뉴 차단

> 작성일: 2026-05-16
> 단계: 9 / 11
> 섹션: D. 클릭-선택 시스템 PC 비활성화 + 편집 단일클릭
> 동작 변화: 🔵 의도된 변화 — PC 단일클릭 편집 진입 + 편집 중 우클릭 컨텍스트 메뉴 차단
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

- PC에서 InlineInput 단일클릭으로 편집 진입 (모바일은 기존 더블탭 유지).
- 단일클릭 편집 활성화로 편집 진입 빈도가 늘어남 → 편집 중 우클릭 시 컨텍스트 메뉴가 열리는 기존 버그를 사전 차단.

---

## 2. 우클릭 차단 구현 방식 결정 (사실 기반)

| 후보 | 장점 | 단점 |
|---|---|---|
| `useContextMenu.canOpen`에 `editingInputId` 추가 | hook 책임 통일 | InlineInput → GuestRow → RoomAssignment 양방향 prop drilling 필요. state 동기화 race 가능성 |
| **GuestRow/CompactGuestCell `onContextMenu`에서 `document.activeElement instanceof HTMLInputElement` 체크** ✅ | 변경 1줄. 동기 체크라 race 없음. state 추가 0 | input 종류 구분 불가 (단, 다른 input은 행 onContextMenu에 전파 안 되거나 modalVisible로 이미 가드 → 영향 없음) |

**결정**: `document.activeElement` 체크 채택.

**검증**:
- `InlineInput` input의 `onContextMenu={(e) => e.stopPropagation()}` (L105) — 이미 input 위 우클릭은 행으로 전파 안 됨 (native paste/select menu 활성). **input 바깥 행 영역 우클릭만이 문제**.
- `modalVisible` 가드 (RoomAssignment.tsx useContextMenu.canOpen) — 모달의 input은 모달이 열려 있어 `useContextMenu.canOpen=false`로 차단됨. 우리 동기 체크는 추가 안전망일 뿐 충돌 없음.
- `TextInput` (date picker 855줄 등) — 행 onContextMenu 발화 경로와 무관.

---

## 3. quickAddedId autoFocus vs 단일클릭 충돌 검증

- `InlineInput` autoFocus: 마운트 시 effect 1회 (`useEffect` L43-50, deps []) → `committedRef.current=false` + `setEditing(true)` + `onActivate?.()`.
- 단일클릭: 사용자 마우스 click → `activate()` → 동일 동작.
- React 18 setState batching: 둘 다 동기 callback 안에서 호출됨. 마운트 effect와 사용자 click이 동시에 발화될 일 없음 (시간 순서로 분리).
- **결론**: 충돌 없음.

---

## 4. 변경 대상 코드

### 4-1. `InlineInput.tsx` — singleClick prop + display span 분기

**Before** (interface):
```tsx
interface InlineInputProps {
  value: string;
  ...
  onActivate?: () => void;
}
```

**After**:
```tsx
interface InlineInputProps {
  value: string;
  ...
  onActivate?: () => void;
  /** PC에서 단일클릭으로 편집 진입 (true). false면 더블클릭 (모바일 기존 동작). */
  singleClick?: boolean;
}
```

**Before** (함수 시그니처):
```tsx
export const InlineInput = ({
  value,
  ...
  onActivate,
}: InlineInputProps) => {
```

**After**:
```tsx
export const InlineInput = ({
  value,
  ...
  onActivate,
  singleClick,
}: InlineInputProps) => {
```

**Before** (display 모드 span, L112-114):
```tsx
    <span
      onDoubleClick={activate}
      onTouchEnd={handleTouchEnd}
```

**After**:
```tsx
    <span
      onClick={singleClick ? activate : undefined}
      onDoubleClick={!singleClick ? activate : undefined}
      onTouchEnd={handleTouchEnd}
```

**Before** (title 안내 L124):
```tsx
      title={disabled ? undefined : '더블클릭하여 수정'}
```

**After**:
```tsx
      title={disabled ? undefined : (singleClick ? '클릭하여 수정' : '더블클릭하여 수정')}
```

### 4-2. `GuestRow.tsx` — InlineInput 5곳에 singleClick={isDesktop} + onContextMenu 가드

**Before** (5개 `<InlineInput ... />` 호출에 `singleClick={isDesktop}` 추가):
- L184 (customer_name)
- L192 (phone)
- L195 (party_type)
- L198 (genderPeople)
- L207 (notes)

**Before** (행 onContextMenu, L106):
```tsx
onContextMenu={(e) => { if (!isCancelled) onGuestContextMenu(e, res.id, zone); }}
```

**After**:
```tsx
onContextMenu={(e) => {
  if (isCancelled) return;
  // 편집 중 InlineInput input이 활성이면 컨텍스트 메뉴 차단
  if (document.activeElement instanceof HTMLInputElement) return;
  onGuestContextMenu(e, res.id, zone);
}}
```

### 4-3. `CompactGuestCell.tsx` — InlineInput 4곳에 singleClick={isDesktop} + 외피 div onContextMenu 가드

**Before** (4개 `<InlineInput ... />` 호출에 `singleClick={isDesktop}` 추가):
- L86 (customer_name)
- L93 (phone)
- L98 (party_type)
- L103 (genderPeople)

**Before** (외피 div onContextMenu, L64):
```tsx
onContextMenu={(e) => onGuestContextMenu(e, guest.id)}
```

**After**:
```tsx
onContextMenu={(e) => {
  if (document.activeElement instanceof HTMLInputElement) return;
  onGuestContextMenu(e, guest.id);
}}
```

---

## 5. 동작 동등성 / 의도된 변화

| 케이스 | #8 후 | 이 단계 이후 |
|---|---|---|
| PC — InlineInput 더블클릭 | 편집 진입 | `onDoubleClick=undefined` → 발화 안 함 (의도된 변화, 단일클릭으로 통일) |
| PC — InlineInput 단일클릭 | 아무 일 없음 | 편집 진입 ✅ |
| PC — InlineInput 키보드 Tab focus | activate 발화 (L121-123) | 동일 ✅ (focus-visible 게이트) |
| 모바일 — InlineInput 더블탭 | 편집 진입 (handleTouchEnd) | 동일 ✅ (singleClick=false) |
| 모바일 — InlineInput 단일탭 | 합성 click 발화? span에 onClick 없으니 무동작 | 동일 ✅ (singleClick=false → onClick=undefined) |
| PC — 편집 중 input 위 우클릭 | input의 stopPropagation → 행 전파 안 됨 (native menu) | 동일 ✅ |
| PC — 편집 중 행 본문(input 바깥) 우클릭 | onContextMenu 발화 → 컨텍스트 메뉴 표시 (버그) | `document.activeElement instanceof HTMLInputElement` → 차단 ✅ (의도된 수정) |
| PC — 비편집 상태 행 우클릭 | onContextMenu → 컨텍스트 메뉴 표시 | 동일 ✅ (activeElement는 body 등) |
| PC — quickAddedId 자동 편집 | autoFocus → editing 모드 | 동일 ✅ |
| 모바일 — 롱프레스 컨텍스트 메뉴 | 정상 | 동일 ✅ (longPressFiredRef 경로) |

---

## 6. 영향받지 않음을 확인할 코드 경로

- `InlineInput` editing 모드 input (L82-108) — 변경 없음
- `RoomMemoEditor` — InlineInput 사용 여부 별도 확인 (`RoomMemoEditor.tsx`): 자체 input 구현이고 InlineInput 안 씀 → 영향 없음
- `useContextMenu` — 시그니처 그대로
- `useGuestSelection.cancelDeselect` — 편집 진입 시 호출 (`onActivate`). PC에서는 timer 없으니 no-op. 영향 없음
- 모달 inputs — `onContextMenu` 발화 시 행 경로와 무관

---

## 7. 검증 체크리스트

- [ ] PC viewport (≥1024):
  - InlineInput 단일클릭 → 즉시 편집 진입, 포커스, 커서 표시
  - InlineInput 더블클릭 → 첫 클릭만 발화하고 두 번째 클릭은 input 내부 클릭 → 정상
  - 편집 중 행 본문(input 바깥) 우클릭 → 컨텍스트 메뉴 미표시
  - 비편집 상태 행 우클릭 → 컨텍스트 메뉴 표시 (기존)
  - 편집 중 다른 곳 클릭 → onBlur → commit + 저장
  - 편집 중 ESC → 취소 (기존)
  - 편집 중 Enter → commit + blur (기존)
  - quickAddedId(빠른 추가) 새 게스트 → 이름 칸 자동 편집 모드
- [ ] 모바일 viewport (<1024):
  - InlineInput 단일탭 → 아무 일 없음
  - InlineInput 더블탭 → 편집 진입
  - 편집 중 롱프레스 → 합성 click 차단 + 컨텍스트 메뉴 표시 (롱프레스는 input 바깥 경로 → activeElement 체크 안 걸림)
  - 단, 모바일에서 가상키보드 띄운 상태에서 다른 행 롱프레스 → 컨텍스트 메뉴 차단됨? input이 activeElement면 차단. 이 케이스는 의도된 동작 (편집 중 다른 행 메뉴 차단)
- [ ] TypeScript 빌드 오류 없음
