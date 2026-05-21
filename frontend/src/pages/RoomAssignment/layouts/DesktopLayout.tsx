/**
 * RoomAssignment 페이지의 PC(≥768px) 매트릭스 레이아웃.
 *
 * Mobile Layout Step #01 (2026-05-20): RoomAssignment.tsx 의 line 872-1032 JSX 를
 * 라인 단위 1:1 로 옮긴 stateless presentational 컴포넌트.
 *
 * 동작 동등성:
 *  - JSX 구조 / className / key / ref / props 모두 부모와 동일
 *  - 모든 상태/핸들러/hooks 는 부모(RoomAssignment.tsx) 에 그대로 유지
 *  - DnD / 모달 / QuickMenuBar / GuestContextMenu / 단축키 / SSE 는 모두 부모 책임
 *  - Fragment 로 감싸므로 sticky containing block / space-y-* 영향 없음
 *
 * 사전조사: docs/plans/mobile-layout-step-01-desktop-extract.md
 */

import React from 'react';
import type { Dayjs } from 'dayjs';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import dayjs from 'dayjs';
import { TextInput } from '@/components/ui/input';
import { PageHeader } from '../components/PageHeader';
import { SummaryCards } from '../components/SummaryCards';
import { CampaignToolbar } from '../components/CampaignToolbar';
import { BuildingGroup, type BuildingGroupData } from '../components/BuildingGroup';
import type { RoomEntry } from '../components/RoomRow';
import { UnassignedZone } from '../components/zones/UnassignedZone';
import { PartyZone } from '../components/zones/PartyZone';
import { UnstableZone } from '../components/zones/UnstableZone';
import { CancelledZone } from '../components/zones/CancelledZone';
import type { ColWidths } from '../hooks/useColumnResize';
import type { Reservation, Summary } from '../types';

type CampaignToolbarProps = React.ComponentProps<typeof CampaignToolbar>;
type SharedZoneProps = Omit<
  React.ComponentProps<typeof UnassignedZone>,
  'guests' | 'nextDayGuests'
>;

export interface DesktopLayoutProps {
  // ── SummaryCards (2)
  summary: Summary;
  hasUnstable: boolean;

  // ── CampaignToolbar (13) — 부모 useCampaignSend / useReservationForm 출력 그대로 pass-through
  templateLabels: CampaignToolbarProps['templateLabels'];
  selectedTemplateKey: CampaignToolbarProps['selectedTemplateKey'];
  setSelectedTemplateKey: CampaignToolbarProps['setSelectedTemplateKey'];
  campaignDropdownOpen: CampaignToolbarProps['campaignDropdownOpen'];
  setCampaignDropdownOpen: CampaignToolbarProps['setCampaignDropdownOpen'];
  campaignDropdownRef: CampaignToolbarProps['campaignDropdownRef'];
  targets: CampaignToolbarProps['targets'];
  clearTargets: CampaignToolbarProps['clearTargets'];
  sending: CampaignToolbarProps['sending'];
  loadTargets: CampaignToolbarProps['loadTargets'];
  requestSendCampaign: CampaignToolbarProps['requestSendCampaign'];
  onOpenTableSettings: CampaignToolbarProps['onOpenTableSettings'];
  onAddPartyGuest: CampaignToolbarProps['onAddPartyGuest'];

  // ── Date navigation (4)
  selectedDate: Dayjs;
  setSelectedDate: (d: Dayjs) => void;
  navigateDate: (direction: 'prev' | 'next') => Promise<void> | void;
  animDirection: 'none' | 'left' | 'right';

  // ── Column resize / sticky (10) — useColumnResize 출력
  dateHeaderRef: React.RefObject<HTMLDivElement>;
  tableContainerRef: React.RefObject<HTMLDivElement>;
  dateHeaderH: number;
  resizeGuideX: number | null;
  startResize: (col: keyof ColWidths, e: React.MouseEvent) => void;
  colWidths: ColWidths;
  GUEST_COLS: string;
  NEXT_GUEST_COLS: string;
  NEXT_DAY_EXPANDED_WIDTH: number;
  nextDayExpanded: boolean;
  setNextDayExpanded: (b: boolean) => void;

  // ── BuildingGroup loop (5)
  buildingGroups: BuildingGroupData[];
  collapsedBuildings: Set<number | null>;
  toggleBuildingCollapse: (id: number | null) => void;
  renderRoomRow: (entry: RoomEntry, rowIndex: number) => React.ReactNode;
  loading: boolean;

  // ── Zones (7)
  unassigned: Reservation[];
  nextDayUnassigned: Reservation[];
  partyOnly: Reservation[];
  nextDayPartyOnly: Reservation[];
  unstableGuests: Reservation[];
  cancelledGuests: Reservation[];
  sharedZoneProps: SharedZoneProps;
}

