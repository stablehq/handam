# 리팩토링 메모

리팩토링 과정에서 발견된 후속 작업/개선 후보 모음.
실제 처리 시점은 별도로 결정.

각 항목의 **태그**:
- `[삭제]` — 코드/기능 제거 후보
- `[개선]` — 동작/UX 개선 후보
- `[리팩토링]` — 추가 분리/통합 후보
- `[조사]` — 더 알아봐야 할 것

---

## [삭제] 멀티선택 잔여 코드

**배경**: Phase D-2 에서 그립 클릭의 Shift/Ctrl/Meta 멀티선택 로직을 제거하면서 **항상 1명만 선택** 되는 구조로 변경. 다음 영역들은 자동으로 도달 불가능 코드가 됨.

**위치**:
- `frontend/src/pages/RoomAssignment.tsx` — 컨텍스트 메뉴 onDelete 콜백 안의 `targetIds.length > 1` 분기 (게스트 일괄 삭제 다이얼로그 + 일괄 삭제 루프)
- `frontend/src/pages/RoomAssignment.tsx` — QuickMenuBar 의 onDeleteSelected 콜백 안의 `ids.length > 1` 분기 (모바일 일괄 삭제)
- `frontend/src/pages/RoomAssignment.tsx` — 컨텍스트 메뉴 핸들러 (`onGuestContextMenu`) 의 `selectedGuestIds.size > 0 && selectedGuestIds.has(resId) ? [...selectedGuestIds] : ...` — selectedGuestIds 가 0/1 개라 항상 단일 ID
- 컨텍스트 메뉴 액션의 `targetIds.length === 1 ? action : undefined` 가드들 — 항상 length === 1 이므로 가드 자체 불필요

**같이 정리할 자료구조**:
- `selectedGuestIds: Set<number>` → `selectedGuestId: number | null` 로 단순화 가능 (옵션 B)
  - `useGuestSelection` 훅의 반환 타입 변경
  - `targetIds` 변환 로직 (`[...selectedGuestIds]`) 모두 단순 비교로 교체
  - `selectedGuestIds.size`, `selectedGuestIds.has(id)` 모두 직관적인 비교로

**왜 지금 안 함**:
- Phase D-2 의 1단계 원칙 (동작 변경 최소화) 준수
- 회귀 위험 큼 (~30곳 변경)
- 별개 정리 작업으로 분리

**메모일자**: 2026-05-07 (Phase A-2 식별 + Phase D-2 진행 중 확장)

---

## [개선] 커스텀 색상 저장 실패 시 에러 토스트 누락

**위치**:
- `frontend/src/pages/RoomAssignment/hooks/useHighlightColors.ts` 의 `applyCustomColors`
- 원본: `frontend/src/pages/RoomAssignment.tsx` 의 `onSaveCustomColors` 인라인 콜백

**현재 동작**:
```ts
const applyCustomColors = async (colors) => {
  await settingsAPI.updateHighlightColors(colors);  // 실패 시 throw
  setCustomHighlightColors(colors);
  toast.success('커스텀 색상이 저장되었습니다');
};
```

→ API 실패 시 `await` 가 던지면서 ②③ 안 실행됨. 성공 토스트 안 뜨는 건 맞지만 **에러 토스트도 안 뜸**. 사용자는 "왜 저장 안 됐지?" 모름.

**개선안**:
```ts
const applyCustomColors = async (colors) => {
  try {
    await settingsAPI.updateHighlightColors(colors);
    setCustomHighlightColors(colors);
    toast.success('커스텀 색상이 저장되었습니다');
  } catch {
    toast.error('커스텀 색상 저장에 실패했습니다');
  }
};
```

**왜 지금 안 함**: 리팩토링 1단계 원칙(동작 변경 없이 위치만 이동) 준수. 별개 개선 작업으로 분리.

**메모일자**: 2026-05-07 (Phase B-3 진행 중 식별)

---

## [개선] 스테이그룹 작업 후 window.location.reload() 사용

**위치**:
- `frontend/src/pages/RoomAssignment/hooks/useStayGroup.ts` 의 `handleStayGroupComplete` (연박 묶기 완료)
- `frontend/src/pages/RoomAssignment/hooks/useStayGroup.ts` 의 `handleStayGroupUnlink` (연박 해제)

