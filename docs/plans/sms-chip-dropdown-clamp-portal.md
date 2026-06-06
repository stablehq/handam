# SmsCell 드롭다운 — 공용 클램프 훅 추출 + body 포탈 전환

> 상태: **적용 완료** (2026-06-06) — 5축 Impact Analysis 통과 (Critical 0 / High 1 → 완화 반영 / 평결 "수정 후 진행" required 6건 전부 반영), `npm run build` (tsc strict + vite) 통과
> 관련: `frontend/src/pages/RoomAssignment/components/SmsCell.tsx`, `frontend/src/hooks/use-clamped-dropdown.ts`

## 1. 배경 / 문제

객실 배정 페이지의 SMS 칩 `+` 버튼 드롭다운(템플릿 체크리스트)이 템플릿 수가 많으면
뷰포트보다 길어져 화면 밖으로 잘림. 잘린 항목 클릭 불가, 메뉴 내부 스크롤 불가,
페이지 스크롤 시 메뉴가 버튼과 분리(detach).

### 원인 (변경 전 코드 기준)

| 위치 (변경 전) | 내용 |
|---|---|
| `SmsCell.tsx:74-82` | flip-only 로직 — `menuRect.bottom > window.innerHeight` 이면 위로 플립만. 양쪽 다 부족하면 잘림 |
| `SmsCell.tsx:173-174` | `fixed z-[60]` + max-height/overflow 없음 → 내부 스크롤 불가 |
| `SmsCell.tsx:173` (inline 렌더) | 메뉴가 행(row)의 DOM 자식 → **2차 버그**: 커스텀 hex 하이라이트 행은 `hover:brightness` filter(`GuestRow.tsx:133`, `MobileGuestRow.tsx:125`)가 행을 fixed containing block 으로 만들어 좌표가 행 기준으로 해석됨 |
| (부재) | scroll/resize 리스너 없음 → detach |
| `SmsCell.tsx:78` | `window.innerHeight` = layout viewport → 핀치줌 시 부정확 |

### 해결 전략 (B안)

`GuestContextMenu.tsx:93-141` 의 검증된 패턴(createPortal + visualViewport 4방향 측정 +
최종 clamp + maxHeight/overflowY)을 공용 훅 `useClampedDropdown` 으로 추출하고,
SmsCell 드롭다운을 이 훅 + body 포탈로 전환.

**범위 제외 (이번 변경에서 건드리지 않음)**:
- `GuestContextMenu.tsx` — 역마이그레이션은 별도 단계로 보류. 보류 사유: 점 anchor 를
  `{ left: position.x, right: position.x, ... }` 객체 리터럴로 매 렌더 재생성하면
  훅 deps 변경 → 재계산 루프 위험 (마이그레이션 시 `useMemo([position.x, position.y])` 필수)
- SmsCell 의 칩 렌더링/dedup 로직 — 무변경
- `SmsCellProps` 인터페이스 — 무변경 (호출부 `GuestRow.tsx:252`, `MobileGuestRow.tsx:361` 영향 없음)

## 2. 변경 파일 (적용 실측)

| 파일 | 종류 | 규모 |
|---|---|---|
| `frontend/src/hooks/use-clamped-dropdown.ts` | 신규 | 146줄 (주석 포함) |
| `frontend/src/pages/RoomAssignment/components/SmsCell.tsx` | 수정 | +31/-26 (git numstat 실측) |

## 3. 신규 훅 — `use-clamped-dropdown.ts`

전문은 실제 파일 참조. 핵심 구조:

- **배치 계산** (`useLayoutEffect`): `GuestContextMenu.tsx:96-138` 과 의미 동등 —
  visualViewport 폴백 → `maxWidth/maxHeight = v크기 − margin×2` → 가로(선호 정렬 → 반대 플립 → clamp) →
  세로(아래 우선 → 위 플립 → 양쪽 부족 시 하단 정렬 + maxHeight 내부 스크롤) → 최종 clamp.
  anchor 는 점이 아닌 사각형(`AnchorRect`, DOMRect 구조 호환) — `align: 'end'` 가 기존 right-anchor 동작 재현.
- **닫기 리스너** (`useEffect`): document scroll capture(내부 스크롤·`ignoreScrollWithinRef` 제외) +
  resize 계열 + Escape. open 직후 300ms 가드 (`useContextMenu.ts:37-38` 동일 패턴).
