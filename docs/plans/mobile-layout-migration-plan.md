# 객실배정 모바일 레이아웃 — 단계 분해 계획

> 작성일: 2026-05-20
> 상태: 단계 분해안 검토 대기
> 대상 페이지: `frontend/src/pages/RoomAssignment.tsx` (1321 lines) + 하위 `RoomAssignment/**`

---

## 배경

PC(≥768px) 에서 객실배정 페이지는 안정적으로 동작. 모바일(<768px) 은 같은 가로 매트릭스를 그대로 렌더하여 가로 overflow + 작은 터치 타겟 문제 존재.

**현재 분기 상태** (조사 결과):
- 분기 지점: `useIsMobile()` (`hooks/use-mobile.ts`, 768px 기준)
- 적용 영역: **인터랙션 5곳만** — `useSelectionSystem`(PC noop, 모바일 실제), `QuickMenuBar`(모바일 컨텍스트 버튼), `GuestContextMenu`(hideDelete), `dnd-kit` 드래그(PC만), 단축키 툴팁 표시
- **레이아웃 분기 0건** — `RoomAssignment.tsx` / 하위 컴포넌트 모두 Tailwind `sm:/md:/lg:` 분기 없이 PC 폭 기준 가로 매트릭스로 구성

## 진행 프로세스 (Mutator 방식)

본 마이그레이션은 Mutator/dndkit 마이그레이션과 동일한 프로세스로 진행한다.

