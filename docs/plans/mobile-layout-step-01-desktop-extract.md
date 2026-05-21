# Mobile Layout Step #01 — PC JSX 추출 (DesktopLayout 분리)

> 작성일: 2026-05-20
> 상태: 사전조사 검토 대기
> 부모 plan: [mobile-layout-migration-plan.md](./mobile-layout-migration-plan.md)
> 동작 변화: **없음** (순수 JSX 이동, ⚪)

---

## 목표

`RoomAssignment.tsx` 의 return 안 JSX 중 **PC 매트릭스 영역(line 870~1032)** 을 `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` 로 추출.

- 상태/hooks/mutations/handlers 는 **모두 parent 에 유지**
- 모달/QuickMenuBar/GuestContextMenu/DragOverlay/DndContext 도 **parent 유지** (모바일과 공유될 예정이라)
- DesktopLayout 은 받은 prop 만 사용하는 **stateless presentational** 컴포넌트

---

## 원칙 (Mutator 방식)

1. **PC 사용자 인지 가능한 변화 0** — 시각/동작/순서/포커스/스크롤 모두 동일
2. **JSX 변경 금지** — 줄바꿈/공백 외에는 1:1 이동
3. **prop 명세는 노출이 명확** — 25개 내외 prop 을 인터페이스로 명시 (Context 도입은 Step #02 이후 검토)
4. **ref 동일 인스턴스 보장** — `dateHeaderRef`, `tableContainerRef`, `campaignDropdownRef`, `mobileContextBtnRef` 모두 parent 에서 생성 → prop 으로 전달 → 동일 DOM 참조

---

## 현재 구조 (확인된 사실)

`RoomAssignment.tsx` 1321 lines, return JSX 는 line 863~1318.

### JSX 구조 트리 (확인된 라인)

```
return (                                             // 863
  <DndContext>                                       // 864-869  (parent 유지)
    <div className="space-y-4 pb-14 min-w-0 ...">    // 870  ★ MAIN WRAPPER (parent 유지)

      ─── 추출 대상 (DesktopLayout) ─────────────────
      <PageHeader />                                 // 872
      <SummaryCards summary hasUnstable />           // 874
      <CampaignToolbar ... />                        // 876-890
      <div className="section-card !overflow-visible w-max min-w-full">  // 893
        <div ref={dateHeaderRef} className="sticky top-0 z-20">          // 895
          <div className="section-header justify-center ...">            // 896
            ...Date nav (ChevronLeft/Right + TextInput)                  // 897-918
          </div>
        </div>                                                            // 920
        <div className="section-body !pt-2">                              // 922
          <div key={selectedDate.format} animation>                       // 923
            <div ref={tableContainerRef} className="relative rounded-xl ...">  // 934
              {resizeGuideX !== null && <div .../>}                       // 935-937
              ...Column header (sticky)                                   // 939-981
              <div className={loading ? 'pointer-events-none' : ''}       // 986
                   onContextMenu={...}>
                {buildingGroups.map(group =>                              // 989
                  <BuildingGroup ... renderRoomRow={renderRoomRow} />     // 993-1001
                )}
              </div>                                                       // 1004
              <UnassignedZone ... {...sharedZoneProps} />                 // 1006-1010
              <PartyZone     ... {...sharedZoneProps} />                  // 1012-1016
              <UnstableZone  ... {...sharedZoneProps} />                  // 1018-1022
              <CancelledZone ... {...sharedZoneProps} />                  // 1024-1028
            </div>                                                         // 1029
          </div>                                                           // 1030
        </div>                                                             // 1031
      </div>                                                               // 1032
      ─── 추출 끝 ───────────────────────────────────

      ─── parent 유지 (모달 + 메뉴) ─────────────────
      <ReservationFormModal ... />                   // 1035-1043
      <QuickMenuBar isMobile selectionActive ... />  // 1045-1098
      <ConfirmDialog ... />                          // 1100-1103
      <MultiNightConfirmModal ... />                 // 1105-1108
      <SendConfirmModal ... />                       // 1110-1120
      <style>{...keyframes...}</style>               // 1122-1134  (slideLeft/Right)
      <AutoAssignConfirmModal ... />                 // 1136-1142
      <TableSettingsModal ... />                     // 1145-1203
      <StayGroupChainModal ... />                    // 1205-1218
      <ExtendStayConflictModal ... />                // 1220-1242
      <DateChangeModal ... />                        // 1244-1265
      {contextMenu && contextMenuActions && (        // 1267-1305
        <>
          <div className="fixed inset-0 z-[55]" .../>
          <GuestContextMenu ... />
        </>
      )}
    </div>                                            // 1306  end main wrapper
    <DragOverlay>                                     // 1307-1316  (parent 유지)
      {activeResId !== null ? ... : null}
    </DragOverlay>
  </DndContext>                                       // 1317
);
```

---

## Before / After 코드 인용

### Before (RoomAssignment.tsx, line 863-1318)

```tsx
return (
  <DndContext
    sensors={sensors}
    onDragStart={handleDragStart}
    onDragEnd={handleDragEnd}
    onDragCancel={handleDragCancel}
  >
  <div className={`space-y-4 pb-14 min-w-0 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

    <PageHeader />

    <SummaryCards summary={summary} hasUnstable={hasUnstable} />

    <CampaignToolbar
      templateLabels={templateLabels}
      selectedTemplateKey={selectedTemplateKey}
      ... (총 12개 prop)
    />

    {/* Main grid card */}
    <div className="section-card !overflow-visible w-max min-w-full">
      {/* Date navigation header — sticky */}
      <div ref={dateHeaderRef} className="sticky top-0 z-20">
        ...Date nav (ChevronLeft/Right + TextInput)
      </div>

      <div className="section-body !pt-2">
        <div key={selectedDate.format('YYYY-MM-DD')}
             className={animDirection === 'left' ? 'date-slide-left'
                      : animDirection === 'right' ? 'date-slide-right' : ''}>
          {/* Unified Table */}
          <div ref={tableContainerRef} className="relative rounded-xl ...">
            {resizeGuideX !== null && <div .../>}
            {/* Header */}
            <div className="flex items-center h-10 ... sticky z-[19]" style={{ top: dateHeaderH }}>
              ...Column header
            </div>

            {/* Room Rows */}
            <div className={loading ? 'pointer-events-none' : ''} onContextMenu={...}>
              {(() => {
                let rowIdx = 0;
                return buildingGroups.map((group) => {
                  const startIdx = rowIdx;
                  rowIdx += group.entries.length;
                  return (
                    <BuildingGroup
                      key={`building-${group.building_id ?? 'none'}`}
                      group={group}
                      isCollapsed={collapsedBuildings.has(group.building_id)}
                      onToggle={toggleBuildingCollapse}
                      startRowIndex={startIdx}
                      renderRoomRow={renderRoomRow}
                    />
                  );
                });
              })()}
            </div>

            <UnassignedZone guests={unassigned} nextDayGuests={nextDayUnassigned} {...sharedZoneProps} />
            <PartyZone     guests={partyOnly}   nextDayGuests={nextDayPartyOnly}  {...sharedZoneProps} />
            <UnstableZone  guests={unstableGuests} nextDayGuests={[]}             {...sharedZoneProps} />
            <CancelledZone guests={cancelledGuests} nextDayGuests={[]}            {...sharedZoneProps} />
          </div>
        </div>
      </div>
    </div>

    {/* Guest Form Modal */}
    <ReservationFormModal ... />
    <QuickMenuBar ... />
    <ConfirmDialog ... />
    ... (총 10개 모달/메뉴)
    {contextMenu && contextMenuActions && (...)}
  </div>
    <DragOverlay>...</DragOverlay>
  </DndContext>
);
```

### After (RoomAssignment.tsx, line 863 부근)

```tsx
return (
  <DndContext
    sensors={sensors}
    onDragStart={handleDragStart}
    onDragEnd={handleDragEnd}
    onDragCancel={handleDragCancel}
  >
  <div className={`space-y-4 pb-14 min-w-0 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

    <DesktopLayout
      // SummaryCards
      summary={summary}
      hasUnstable={hasUnstable}
      // CampaignToolbar
      templateLabels={templateLabels}
      selectedTemplateKey={selectedTemplateKey}
      setSelectedTemplateKey={setSelectedTemplateKey}
      campaignDropdownOpen={campaignDropdownOpen}
      setCampaignDropdownOpen={setCampaignDropdownOpen}
      campaignDropdownRef={campaignDropdownRef}
      targets={targets}
      clearTargets={clearTargets}
      sending={sending}
      loadTargets={loadTargets}
      requestSendCampaign={requestSendCampaign}
      onOpenTableSettings={() => setTableSettingsOpen(true)}
      onAddPartyGuest={handleAddPartyGuest}
      // Date nav
      selectedDate={selectedDate}
      setSelectedDate={setSelectedDate}
      navigateDate={navigateDate}
      animDirection={animDirection}
      // Column resize / sticky
      dateHeaderRef={dateHeaderRef}
      tableContainerRef={tableContainerRef}
      dateHeaderH={dateHeaderH}
      resizeGuideX={resizeGuideX}
      startResize={startResize}
      colWidths={colWidths}
      GUEST_COLS={GUEST_COLS}
      NEXT_GUEST_COLS={NEXT_GUEST_COLS}
      NEXT_DAY_EXPANDED_WIDTH={NEXT_DAY_EXPANDED_WIDTH}
      nextDayExpanded={nextDayExpanded}
      setNextDayExpanded={setNextDayExpanded}
      // BuildingGroup loop
      buildingGroups={buildingGroups}
      collapsedBuildings={collapsedBuildings}
      toggleBuildingCollapse={toggleBuildingCollapse}
      renderRoomRow={renderRoomRow}
      loading={loading}
      // Zones
      unassigned={unassigned}
      nextDayUnassigned={nextDayUnassigned}
      partyOnly={partyOnly}
      nextDayPartyOnly={nextDayPartyOnly}
      unstableGuests={unstableGuests}
      cancelledGuests={cancelledGuests}
      sharedZoneProps={sharedZoneProps}
    />

    {/* 모달/메뉴는 그대로 parent 에 유지 */}
    <ReservationFormModal ... />
    <QuickMenuBar ... />
    <ConfirmDialog ... />
    <MultiNightConfirmModal ... />
    <SendConfirmModal ... />
    <style>{`...keyframes...`}</style>
    <AutoAssignConfirmModal ... />
    <TableSettingsModal ... />
    <StayGroupChainModal ... />
    <ExtendStayConflictModal ... />
    <DateChangeModal ... />
    {contextMenu && contextMenuActions && (
      <>
        <div className="fixed inset-0 z-[55]" .../>
        <GuestContextMenu ... />
      </>
    )}
  </div>
    <DragOverlay>...</DragOverlay>
  </DndContext>
);
```

### After (DesktopLayout.tsx, 신규)

```tsx
// frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import dayjs, { Dayjs } from 'dayjs';
import { TextInput } from '@/components/ui/input';
import { PageHeader } from '../components/PageHeader';
import { SummaryCards } from '../components/SummaryCards';
import { CampaignToolbar } from '../components/CampaignToolbar';
import { BuildingGroup } from '../components/BuildingGroup';
import { UnassignedZone } from '../components/zones/UnassignedZone';
import { PartyZone } from '../components/zones/PartyZone';
import { UnstableZone } from '../components/zones/UnstableZone';
import { CancelledZone } from '../components/zones/CancelledZone';
import type { RoomEntry } from '../components/RoomRow';
import type { Reservation } from '../types';

interface DesktopLayoutProps {
  // SummaryCards
  summary: ReturnType<typeof useMemoSummary>;  // 또는 inline 타입
  hasUnstable: boolean;
  // CampaignToolbar (12)
  templateLabels, selectedTemplateKey, setSelectedTemplateKey,
  campaignDropdownOpen, setCampaignDropdownOpen, campaignDropdownRef,
  targets, clearTargets, sending,
  loadTargets, requestSendCampaign,
  onOpenTableSettings, onAddPartyGuest,
  // Date nav (4)
  selectedDate, setSelectedDate, navigateDate, animDirection,
  // Column resize / sticky (10)
  dateHeaderRef, tableContainerRef, dateHeaderH, resizeGuideX, startResize,
  colWidths, GUEST_COLS, NEXT_GUEST_COLS, NEXT_DAY_EXPANDED_WIDTH,
  nextDayExpanded, setNextDayExpanded,
  // BuildingGroup loop (5)
  buildingGroups, collapsedBuildings, toggleBuildingCollapse, renderRoomRow, loading,
  // Zones (7)
  unassigned, nextDayUnassigned, partyOnly, nextDayPartyOnly,
  unstableGuests, cancelledGuests, sharedZoneProps,
}

export function DesktopLayout(props: DesktopLayoutProps) {
  return (
    <>
      <PageHeader />
      <SummaryCards summary={props.summary} hasUnstable={props.hasUnstable} />
      <CampaignToolbar ... />
      <div className="section-card !overflow-visible w-max min-w-full">
        <div ref={props.dateHeaderRef} className="sticky top-0 z-20">
          ...  {/* Date nav — 원본 line 896-919 와 1:1 동일 */}
        </div>
        <div className="section-body !pt-2">
          <div key={...} className={animDirection === 'left' ? 'date-slide-left' : ...}>
            <div ref={props.tableContainerRef} className="relative rounded-xl ...">
              {props.resizeGuideX !== null && <div .../>}
              <div className="flex items-center h-10 ... sticky z-[19]" style={{ top: props.dateHeaderH }}>
                ... {/* Column header — 원본 line 939-981 와 1:1 동일 */}
              </div>
              <div className={props.loading ? 'pointer-events-none' : ''} onContextMenu={...}>
                {(() => {
                  let rowIdx = 0;
                  return props.buildingGroups.map((group) => {
                    const startIdx = rowIdx;
                    rowIdx += group.entries.length;
                    return <BuildingGroup ... />;
                  });
                })()}
              </div>
              <UnassignedZone guests={props.unassigned} ... />
              <PartyZone ... />
              <UnstableZone ... />
              <CancelledZone ... />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
```

---

## Props 인터페이스 명세 (총 41 props)

> ★ 이 표는 라인 단위 검증의 핵심. 빠진 prop 이 있으면 PC 가 깨짐.

| # | Prop | 타입 | 출처 (line) | 용도 |
|---|------|------|------------|------|
| **SummaryCards (2)** | | | | |
| 1 | `summary` | `Summary` (useMemo, line 801-861) | 본체 | 통계 |
| 2 | `hasUnstable` | `boolean` | 82 | unstable 카드 노출 |
| **CampaignToolbar (12)** | | | | |
| 3 | `templateLabels` | `Record<string,string>` | useReservationsData | 템플릿 목록 |
| 4 | `selectedTemplateKey` | `string` | useCampaignSend 451 | 선택 템플릿 |
| 5 | `setSelectedTemplateKey` | `(k:string)=>void` | useCampaignSend | 선택 변경 |
| 6 | `campaignDropdownOpen` | `boolean` | useCampaignSend | 드롭다운 open |
| 7 | `setCampaignDropdownOpen` | `(b:boolean)=>void` | useCampaignSend | 드롭다운 토글 |
| 8 | `campaignDropdownRef` | `RefObject<HTMLElement>` | useCampaignSend | 드롭다운 ref |
| 9 | `targets` | `number[]` | useCampaignSend | 캠페인 대상 |
| 10 | `clearTargets` | `()=>void` | useCampaignSend | 대상 초기화 |
| 11 | `sending` | `boolean` | useCampaignSend | 전송 중 |
| 12 | `loadTargets` | `()=>void` | useCampaignSend | 대상 로드 |
| 13 | `requestSendCampaign` | `()=>void` | useCampaignSend | 발송 요청 |
| 14 | `onOpenTableSettings` | `()=>void` | inline | 설정 모달 |
| 15 | `onAddPartyGuest` | `()=>void` | useReservationForm 207 | 파티 추가 |
| **Date nav (4)** | | | | |
| 16 | `selectedDate` | `Dayjs` | useState 85 | 현재 날짜 |
| 17 | `setSelectedDate` | `(d:Dayjs)=>void` | useState 85 | 날짜 설정 |
| 18 | `navigateDate` | `(dir)=>Promise<void>` | useCallback 756 | prev/next |
| 19 | `animDirection` | `'none'|'left'|'right'` | useState 170 | 슬라이드 |
| **Column resize / sticky (10)** | | | | |
| 20 | `dateHeaderRef` | `RefObject<HTMLDivElement>` | useColumnResize 447 | sticky ref |
| 21 | `tableContainerRef` | `RefObject<HTMLDivElement>` | useColumnResize 446 | 컨테이너 ref |
| 22 | `dateHeaderH` | `number` | useColumnResize 442 | sticky top |
| 23 | `resizeGuideX` | `number\|null` | useColumnResize 441 | 리사이즈 가이드 |
| 24 | `startResize` | function | useColumnResize 448 | 컬럼 리사이즈 시작 |
| 25 | `colWidths` | `Record<col,number>` | useColumnResize 440 | 컬럼 폭 |
| 26 | `GUEST_COLS` | `string` | useColumnResize 443 | grid-template-columns |
| 27 | `NEXT_GUEST_COLS` | `string` | useColumnResize 444 | 다음날 grid |
| 28 | `NEXT_DAY_EXPANDED_WIDTH` | `number` | useColumnResize 445 | 확장 폭 |
| 29 | `nextDayExpanded` | `boolean` | useState 164 | 펼침 여부 |
| 30 | `setNextDayExpanded` | `(b:boolean)=>void` | useState 164 | 펼침 토글 |
| **BuildingGroup loop (5)** | | | | |
| 31 | `buildingGroups` | array | useReservationsData | 건물 그룹 |
| 32 | `collapsedBuildings` | `Set<number\|null>` | useCollapsibleBuildings 199 | 접힘 상태 |
| 33 | `toggleBuildingCollapse` | function | useCollapsibleBuildings 199 | 접기 토글 |
| 34 | `renderRoomRow` | `(entry, rowIndex)=>JSX` | inline 733 | 객실 행 렌더 |
| 35 | `loading` | `boolean` | useReservationsData | 로딩 |
| **Zones (7)** | | | | |
| 36 | `unassigned` | `Reservation[]` | useMemo 506 | 미배정 |
| 37 | `nextDayUnassigned` | `Reservation[]` | useReservationsData | 다음날 미배정 |
| 38 | `partyOnly` | `Reservation[]` | useMemo 507 | 파티만 |
| 39 | `nextDayPartyOnly` | `Reservation[]` | useReservationsData | 다음날 파티 |
| 40 | `unstableGuests` | `Reservation[]` | useReservationsData | unstable |
| 41 | `cancelledGuests` | `Reservation[]` | useReservationsData | 취소 |
| 42 | `sharedZoneProps` | object (10 fields) | inline 721 | 4 zones 공통 |

> 실제 41개 + sharedZoneProps 1개 = 42개. 향후 Step #02 에서 동일 인터페이스를 MobileLayout 도 받게 됨 (분기점에서 공유).

---

## 동작 동등성 증명

### 1) JSX 트리 동일성
- Before/After 의 JSX 노드 순서, className, key, props 모두 1:1 일치
- 줄바꿈/들여쓰기 외 변경 없음
- 추출 후 DesktopLayout 은 Fragment `<>...</>` 로 감싸므로 추가 DOM 노드 없음

### 2) Ref 동일 인스턴스 보장
- `dateHeaderRef`, `tableContainerRef`, `campaignDropdownRef`, `mobileContextBtnRef` 는 모두 parent 의 hook 에서 `useRef()` 로 생성 → prop 으로 전달 → DesktopLayout 안에서 `<div ref={props.xxx}>` 로 부착
- 동일한 ref 객체이므로 `.current` 가 동일 DOM 을 가리킴
- ResizeObserver / IntersectionObserver / sticky positioning 모두 동일 DOM 기준

### 3) Sticky / Z-index 보존
- `<div ref={dateHeaderRef} className="sticky top-0 z-20">` → DesktopLayout 안의 동일 className 유지
- `<div className="... sticky z-[19]" style={{ top: dateHeaderH }}>` → 동일
- DesktopLayout 이 Fragment 라서 sticky 계산 기준 (containing block) 이 변하지 않음 ★

### 4) DnD / 모달 / 단축키 / SSE / 컨텍스트 메뉴 — parent 유지
- DndContext 는 parent 의 outer wrapper. DesktopLayout 내부의 `useDraggable`/`useDroppable` 호출은 동일 context 를 본다 (React context 는 트리 위로 lookup).
- 모달 7종 + QuickMenuBar + GuestContextMenu + DragOverlay 모두 parent JSX 에 남음
- `useEffect` (Ctrl+Z 단축키, SSE invalidator, clearTargets on date change, body keyboard) 모두 parent 에 남음

### 5) Closure 동일성
- `renderRoomRow` (line 733), `renderCompactCell` (702), `renderGuestRow` (710), `sharedRowProps` (690), `sharedNextProps` (697), `sharedZoneProps` (721) 모두 parent 에서 정의 → prop 으로 전달
- 따라서 같은 closure 가 같은 데이터를 본다

---

## 시나리오 비교 (검증 포인트)

| # | 시나리오 | Before 동작 | After 동작 | 차이 | 검증 방법 |
|---|---------|-----------|------------|------|----------|
| 1 | 페이지 첫 로드 (PC) | matrix + zones 렌더 | 동일 | 없음 | 시각 비교 |
| 2 | 게스트 그립 드래그 → 빈 객실 드롭 | onDragEnd → handleDropOnRoom | 동일 | 없음 | E2E |
| 3 | 게스트 드래그 → UnassignedZone 드롭 | onDropZoneClick (zone) | 동일 | 없음 | E2E |
| 4 | 게스트 드래그 → 다음날 칸 드롭 | handleDropOnZoneCrossDay | 동일 | 없음 | E2E |
| 5 | 인라인 편집 (이름/전화/...) | InlineInput → handleFieldSave | 동일 | 없음 | E2E |
| 6 | SMS 칩 토글 | useSmsAssignment | 동일 | 없음 | E2E |
| 7 | 우클릭 컨텍스트 메뉴 | onGuestContextMenu | 동일 | 없음 | E2E |
| 8 | 모달 7종 열기/닫기 | parent state | 동일 | 없음 | E2E |
| 9 | Ctrl+Z 되돌리기 | useEffect (parent) | 동일 | 없음 | E2E |
| 10 | 날짜 ← → 네비게이션 | navigateDate + slideLeft/Right | 동일 (애니메이션 keyframe 도 parent의 `<style>` 유지) | 없음 | 시각 |
| 11 | 다음날 컬럼 펼침/접힘 | setNextDayExpanded | 동일 | 없음 | E2E |
| 12 | 컬럼 폭 리사이즈 | useColumnResize 의 startResize | 동일 (ref 동일) | 없음 ★ | E2E |
| 13 | sticky 헤더 (스크롤 시) | dateHeaderRef sticky | 동일 (Fragment containing block 보존) | 없음 ★ | 시각 |
| 14 | SSE 이벤트 수신 → invalidate | useSseInvalidator (parent) | 동일 | 없음 | dev tool |
| 15 | QuickMenuBar 모바일 컨텍스트 버튼 | parent 에 있음 | 동일 | 없음 | mobile |
| 16 | 행 컬러/그룹 컬러 적용 | renderRoomRow 안 | 동일 | 없음 | 시각 |
| 17 | dark mode | className 동일 | 동일 | 없음 | 시각 |
| 18 | loading 상태 (`pointer-events-none`) | inline className | 동일 | 없음 | E2E |
| 19 | 우클릭 차단 (`onContextMenu={preventDefault}`) | line 986 inline | 동일 | 없음 | E2E |
| 20 | TableSettingsModal 의 dividers 저장 | parent state | 동일 | 없음 | E2E |

★ = 가장 주의 깊게 검증할 항목 (ref / sticky / column resize)

---

## 변경 파일 명세

### 신규
- `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` (+~170 lines)

### 수정
- `frontend/src/pages/RoomAssignment.tsx` (-~160 lines, +~50 lines = 약 1210 lines)
  - line 870-1032 영역을 `<DesktopLayout ...props/>` 단일 호출로 치환
  - import 에 `DesktopLayout` 추가

### 영향 없음
- 모든 하위 컴포넌트 (`PageHeader`, `SummaryCards`, `CampaignToolbar`, `BuildingGroup`, `RoomRow`, `*Zone`, 모달 등)
- 모든 hooks (`useReservationsData`, `useColumnResize`, `useCampaignSend`, `useGuestMove`, etc.)
- `types.ts`, `utils/*.ts`

---

## 검증 체크리스트 (PR 머지 전)

### 정적 분석
- [ ] `npm run build` 성공 (TypeScript 타입 에러 0)
- [ ] `npm run lint` 통과
- [ ] DesktopLayout 의 props 인터페이스에 42 항목 모두 존재
- [ ] import 누락 없음 (RoomRow 등 type import 포함)

### PC 환경 (≥768px) 동작
- [ ] 페이지 첫 로딩 — 헤더/통계/툴바/매트릭스/zones 시각 동일
- [ ] BuildingGroup 접기/펴기
- [ ] 객실 매트릭스 — 컬럼 폭, sticky 헤더, 다음날 컬럼 확장/축소
- [ ] 게스트 드래그 → 빈 객실 드롭
- [ ] 게스트 드래그 → UnassignedZone / PartyZone / UnstableZone 드롭
- [ ] 게스트 드래그 → 다음날 칸 cross-day 드롭
- [ ] 인라인 편집: 이름/전화/파티/성별/예약객실/메모 6필드 모두
- [ ] SMS 칩: 클릭/할당/제거 동일
- [ ] 우클릭 컨텍스트 메뉴: 모든 액션 (색상/연박/취소/삭제/연락/날짜변경/stayGroup/unstable)
- [ ] 모달 11종 모두 열기/닫기 정상
- [ ] QuickMenuBar — 되돌리기/자동배정/파티추가
- [ ] Ctrl+Z 단축키
- [ ] 날짜 네비게이션 (← →) + 슬라이드 애니메이션
- [ ] SSE 이벤트 수신 시 자동 새로고침 (dev: 스케줄 발송 시뮬)
- [ ] dark mode 토글
- [ ] 객실 색상 / 그룹 색상 / 하이라이트 색상
- [ ] loading 상태 시 `pointer-events-none`

### 모바일 환경 (<768px) 동작
> Step #01 은 모바일 변화 0 — 모바일도 PC 와 동일한 가로 매트릭스를 그대로 렌더 (overflow 그대로)
- [ ] 모바일에서 PC 와 시각/동작 완전 동일 (회귀 없음)
- [ ] long-press 선택 모드 + QuickMenuBar 컨텍스트 버튼 동작

---

## 결정 필요 사항 (PR 전)

1. **Context vs prop drilling**
   - 42개 prop drilling 은 인터페이스 변경 시 부담
   - Step #01 의 "0 동작 변화" 원칙은 prop drilling 이 더 안전 (Context Provider 추가는 새 React rerender 경로)
   - **권장**: Step #01 에서는 prop drilling 그대로, Step #02 에서 분기 도입할 때 Context 검토

2. **DesktopLayout 파일 위치**
   - 옵션 A: `frontend/src/pages/RoomAssignment/layouts/DesktopLayout.tsx` (layouts/ 폴더 신설)
   - 옵션 B: `frontend/src/pages/RoomAssignment/DesktopLayout.tsx` (기존 폴더 평면)
   - **권장**: A — Step #02 에서 `layouts/MobileLayout.tsx` 도 같은 위치에 들어가게

3. **Type import 경로**
   - `RoomEntry` 는 `RoomRow.tsx` 에서 export, `Reservation` 은 `types.ts` 에서 export
   - DesktopLayout 도 동일하게 import (변경 없음)

4. **summary 타입**
   - `useMemo(() => { ... return { ... } }, [...])` 의 추론된 타입을 그대로 사용할지, 별도 `interface Summary` 를 `types.ts` 에 정의할지
   - **권장**: 별도 인터페이스 정의 (DesktopLayoutProps 의 타입 명확성을 위해)

---

## Step #01 이후 미리보기

| Step | 작업 | 영향 | PR 별 분리 |
|------|------|------|------------|
| **#02** | `MobileLayout.tsx` 빈 골격 (PC 와 동일 JSX 사본) + `isMobile ? Mobile : Desktop` 분기 | 모바일=PC 동일 | 별도 PR |
| **#03** | `MobileRoomCard` 신규 → MobileLayout 의 `renderRoomRow` 자리에 사용 | 모바일만 카드화 | 별도 PR |
| **#04** | Mobile Zones 카드화 | 모바일 zones | 별도 PR |
| **#05** | Mobile PageHeader / SummaryCards / CampaignToolbar 조정 | 모바일 헤더 | 별도 PR |
| **#06** | 마무리 (필요 시 bottom sheet, 터치 타겟) | 모바일 인터랙션 | 별도 PR |

---

## 사전조사 작성자 메모

이 문서는 `RoomAssignment.tsx` 의 실제 코드를 line 단위로 확인하며 작성됨:

- 전체 줄 수 확인: `wc -l` → 1321 lines
- import 영역 (1-77), 본체 시작 (79), return 시작 (863), 종료 (1318)
- JSX 구조 트리: line 864 (`<DndContext>`), 870 (`<div main wrapper>`), 872-1032 (추출 대상), 1034-1305 (모달 영역), 1306 (`</div>`), 1307-1316 (`<DragOverlay>`), 1317 (`</DndContext>`)
- Hooks/상태 인벤토리:
  - useState: line 85, 164, 170, 173, 197, 198, 215, 367, 375, 383, 464
  - useMutation: 113, 121, 128, 135, 143, 151
  - 커스텀 훅: useReservationsData (86), useUndoStack (195), useCollapsibleBuildings (199), useConfirmDialog (201), useReservationForm (207), useGuestMove (229), useSelectionSystem (183), useContextMenu (388), useColumnResize (439), useCampaignSend (451), useAutoAssign (465), useHighlightColors (384), useStayGroup (386), useSmsAssignment (682), useSseInvalidator (474)
  - useEffect: 190 (localStorage), 469 (clearTargets), 481 (Ctrl+Z)
  - useMemo: 506, 507, 514, 801
  - useCallback: 107, 756
- 모달 인벤토리 (parent 유지): ReservationFormModal (1035), QuickMenuBar (1045), ConfirmDialog (1100), MultiNightConfirmModal (1105), SendConfirmModal (1110), `<style>` (1122), AutoAssignConfirmModal (1136), TableSettingsModal (1145), StayGroupChainModal (1205), ExtendStayConflictModal (1220), DateChangeModal (1244), GuestContextMenu+backdrop (1267)

환각 방지: 위 모든 line number 는 실제 파일 `RoomAssignment.tsx` (2026-05-20 시점, commit fbbe2aa 이후) 에서 직접 grep/Read 로 확인됨.