- **resize 방향 가드** (Impact Analysis High 발견 대응): 뷰포트 높이가 **줄어드는** 방향
  (가상 키보드 오픈, 창 축소)만 닫고 **커지는** 방향(키보드 dismiss, 주소창 수축)은 무시 —
  모바일에서 InlineInput 편집(키보드 업) 직후 `+` 탭 시 키보드 하강 중 vv resize 가
  메뉴를 열리자마자 닫는 플리커 방지. 선례 `useContextMenu` 에는 resize 리스너 자체가 없어
  detach 방지용 신규 동작이므로 방향 가드가 필요했음.
- **호출 규약**: ① portal + 반환 style 적용, ② 측정 전 1프레임은 호출부가
  `{ position:'fixed', top:0, left:0, visibility:'hidden', maxWidth:'calc(100vw - 16px)' }` fallback,
  ③ 열 때마다 anchor 새 참조로 갱신, ④ `onClose` 는 참조 안정(useCallback) 필수.

## 4. SmsCell.tsx — 적용된 변경 (5 hunks)

### Hunk 1 — import
`useCallback`, `createPortal`, `useClampedDropdown`/`AnchorRect` 추가.

### Hunk 2 — state 교체
`dropdownPos` state·`buttonRectRef` 제거 → `anchorRect` state + `closeDropdown`(useCallback) +
훅 호출(`align:'end'`, `onClose`, `ignoreScrollWithinRef: scrollRef`).
주석 근거 (5축 검증으로 교정됨): 칩 스트립(scrollRef)의 **사용자 가로 스와이프**, 그리고
**칩 추가/제거로 콘텐츠 폭이 변할 때 브라우저의 scrollLeft 자동 클램프가 발화시키는 네이티브
scroll 이벤트**를 닫기 트리거에서 제외 (JS 보정 코드는 존재하지 않음 — grep 0건 실측).

### Hunk 3 — outside-click 보강 + 구 flip effect 삭제
mousedown 핸들러가 `dropdownRef`(버튼 영역) ∪ `dropdownMenuRef`(포탈 메뉴) 둘 다 내부로 취급
(포탈 분리로 인한 고전적 contains 버그 방지). 구 flip-only effect(L73-82) 통째 삭제.

### Hunk 4 — 버튼 onClick
`templateLabels.length === 0` 이면 열기 차단 (0개 상태로 열어둔 채 데이터 도착 시
fallback `visibility:hidden` 영구 비표시 엣지 제거 — 축 A Low 발견 채택).
열 때마다 `setAnchorRect(getBoundingClientRect())` — 새 참조가 훅 재계산 트리거.

### Hunk 5 — body 포탈 렌더
`createPortal(<div …>, document.body)`. 변경 클래스:
`fixed z-[60]` → `z-[10000]`(포탈 메뉴 패밀리: GuestContextMenu 10000/팔레트 10001/TableSettings 10100) +
`overflow-y-auto overscroll-contain scrollbar-thin`(Firefox 기본 스크롤바 폭 잠식 완화 — 축 E 채택).
`data-interactive=""` 부여 — 행 long-press 가드 셀렉터(`GuestRow.tsx:148`, `MobileGuestRow.tsx:147`) 대상.
항목 JSX 무변경.

## 5. 동작 동등성 — 시나리오 비교표 (5축 검증 완료)