export function DesktopLayout({
  // SummaryCards
  summary,
  hasUnstable,
  // CampaignToolbar
  templateLabels,
  selectedTemplateKey,
  setSelectedTemplateKey,
  campaignDropdownOpen,
  setCampaignDropdownOpen,
  campaignDropdownRef,
  targets,
  clearTargets,
  sending,
  loadTargets,
  requestSendCampaign,
  onOpenTableSettings,
  onAddPartyGuest,
  // Date nav
  selectedDate,
  setSelectedDate,
  navigateDate,
  animDirection,
  // Column resize / sticky
  dateHeaderRef,
  tableContainerRef,
  dateHeaderH,
  resizeGuideX,
  startResize,
  colWidths,
  GUEST_COLS,
  NEXT_GUEST_COLS,
  NEXT_DAY_EXPANDED_WIDTH,
  nextDayExpanded,
  setNextDayExpanded,
  // BuildingGroup loop
  buildingGroups,
  collapsedBuildings,
  toggleBuildingCollapse,
  renderRoomRow,
  loading,
  // Zones
  unassigned,
  nextDayUnassigned,
  partyOnly,
  nextDayPartyOnly,
  unstableGuests,
  cancelledGuests,
  sharedZoneProps,
}: DesktopLayoutProps) {
  return (
    <>
      <PageHeader />

      <SummaryCards summary={summary} hasUnstable={hasUnstable} />

      <CampaignToolbar
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
        onOpenTableSettings={onOpenTableSettings}
        onAddPartyGuest={onAddPartyGuest}
      />

      {/* Main grid card */}
      <div className="section-card !overflow-visible w-max min-w-full">
        {/* Date navigation header — sticky */}
        <div ref={dateHeaderRef} className="sticky top-0 z-20">
          <div className="section-header justify-center bg-white dark:bg-[#1E1E24]">
            <div className="flex items-center gap-1">
              <button
                onClick={() => navigateDate('prev')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <TextInput
                type="date"
                sizing="sm"
                value={selectedDate.format('YYYY-MM-DD')}
                onChange={(e) => {
                  if (e.target.value) setSelectedDate(dayjs(e.target.value));
                }}
              />
              <button
                onClick={() => navigateDate('next')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="section-body !pt-2">
          <div
            key={selectedDate.format('YYYY-MM-DD')}
            className={
              animDirection === 'left'
                ? 'date-slide-left'
                : animDirection === 'right'
                  ? 'date-slide-right'
                  : ''
            }
          >
            {/* Unified Table */}
            <div ref={tableContainerRef} className="relative rounded-xl border border-[#F2F4F6] dark:border-[#2C2C34]">
              {resizeGuideX !== null && (
                <div className="absolute top-0 bottom-0 w-px bg-[#3182F6] z-50 pointer-events-none" style={{ left: resizeGuideX }} />
              )}
              {/* Header */}
              <div className="flex items-center h-10 bg-[#F2F4F6] dark:bg-[#17171C] border-b border-[#D1D5DB] dark:border-[#4E5968] sticky z-[19]" style={{ top: dateHeaderH }}>
                <div className="flex-shrink-0 pl-3 pr-2 w-38 border-r border-[#F2F4F6] dark:border-[#2C2C34]">
                  <span className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">객실</span>
                </div>
                <div className="w-10 flex-shrink-0" />
                <div
                  className="flex-1 grid items-center"
                  style={{ gridTemplateColumns: GUEST_COLS }}
                >
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">이름<div onMouseDown={(e) => startResize('name', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">전화번호<div onMouseDown={(e) => startResize('phone', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">파티<div onMouseDown={(e) => startResize('party', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">성별<div onMouseDown={(e) => startResize('gender', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">예약객실<div onMouseDown={(e) => startResize('roomType', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">메모<div onMouseDown={(e) => startResize('notes', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">문자<div onMouseDown={(e) => startResize('sms', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                </div>
                <div className="relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none flex flex-col justify-center self-stretch transition-all duration-200" style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay }}>
                  {!nextDayExpanded && (
                    <div onMouseDown={(e) => startResize('nextDay', e)} className="absolute left-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" />
                  )}
                  {!nextDayExpanded ? (
                    <div className="flex items-center justify-center gap-1 px-2">
                      <button onClick={() => setNextDayExpanded(true)} className="text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="펼치기">
                        <ChevronsLeft className="h-3.5 w-3.5" />
                      </button>
                      <span className="text-caption font-semibold text-[#8B95A1] dark:text-[#8B95A1]">{selectedDate.add(1, 'day').format('M/D')}</span>
                    </div>
                  ) : (
                    <div className="flex items-center">
                      <button onClick={() => setNextDayExpanded(false)} className="w-8 flex-shrink-0 flex items-center justify-center text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="접기">
                        <ChevronsRight className="h-3.5 w-3.5" />
                      </button>
                      <div className="flex-1 grid items-center" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
                        <div className="px-1 text-caption font-semibold text-[#8B95A1] whitespace-nowrap">{selectedDate.add(1, 'day').format('M/D')}</div>
                        <div className="px-1 text-[10px] font-semibold text-[#8B95A1]">전화번호</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">파티</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">성별</div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Selection mode toast is handled via useEffect */}

              {/* Room Rows (stale-while-revalidate: 이전 데이터 유지, 새 데이터 조용히 교체) */}
              <div className={loading ? 'pointer-events-none' : ''} onContextMenu={(e) => { if (!(e.target as HTMLElement).closest('[data-allow-context]')) e.preventDefault(); }}>
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

              <UnassignedZone
                guests={unassigned}
                nextDayGuests={nextDayUnassigned}
                {...sharedZoneProps}
              />

              <PartyZone
                guests={partyOnly}
                nextDayGuests={nextDayPartyOnly}
                {...sharedZoneProps}
              />

              <UnstableZone
                guests={unstableGuests}
                nextDayGuests={[]}
                {...sharedZoneProps}
              />

              <CancelledZone
                guests={cancelledGuests}
                nextDayGuests={[]}
                {...sharedZoneProps}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
