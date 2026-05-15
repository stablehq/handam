# dnd-kit 드래그 마이그레이션 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: 단계 분해안 검토 대기
> 부모 설계: [dndkit-migration-design.md](./dndkit-migration-design.md)

---

## 진행 프로세스 (Mutator 방식 명시)

본 마이그레이션은 Mutator 마이그레이션과 동일한 프로세스로 진행한다.

```
① 설계안 합의 (현재 단계)
   → 본 분해안 검토 후 단계 분해 확정

② 단계별 순차 진행 (반복)
   1. 해당 단계의 사전조사 문서 작성 (docs/plans/dndkit-step-NN-*.md)
      — Before/After 코드 인용
      — 동작 동등성 또는 의도된 변화 근거 명시
      — 검증 체크리스트
   2. 코드 변경 PR 생성
   3. 검토 + 머지
   4. 다음 단계 사전조사 문서 작성 → 반복

③ 각 단계는 독립적으로 롤백 가능
   → 단계 #N 롤백 시 #N-1 상태로 회귀, 시스템 동작 보장
```

**핵심 원칙**: 사전조사 문서 없이 코드 변경 PR을 올리지 않는다.
단계 N을 시작하기 전에 N의 사전조사 문서가 검토 완료되어야 한다.

---

## 원칙

1. **의도된 변화만 허용** — 아래 §의도된 동작 변화 표 외의 silent behavior change 금지.
2. **각 단계는 별도 PR + 별도 사전조사 문서** — `docs/plans/dndkit-step-NN-*.md` 형식.
3. **각 사전조사 문서에 Before/After 코드 인용 + 동작 동등성 근거 명시**.
4. **각 단계는 직전 단계와 독립** — 단계 #N을 롤백해도 시스템 동작.
5. **모바일 변경 금지** — 전체 변경사항은 `useIsDesktop()` (1024px) 으로 gate. 모바일 동작은 변경 전과 동일해야 한다.
6. **handleDropOnRoom/Pool/Party 변경 금지** — API 호출 로직 전부 유지. dnd-kit은 routing만 대체.

---

## 의도된 동작 변화 (= 변경 대상)

PC에서만 적용. 모바일은 전부 기존 동작 유지.

| 항목 | 기존 PC 동작 | 변경 후 PC 동작 |
|------|-------------|----------------|
| 게스트 이동 | 그립 클릭 → 선택 toast → 목적지 클릭 (2단계) | 그립 드래그 → 드롭 (1단계) |
| 드래그 트리거 | 행 전체 클릭 가능 | 그립 div에서만 드래그 시작 |
| 인라인 편집 진입 | 더블클릭 | 단일클릭 |
| 편집 중 드래그 시작 | 편집창 열린 채 드래그 (충돌) | blur → commit → 드래그 |
| 우클릭 시 InlineInput | 배경 활성화됨 (버그) | 배경 활성화 없음 (수정) |
| 선택 toast | 매 이동마다 표시 | 표시 안 함 |

**그 외 동작은 모두 불변** — API 호출, 연박 처리, push-out, undo, 취소 행, 다음날 컬럼 등.

---

## 단계 분해 (10개)

각 단계의 **실제 동작 변화 유무**를 명시.
⚪ = 동작 변화 없음 (구조/인프라), 🔵 = 의도된 변화 (PC 동작 개선), ⚫ = UX 정리 (기능 동등)

### A. 기초 인프라 (⚪ 동작 변화 없음)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 1 | `useIsDesktop` 훅 신규 생성 — `window.matchMedia('(min-width: 1024px)')` 기반. 아직 어떤 컴포넌트도 import 안 함 | `src/hooks/use-desktop.ts` (신규) | +25 lines |
| 2 | `InlineInput.tsx:131` — span `focus:bg-[#F2F4F6] dark:focus:bg-[#2C2C34] focus:rounded` → `focus-visible:` 로 교체 (우클릭 배경 방어. 버그 수정) | `InlineInput.tsx` | 수정 1 line |

**동작 동등성**:
- #1: 아무 컴포넌트도 import 안 하므로 UI 변화 전혀 없음.
- #2: 우클릭 시 배경 미활성 — **버그 수정이므로 의도된 미세 시각 변화**. 키보드 Tab focus 시 배경 활성은 유지 (`:focus-visible`이 여전히 매칭됨).

---