| # | 시나리오 | Before | After | 판정 |
|---|---|---|---|---|
| 1 | 아래 공간 충분 | 버튼 아래 우측정렬 오픈 | 동일 (`anchor.bottom+gap`, `left = right−w`) | 동등¹ |
| 2 | 아래 부족, 위 충분 | 위로 플립 | 위로 플립 — 동일 기하 (축 A 검산) | 동등 |
| 3 | **양쪽 모두 부족 (버그 케이스)** | 위로 플립 후 상단 잘림, 도달 불가 | 하단 정렬 + `maxHeight` → 내부 스크롤로 전 항목 도달 | **수정** |
| 4 | 메뉴 연 채 페이지 스크롤 | detach | 가드(300ms) 만료 후 첫 scroll 이벤트에서 닫힘. 가드 내 종료된 단발 스크롤은 무시되어 잠시 detach 잔존 (`useContextMenu` 동일 한계 — 후속 스크롤/외부클릭/Escape 로 닫힘) | **의도된 변화** |
| 5 | 메뉴에서 칩 멀티 토글 | 메뉴 유지 | 유지 — mousedown 은 menuRef 내부, 스트립 폭 변화 시 브라우저 scrollLeft 자동 클램프가 발화하는 scroll 은 `ignoreScrollWithinRef` 로 무시 | 동등 |
| 6 | 커스텀 hex 행에서 오픈 (hover 중) | filter containing block → 좌표 깨짐 | body 포탈이라 무관 | **수정** |
| 7 | 발송완료 항목 클릭 | 해제 불가 | 동일 (로직 무변경) | 동등 |
| 8 | 외부 클릭 닫기 | `dropdownRef.contains` | `dropdownRef ∪ dropdownMenuRef` | 동등 |
| 9 | Escape | 무반응 | 닫힘 (GuestContextMenu 패리티) | 개선 |
| 10 | 메뉴 비버튼 영역 long-press (모바일) | 행 long-press 타이머 발동 가능 | `data-interactive` 가드로 차단 | 개선 |
| 11 | 핀치줌 상태 | layout viewport 기준 → 잘림 | visualViewport 기준 | 개선 |
| 12 | 셀 A 메뉴 연 채 셀 B `+` 클릭 | A 닫히고 B 열림 | 동일 | 동등 |
| 13 | 그립 드래그 (dnd-kit) | 무관 (`RoomAssignment.tsx:171-178` Mouse/TouchSensor, grip 전용 listeners) | 무관 | 동등 |
| 14 | `templateLabels` 0개 | 버튼 토글만 (유령 open state) | 열기 자체 차단 | 개선 |
| 15 | 메뉴 연 채 SSE 로 행 unmount | 메뉴 함께 unmount | 포탈 unmount + 전 리스너 cleanup | 동등 |
| 16 | **Escape 비계층 동시 닫힘** | — | InlineInput 편집 중(`InlineInput.tsx` Escape 분기는 stopPropagation 없음)·모달·GuestContextMenu 와 동시 발화 시 함께 닫힘 — **의도된 동작**. 계층적 닫기는 별도 단계 (InlineInput Escape stopPropagation 추가 시 `useGuestSelection` Escape 선택해제 영향 사전조사 필요) | 의도됨 |
| 17 | **모바일 키보드 dismiss 직후 `+` 탭** | (해당 없음 — resize 미감지) | 키보드 하강 중 vv resize 는 vHeight **증가** 방향 → 방향 가드가 무시 → 플리커 없음. 키보드-업 높이 기준 stale 클램프는 §6 한계 참조 | 완화됨 (High 대응) |
| 18 | 메뉴 연 채 편집 진입 (키보드 오픈) | 키보드 위 detach 잔존 | vHeight **감소** 방향 → 닫힘 | 개선 |
| 19 | 메뉴 호버 중 행 hover 스타일 | 행 hover 유지 | body 포탈로 `:hover`/`group-hover` 단절 → 행 hover 해제 (GuestContextMenu 패리티) | 코스메틱 변화 |

¹ 신규 `margin=8` 로 화면 가장자리 8px 여백 강제 — GuestContextMenu 와 동일, 실해 없음.

## 6. 사이드이펙트 점검 (5축 실증 근거)

| 항목 | 근거 | 판정 |
|---|---|---|
| React 포탈 이벤트 버블링 | 포탈 자식의 합성 이벤트는 React 트리를 따라 전파 → 행 `onClick`/`onTouchStart` 가드 경로 전/후 동일 (축 C: 행 핸들러 5종 × 메뉴 상호작용 3종 전수 통과) | 영향 없음 |
| 행 long-press 가드 | 가드 셀렉터에 `[data-interactive]` 포함 — 메뉴 전체 가드 | 개선 |
| document 레벨 외부 리스너 | 축 C: addEventListener 전수 15곳 중 판정 변화 1곳 = SmsCell 자신의 mousedown (Hunk 3 이 정확히 보강). `useContextMenu` 의 click(L40)·**scroll capture(L41)·keydown(L39)** 포함 — SMS 메뉴 내부 스크롤이 동시 열린 컨텍스트메뉴를 닫는 조합은 by-design | 영향 없음 |
| z-index 60 → 10000 | 포탈 메뉴 패밀리와 정렬 (실측: GuestContextMenu 10000, 팔레트 10001, TableSettings 10100, 툴팁 60, 백드롭 55, QuickMenuBar/모달 50) | 의도됨 |
| 드롭존 클릭 가드 (보너스) | 포탈(DOM 조상 단절) + `data-interactive` 로 `useGuestMove` `onDropZoneClick` 의 `closest('[data-drop-zone]')` 오인 경로 이중 차단 (축 A·B 합치) | 개선 |
| backend / API / DB | 변경 없음 (순수 프론트 UI) | 영향 없음 |