**현재 동작**:
연박 묶기/해제 성공 후 `window.location.reload()` 로 페이지 통째로 새로고침.

**문제**:
- 화면 깜빡임 + 흰 화면
- 모든 JS 다시 로드 (느림)
- 다른 상태(필터, 스크롤 위치 등) 모두 날아감

**개선안**:
- `window.location.reload()` → `refetch()` (= `fetchReservations(selectedDate)`)
- 다만 stay_group_id 변경이 모든 파생 상태(buildingGroups, SMS 스케줄 표시 등)에 안전히 전파되는지 확인 필요

**왜 지금 안 함**:
- 리팩토링 1단계 원칙(동작 변경 없이 위치만 이동) 준수
- 검증 비용이 큼 (연박 데이터의 다양한 케이스 테스트 필요)

**메모일자**: 2026-05-07 (Phase B-4 진행 중 식별)

---

## [리팩토링] useGuestDropTarget 훅 (Phase F 안에서 도입)

**배경**: Phase E-3 으로 계획됐던 작업. 사용처 (zone / room 의 drop 영역) 가 본체 인라인 상태에서 추출하면 절약 2~3줄로 가치 작아 **Phase F 진입 시점으로 미룸**.

**할 일**:
- `frontend/src/pages/RoomAssignment/hooks/useGuestDropTarget.ts` 생성
- 시그니처 (예시): `useGuestDropTarget(zoneId): { isDragOver, dropZoneProps }`
- `dropZoneProps` 에 `data-drop-zone`, `onMouseEnter`, `onMouseLeave` 묶음
- `isDragOver` 는 `useHoverZone` 의 hover 상태와 zoneId 매칭으로 도출

**사용 예상처** (Phase F 시점):
- `<GuestZone>` 공통 골격 안 (4 zone 모두 사용)
- `<RoomRow>` (Phase G) 의 객실 셀 / 다음날 셀

**왜 미뤘나**:
- 사용처 명확해진 시점 (Phase F) 에 시그니처 결정 → 후속 변경 회피
- 지금 본체에서 미리 넣어도 절약 효과 작음

**메모일자**: 2026-05-08 (Phase E 마무리 시 결정)

---

## [리팩토링] handleSubmit 의 폼-백엔드 변환 로직 정리

**위치**: `frontend/src/pages/RoomAssignment/hooks/useReservationForm.ts` 의 `handleSubmit`

**현재 동작**:
모달 폼 입력값을 백엔드 스키마로 변환:
- `male_count + female_count` → `gender` 문자열 + `party_size`
- `multi_night + nights` → `check_out_date` 계산
- `date + time` → `check_in_date + check_in_time` 필드명 매핑
- `guest_type` → `naver_room_type` + `section` 매핑

**개선안**:
폼 자체가 백엔드 스키마를 따르도록 ReservationFormModal 의 입력 필드 구조 자체를 수정하면 변환 로직 사라짐.

**왜 지금 안 함**:
- 모달 컴포넌트의 인풋 인터페이스 전체 재설계 필요 (별도 큰 작업)
- 백엔드 API 와 프론트 코드 모두 변경 → 회귀 위험
- 폼 UX 도 함께 재검토 필요

**메모일자**: 2026-05-08 (Phase H 진행 중 식별)

---

## [향후작업] Phase J — 마무리 + 반응형 도입

**배경**: 리팩토링(A~I) 완료로 RoomAssignment.tsx 3253→1322줄(-59%). 원래 출발점이었던 **17인치 노트북 가로 스크롤** 해결을 포함한 마무리 작업이 남음. 2026-05-08 시점 일정 분리 결정.

### 후보 작업 목록

#### A. 반응형 도입 (원래 목표)

- **A-1. Summary Cards 반응형**
  - 위치: `frontend/src/pages/RoomAssignment/components/SummaryCards.tsx`
  - 현재: `min-w-max` 로 좁은 화면에서 가로 스크롤 / hidden
  - 개선: `min-w-max` 제거 + grid wrap (예: `grid-cols-2 sm:grid-cols-3 lg:grid-cols-5`)

- **A-2. 페이지 헤더 액션 버튼 반응형**
  - 위치: `RoomAssignment.tsx` 상단 PageHeader + 액션 영역
  - 좁은 화면에서 버튼 텍스트 숨기고 아이콘만 표시 (예약자 추가, 테이블 설정, 네이버 동기화 등)