### B. dnd-kit 골격 설치 (⚪ 동작 변화 없음 — 전부 disabled)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 3 | `DndContext` + `DragOverlay` 골격 + sensors 선언. `onDragStart`/`onDragEnd` noop. `activeResId` state 추가. 아직 useDraggable 연결 없으므로 드래그 미발생 | `RoomAssignment.tsx` | +30 lines |
| 4 | Grip div에 `useDraggable` 연결 — `disabled: !isDesktop \|\| isCancelled`. `isDragging` 시 `opacity-50` 추가. `onDragEnd` 아직 noop → 드래그 해도 아무 이동 없음. **`CompactGuestCell.tsx` 도 동일하게 적용** (구조 주의: grip div에 직접 onClick 바인딩이라 useDraggable ref/listeners 연결 위치가 GuestRow와 다름) | `GuestRow.tsx`, `CompactGuestCell.tsx` | +25 lines |
| 5 | 각 zone에 `useDroppable` 연결 — RoomRow: `disabled: !isDesktop \|\| !isActive`, GuestZone: `disabled: !isDesktop \|\| !accept`. `isOver` 시 배경 전환 추가. `onDragEnd` 아직 noop | `RoomRow.tsx`, `GuestZone.tsx` | +30 lines |

**동작 동등성**:
- #3: `DndContext`가 있어도 `useDraggable` 없으면 아무 이벤트도 발생 안 함.
- #4: `disabled: !isDesktop` 이므로 PC에서도 드래그 가능하지만 `onDragEnd` noop이라 이동 안 됨. 시각적 `opacity-50` 변화만 있음.
- #5: `useDroppable` 연결 후 dnd-kit이 드롭 zone을 인식하지만, onDragEnd noop 이므로 이동 없음.

**사전조사 필수 확인 항목**:
- `GuestZone.tsx`는 현재 `useGuestDropTarget`을 사용 중. `useDroppable`과 병존 시 `setNodeRef`가 동일 DOM 요소에 연결되어야 함 (ref 충돌 확인).
- `RoomRow.tsx`의 현재 drop 영역 DOM 구조 — `useDroppable.setNodeRef`를 어느 div에 연결할지 확인.

---

### C. 드래그 → 드롭 실제 연결 (🔵 의도된 변화 — PC에서만)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 6 | `onDragEnd` 구현 — `over.id` (zoneId) 파싱 → `handleDropOnRoom`/`handleDropOnPool`/`handleDropOnParty` 라우팅. `next-room-N`/`next-pool`/`next-party` 분기 포함. **`setSelectedGuestIds(new Set())` 호출 추가** — #8 이전 중간 상태에서 클릭 선택 후 드래그 시 toast 잔존 방지 | `RoomAssignment.tsx` | 수정 ~30 lines |
| 7 | `onDragStart` 구현 — `setActiveResId(active.id)` + `document.activeElement.blur()` (열린 InlineInput 자동 저장). `DragOverlay` 게스트 이름 표시 활성화 | `RoomAssignment.tsx` | 수정 ~15 lines |