### 인지된 한계 (수용, 비차단)

| 한계 | 비고 |
|---|---|
| 모바일 스크롤바 미표시 | `index.css:223` coarse pointer 스크롤바 숨김 → 클램프된 메뉴에 스크롤 단서 없음 (동작은 정상) |
| 데스크탑 클램프 시 스크롤바 폭 잠식 → `w-max` 줄바꿈 | `scrollbar-thin` 으로 완화. 짧은 한글 라벨 기준 발생 확률·외관 손상 경미 |
| 메뉴 연 채 background refetch 로 '발송완료' 뱃지 등장 | 메뉴 폭이 우측으로 성장해 잘릴 수 있음 (Before 는 right 앵커라 좌측 성장 — 국소 차이). 재오픈으로 회복. 필요 시 ResizeObserver 재클램프 후속 |
| PC 에서 메뉴 토글로 스트립 폭 변동 → `+` 버튼 수평 이동 | 메뉴 미추적 — Before 와 동등한 기존 한계 (비스크롤 reflow 계열의 가장 흔한 실사례) |
| scroll-close 직후 탭의 click-through | 메뉴 unmount 순간 그 위치 탭이 밑의 행에 떨어질 수 있음 — GuestContextMenu 와 동일 trade-off. 문제 보고 시 close 후 ~300ms 클릭 swallow 검토 |
| `overscroll-contain` 은 iOS 16+ | 미만 버전은 스크롤 체이닝 → scroll-close 로 수렴 (메뉴가 닫힐 뿐 오동작 아님) |
| 핀치줌 시 측정(fallback, layout viewport)-최종(visualViewport) maxWidth 불일치 | 극단 핀치줌에서 줄바꿈으로 측정 높이 초과 가능 (내부 스크롤로 도달은 보장) — GuestContextMenu 동일 계열 한계, 패리티 유지 |
| 키보드-업 상태에서 연 메뉴의 stale 클램프 | 방향 가드가 dismiss resize 를 무시하므로 키보드-업 기준 maxHeight 잔존 — 재오픈으로 회복 |
| 비스크롤 reflow (SSE 행 재정렬 등) | 버튼 이동해도 메뉴 위치 유지 — GuestContextMenu 동일, scroll-close 가 대부분 커버 |

## 7. 훅 안정성 (축 A 실증)

- `useLayoutEffect` deps 전부 원시값/안정 참조 — 무한 루프 없음 (SmsCell 경로는 `anchorRect` 가 state). StrictMode 이중 실행 안전 (멱등 측정 + 대칭 등록/해제)
- 닫힘 전환 직후 1회 렌더 후 안정화 (이후 `null→null` 은 `Object.is` bail-out)
- close 리스너는 open 당 1회 등록 (deps 전부 안정 참조), cleanup 대칭
- 측정 1프레임: 포탈 ref 는 layout effect 전에 attach → paint 전 setStyle → 깜빡임 없음
- RefObject variance·DOMRect 구조 호환·CSSProperties 리터럴 — strict tsc 실증 (exit 0)

## 8. 검증 기록

1. ✅ Impact Analysis 워크플로 1차+2차 (5축: 훅 수학/diff 정합/이벤트 흐름/시나리오/스타일·스택 + 적대적 통합 평결) — Critical 0 / High 1(완화 반영) / 평결 "수정 후 진행" required 6건 전부 반영
2. ✅ 축 A 가 변경안을 임시 적용해 `npx tsc --noEmit` 사전 실증 (strict, exit 0)
3. ✅ 적용 후 `npm run build` (tsc + vite) 통과 — 2026-06-06
4. ⏳ 수동 시나리오: PC/모바일 × {일반 행, 색칠 행, 화면 하단 행} × {짧은 목록, 긴 목록(뷰포트 초과)} — 운영 확인 대기