- **A-3. 메인 테이블 반응형** ⚠️ (전략 결정 필요)
  - 컬럼: 객실 / 다음날 / 이름 / 전화 / 파티 / 성별 / 예약객실 / 메모 / 문자
  - 옵션 (a): xl: 미만에서 일부 컬럼 숨기기 — 어떤 컬럼을 숨길지 사전 결정
  - 옵션 (b): 좌측 객실 칼럼 sticky + 가로 스크롤 유지
  - 옵션 (c): 가장 가벼움 — 그냥 둠 (Summary만 정리)
  - **결정 필요**: 어느 옵션으로 갈지 (사용 시나리오 검토 후)

#### B. 마무리 정리 — DELETE.md 잔여 메모 처리

- **B-1. useGuestDropTarget 메모 outdated**
  - 위 [리팩토링] 섹션 메모는 이미 Phase F 에서 구현 완료
  - DELETE.md 의 해당 메모 항목 제거만 하면 됨 (코드 변경 없음)

- **B-2. 커스텀 색상 저장 에러 토스트** (위 [개선] 섹션)
  - `useHighlightColors.ts` `applyCustomColors` 에 try/catch + 에러 토스트 추가
  - 위험도: 낮음

- **B-3. 스테이그룹 `window.location.reload()` 제거** (위 [개선] 섹션)
  - `useStayGroup.ts` 의 `handleStayGroupComplete` / `handleStayGroupUnlink` 에서 reload → refetch 교체
  - 위험도: 중간 (연박 데이터 케이스 검증 필요)

- **B-4. 멀티선택 잔여 코드 정리** (위 [삭제] 섹션, ~30곳)
  - `selectedGuestIds: Set<number>` → `selectedGuestId: number | null` 단순화
  - 위험도: 높음 → **별개 작업으로 분리 권장**

- **B-5. handleSubmit 폼-백엔드 변환 로직 정리** (위 [리팩토링] 섹션)
  - 모달 인풋 인터페이스 전체 재설계 필요
  - 위험도: 매우 높음 → **별개 작업으로 분리 권장**

#### C. 노재원 undo 회귀 진단/수정 ⭐

- **현상**: 게스트 객실 이동 후 Ctrl+Z (또는 되돌리기 버튼) — 토스트는 "되돌리기 성공" 뜨는데 실제로는 안 돌아감
- **의심 후보** (코드 분석 미진행):
  - `useUndoStack.ts:52-102` — `setUndoStack(prev => { ... 비동기 IIFE ... })` 안의 closure 캡처
  - React StrictMode 더블 파이어링 가능성 (updater 두 번 호출)
  - `selectedDate` stale closure (사용자가 undo 직전 날짜 변경 시)
  - 백엔드 API `apply_subsequent` / `apply_group` 전파 누락
  - push_out 케이스의 `pushedOut` 복원 순서 race
- **재현 시나리오 5가지** (모두 실험 필요):
  - 케이스 A: 일반 게스트 미배정→객실
  - 케이스 B: 일반 게스트 객실→객실
  - 케이스 C: 연박 게스트 (multiNightConfirm 동반)
  - 케이스 D: 다음날 컨텍스트
  - 케이스 E: push_out (밀어내기)
- **다음 단계 권장**:
  1. 위 5케이스 직접 재현 → 어느 케이스가 깨지는지 핀포인트
  2. `window.__diagAction` 로깅 + 백엔드 API 응답 확인
  3. 핀포인트 케이스 코드 분석 → 수정

### 추천 진행 범위 (옵션)

| 옵션 | 범위 | 비고 |
|---|---|---|
| 작게 | A-1 + B-1, B-2 | 빠름, 회귀 위험 거의 없음 |
| 중간 | A-1 + A-2 + B-1~B-3 + C | 균형 |
| 크게 | A 전체 + B 대부분 + C | 회귀 위험 큼, 비추 |

### 미결 질문

1. 메인 테이블 반응형 (A-3) — 어느 옵션 (a/b/c) 으로 갈지
2. 노재원 undo (C) — Phase J 안에 포함할지, 별도 트랙으로 분리할지
3. DELETE.md 큰 메모 (B-4, B-5) — 이번에 손댈지, 별개 작업으로 영구 분리할지

**메모일자**: 2026-05-08 (Phase I-3 완료 후, Phase J 진입 직전 일정 분리 결정)