```
① 설계안 합의 (현재 단계)
   → 본 분해안 검토 후 단계 분해 확정

② 단계별 순차 진행 (반복)
   1. 해당 단계의 사전조사 문서 작성 (docs/plans/mobile-layout-step-NN-*.md)
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

---

## 원칙

1. **PC(≥768px) 동작 0 변경** — 모든 단계에서 PC 사용자가 인지 가능한 시각/동작 변화 금지. Silent change 도 금지.
2. **모바일 단독 분기** — 모든 변경은 `useIsMobile()` (`<768px`) 안쪽에서만 발효.
3. **각 단계는 별도 PR + 별도 사전조사 문서** — `docs/plans/mobile-layout-step-NN-*.md` 형식.
4. **각 사전조사 문서에 Before/After 코드 인용 + 동작 동등성 근거 명시**.
5. **각 단계는 직전 단계와 독립** — 단계 #N 을 롤백해도 시스템 동작.
6. **세로 순서 유지** — 모바일에서도 PageHeader → SummaryCards → CampaignToolbar → 객실 → Zones 순서.
7. **테이블 → 카드** — 가로 매트릭스 `RoomRow` 가 모바일에서는 카드 한 장으로 치환. 같은 데이터, 다른 배치.

---

## 의도된 동작 변화 (= 변경 대상)

모바일(<768px) 에서만 발효. PC 는 전부 기존 동작 유지.

| 항목 | 기존 모바일 동작 | 변경 후 모바일 동작 |
|------|-----------------|-------------------|
| 객실 한 줄 (RoomRow) | 가로 매트릭스 한 줄 (overflow 발생) | 카드 한 장 (세로 스택) |
| Building 그룹 | PC와 동일 가로 헤더 | 모바일 친화 접기/펴기 헤더 |
| Zones (Unassigned/Party/Unstable/Cancelled) | PC 가로 레이아웃 | 카드 그리드 또는 세로 리스트 |
| SummaryCards | 단일 줄 5컬럼 가정 | `grid-cols-2` 모바일 그리드 |
| CampaignToolbar | PC 가로 툴바 | 모바일 친화 stacked 또는 sheet |

**그 외 동작은 모두 불변** — API 호출, 모달, QuickMenuBar, 컨텍스트 메뉴, 선택 시스템, 단축키, SSE invalidate 등.

---

## 단계 분해 (6개)

각 단계의 **실제 동작 변화 유무**를 명시.
⚪ = 동작 변화 없음 (구조/인프라), 🟡 = 모바일만 변화 (PC 영향 0)

### A. 기초 인프라 (⚪ 동작 변화 없음)

| # | 작업 | 변경 파일 | 코드 변경량 (예상) |
|---|---|---|---|
| **1** | **PC JSX 추출** — `RoomAssignment.tsx` 의 PC 매트릭스 영역(870-1032 line)을 `layouts/DesktopLayout.tsx` 로 분리. modals/QuickMenuBar/GuestContextMenu/DragOverlay/DndContext 는 parent 유지. PC 동작 0 변화. | `RoomAssignment.tsx` (수정), `layouts/DesktopLayout.tsx` (신규) | RoomAssignment.tsx -160줄, DesktopLayout.tsx +170줄 |

### B. 모바일 골격 (🟡 모바일만 변화, PC 0)

| # | 작업 | 변경 파일 | 영향 |
|---|---|---|---|
| **2** | **MobileLayout 빈 골격 + 분기** — `layouts/MobileLayout.tsx` 신규 생성 (PC 와 동일 JSX 복사). `RoomAssignment.tsx` 에서 `isMobile ? <MobileLayout/> : <DesktopLayout/>`. 이 단계 끝에서 모바일 = PC 동일 시각 (가로 매트릭스 그대로). | `RoomAssignment.tsx`, `layouts/MobileLayout.tsx` (신규) | PC: 0 변화. 모바일: 0 변화 (아직 동일 JSX). |

### C. 모바일 컴포넌트 카드화 (🟡 모바일만)

| # | 작업 | 변경 파일 | 영향 |
|---|---|---|---|
| **3** | **MobileRoomCard 신규** — 가로 `RoomRow` 데이터를 카드 한 장으로 렌더. `GuestRow`, `CompactGuestCell`, `SmsCell`, `InlineInput`, `RoomMemoEditor` 등 하위 컴포넌트는 그대로 재사용 (배치만 변경). `MobileLayout` 에서 `RoomRow` 대신 사용. | `components/MobileRoomCard.tsx` (신규), `MobileLayout.tsx` (수정) | PC: 0. 모바일: 객실 영역 카드화. |
| **4** | **MobileZones** — `UnassignedZone`/`PartyZone`/`UnstableZone`/`CancelledZone` 의 모바일 버전 또는 동일 컴포넌트 + responsive prop. 동작은 동일하되 모바일 폭에 맞는 카드 그리드/세로 리스트 배치. | `components/zones/Mobile*Zone.tsx` 또는 기존 zones 에 mobile variant | PC: 0. 모바일: zones 카드화. |
| **5** | **모바일 헤더 영역** — `PageHeader` / `SummaryCards` / `CampaignToolbar` 의 모바일 버전. SummaryCards 는 grid-cols-2, CampaignToolbar 는 stacked. PageHeader 는 폰트/패딩만 조정. | `components/Mobile*.tsx` 또는 기존에 mobile variant | PC: 0. 모바일: 헤더 영역 정리. |

### D. 마무리 (🟡 모바일만)

| # | 작업 | 변경 파일 | 영향 |
|---|---|---|---|
| **6** | **모바일 인터랙션 다듬기 (필요 시)** — bottom sheet 도입 검토, 터치 타겟 ≥44px 보장, 모바일 전용 모달 사이즈 등. 필요한 항목만 선별 진행. | TBD | 모바일만 |

---

## Step #01 의 안전성 근거

Step #01 은 **순수 JSX 이동** 만 한다.
- 상태/hooks/mutations/handlers 는 모두 `RoomAssignment.tsx` 에 그대로 둠
- JSX 만 `DesktopLayout.tsx` 로 옮기고, 필요한 값들을 prop 으로 전달
- DnD/모달/단축키/SSE/컨텍스트 메뉴는 parent 에 그대로 유지
- ref forwarding 정확성 (sticky positioning, 컬럼 리사이즈) 만 시나리오 검증

Step #02 시작 시점에 모바일은 여전히 PC 와 동일한 JSX 를 렌더. **분기만 도입하고, 모바일 코드는 PC 와 1:1 사본**. 이후 단계에서만 모바일 코드를 변경.

---

## 모바일 카드 mockup (Step #03 미리보기)

PC 의 가로 `RoomRow`:
```
[101호 도미토리] [오늘 게스트칸] [다음날 게스트칸] [SMS 칩] [메모]
```

모바일 카드:
```
┌─────────────────────────────┐
│ 101호 · 도미토리 · 4/6명    │  ← 객실 헤더 (이름, 등급, 점유율)
├─────────────────────────────┤
│ 오늘                         │
│ • 홍길동 (1박)               │
│ • 김철수 (2박)               │
├─────────────────────────────┤
│ 내일                         │
│ • 이영희 (신규)              │
├─────────────────────────────┤
│ [SMS칩들]            [메모] │
└─────────────────────────────┘
```

---

## 참고 문서

- 부모 페이지 컴포넌트: `frontend/src/pages/RoomAssignment.tsx`
- 모바일 감지 훅: `frontend/src/hooks/use-mobile.ts` (768px 기준)
- 디자인 가이드: `frontend/CLAUDE.md` (Toss Invest + Flowbite)
- 선행 마이그레이션 형식: `docs/plans/mutator-step-01-mutator-skeleton.md`, `docs/plans/dndkit-migration-plan.md`