**해결되는 변화 (#6, #7 이후)**:
- PC에서 그립을 드래그 → 드롭하면 객실/미배정/파티 이동이 실행됨.
- 인라인 편집 중 드래그 시작 → blur → commit → 드래그 실행 (편집 내용 보존됨).

**그 외 동작 불변 검증 항목**:
- `handleDropOnRoom`의 연박 처리, push-out, optimistic update, undo push — 전부 동일 함수이므로 동일 동작.
- 모바일: `useDraggable({ disabled: !isDesktop })` 이므로 비활성. 클릭-선택 시스템은 그대로.
- 취소 예약(`isCancelled`): `useDraggable({ disabled: isCancelled })` 이므로 드래그 불가 (기존과 동일).

---

### D. 클릭-선택 시스템 PC 비활성화 + 편집 단일클릭 (🔵 의도된 변화)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 8 | `GuestRow.tsx` 행 `onClick` 수정 — `if (isDesktop) return` 추가 (PC에서 `onGripClick` 호출 차단). cascade 비활성: `selectedGuestIds` 빈 Set → `selectionActive=false` → 호버/toast 자동 비활성. **`CompactGuestCell.tsx` grip div onClick 도 별도 처리 필수** — GuestRow는 행 onClick 버블링 구조지만 CompactGuestCell은 grip div에 직접 `onClick={(e) => onGripClick(e, guest.id)}` 바인딩이므로 `if (isDesktop) return` 위치가 다름 | `GuestRow.tsx`, `CompactGuestCell.tsx` | 수정 ~5 lines |
| 9 | `InlineInput.tsx` — `singleClick?: boolean` prop 신규. span에서 `onClick={singleClick ? activate : undefined}` + `onDoubleClick={!singleClick ? activate : undefined}` 분기. `GuestRow.tsx`에서 `singleClick={isDesktop}` 전달 | `InlineInput.tsx`, `GuestRow.tsx` | +10 lines, 수정 7 lines |

**동작 동등성 검증 항목**:
- #8: 모바일에서 `isDesktop=false` → `if (isDesktop) return` 미실행 → 기존 선택 동작 유지.
- #8: PC에서 `selectionActive` 항상 false → `GuestZone`/`RoomRow`의 `useGuestDropTarget enabled` 자동 false → hover/cursor-pointer 자동 비활성.
- #8: toast `useEffect`에서 `selectionActive=false` → `toast.dismiss` 자동 실행 → toast 없음.
- #8: `#6`의 `setSelectedGuestIds(new Set())` 와 결합해 드래그 완료 후 toast 잔존 완전 차단.
- #9: 모바일 `singleClick=false` → `onDoubleClick={activate}` 유지 — 기존과 동일.
- #9: PC에서 단일클릭 → `activate()` → edit mode. `activationConstraint: { distance: 8 }` 덕분에 8px 미만 클릭은 dnd-kit 무시 → 편집 진입 정상.
- #9: `onActivate` (cancelDeselect 호출) — PC에서 `selectionActive=false` 이므로 cancelDeselect 호출돼도 no-op (타이머 없음).

**⚠️ #8 → #9 순서 필수**: #9(단일클릭 편집) 적용 전 #8(선택 시스템 비활성)이 완료되지 않으면, `selectionActive=true` 상태에서 선택되지 않은 게스트의 InlineInput 단일클릭 시 편집 모드와 선택 모드가 동시에 활성화된다. #8 없이 #9만 적용하면 이 상태가 발생하므로 반드시 순서를 지킨다.

---

### E. UX 정리 (⚫ 기능 동등 — 선택 사항)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 10 | `DragOverlay` 게스트 카드 디자인 완성 — 이름 + 파티인원 표시하는 경량 카드 컴포넌트 신규. 드래그 중 그립 행 `opacity-50` 유지 확인. `GuestDragCard` 컴포넌트 신규 또는 인라인 | `RoomAssignment.tsx`, 선택적으로 신규 컴포넌트 파일 | +30 lines |

**동작 동등성**: 시각적 개선만. 이동 로직 영향 없음.

---

## 단계간 의존성

```
1 → 2 (독립, 순서만 권장)
    ↓
    3 → 4 → 5          (B. 골격: 순차 의존)
              ↓
              6 → 7     (C. 연결: 순차 의존)
              ↓
              8 → 9     (D. 분리: 8 후 9)
              ↓
              10        (E. 정리: 독립)
```

- **1,2는 독립** — 어느 순서든 가능. 다른 단계와 병렬 진행 가능.
- **3→4→5 순차** — DndContext 없이 useDraggable 불가. useDraggable 없이 useDroppable 연결 의미 없음.
- **6이 핵심 분기점** — #6 완료 시 PC에서 드래그 이동이 동작. #7~#10은 UX 개선.
- **8→9 순서 필수** — #8 (선택 시스템 비활성) 완료 후 #9 (단일클릭 편집). 순서 어기면 선택 모드 + 편집 모드 동시 활성 충돌 발생.
- **롤백 안전성**: #N 롤백 시 #N-1 상태로 회귀. B 단계(골격) 롤백 시 클릭-선택 시스템이 그대로 동작.

---

## 파일별 변경 요약

| 파일 | 단계 | 변경 내용 |
|------|------|-----------|
| `src/hooks/use-desktop.ts` (신규) | #1 | useIsDesktop — 1024px matchMedia |
| `InlineInput.tsx` | #2, #9 | focus-visible 수정, singleClick prop 추가 |
| `RoomAssignment.tsx` | #3, #6, #7 | DndContext 골격, onDragEnd 구현, onDragStart+blur |
| `GuestRow.tsx` | #4, #8, #9 | useDraggable 연결, onClick 가드, singleClick 전달 |
| `CompactGuestCell.tsx` | #4, #8 | useDraggable 연결 (grip div 직접), isDesktop 가드 (grip onClick 직접) |
| `RoomRow.tsx` | #5 | useDroppable 연결 |
| `GuestZone.tsx` | #5 | useDroppable 연결 (main + next) |

**변경하지 않는 파일**:
- `useGuestMove.ts` — handleDropOnRoom/Pool/Party 전부 유지
- `useGuestSelection.ts` — 모바일에서 그대로 사용
- `useGuestDropTarget.ts` — 모바일에서 그대로 사용 (PC는 selectionActive=false로 자동 비활성)
- `useHoverZone.ts` — 모바일에서 그대로 사용
- Backend 전체 — 변경 없음

---

## 사전조사 문서 템플릿

각 단계별로 `docs/plans/dndkit-step-NN-<slug>.md` 생성. 권장 섹션:

```markdown
# 단계 N: <제목>

## 1. 목적
- (1~2줄)

## 2. 변경 대상 코드
### 2-1. <파일>:<라인범위>
**Before** (현재 코드):
```tsx
<인용>
```
**After** (변경 후):
```tsx
<인용>
```
**변경 의도**: …

(여러 파일/위치 반복)

## 3. 동작 동등성 근거 (또는 의도된 변화 명시)
- 입력 케이스별 비교:
  - 케이스 A (PC): 기존 결과 X → 새 결과 X ✅
  - 케이스 B (모바일): 기존 결과 Y → 새 결과 Y ✅
  - 케이스 C: 기존 결과 Z → 새 결과 W 🔵 (의도된 변화)

## 4. 영향받지 않음을 확인할 코드 경로
- (이 변경이 건드리지 않는 hook / 함수 / 컴포넌트 목록)

## 5. 검증 체크리스트
- [ ] 변경 라인이 사전조사 §2와 정확히 일치
- [ ] PC Chrome — 드래그 동작 수동 확인
- [ ] 모바일 (width < 1024px) — 기존 클릭-선택 시스템 동작 확인
- [ ] 취소 예약 행 — 드래그 불가, 편집 불가 동작 확인
- [ ] TypeScript 빌드 오류 없음 (`npm run build`)
```

---

## 미결 검토 항목 (단계 시작 전 결정 필요)

- [ ] **activationConstraint 값** — `distance: 8`인지 `delay: 200`인지. 터치패드 스크롤 혼동 가능성 확인.
- [ ] **DragOverlay 내용물** (#10) — 이름만 표시 vs. 컴팩트 카드. 디자인 확정 후 #10 진행.
- [ ] **다음날 컬럼 zoneId** — `next-room-N`/`next-pool`/`next-party` 형식 확정. onDragEnd 분기에서 처리.
- [ ] **연박 모달과 dnd-kit 비동기 충돌** — `onDragEnd`는 동기 콜백. `handleDropOnRoom` 내부의 `setMultiNightConfirm`이 dnd-kit 이벤트 사이클 완료 후 정상 실행되는지 #6 사전조사에서 확인 필요.
- [ ] **#5 ref 충돌 확인** — `GuestZone.tsx`의 현재 드롭 div가 `useGuestDropTarget`의 `data-drop-zone`과 `useDroppable`의 `setNodeRef`를 동시에 받아야 함. ref callback 합성 패턴 필요 여부 확인.
- [ ] **컨텍스트 메뉴 + 편집 모드 동시 활성 (기존 버그)** — `useContextMenu`의 `canOpen` 조건이 InlineInput 편집 상태를 체크하지 않음. InlineInput input 요소 바깥 행 영역을 우클릭하면 편집 중에도 컨텍스트 메뉴가 열림. 본 마이그레이션이 도입한 버그가 아니므로 범위에 포함하지 않으나, #8 이후 단일클릭 편집이 활성화되면 편집 진입 빈도가 높아져 체감 빈도 증가 가능. 별도 수정 여부 결정 필요.

---

## 다음 액션

1. 본 분해안 검토 → 합의되면
2. 단계 #1 사전조사 문서 (`dndkit-step-01-useIsDesktop.md`) 작성
3. 검토 후 단계 #1 코드 변경 PR
4. 머지 후 단계 #2 사전조사 문서 작성 … (반복)
