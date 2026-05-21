/**
 * RoomAssignment 페이지의 모바일(<768px) 레이아웃.
 *
 * Mobile Layout Step #03a (2026-05-20): wrapper 를 full JSX copy 로 확장.
 * 이 단계의 MobileLayout 은 DesktopLayout 의 JSX 본문을 라인 단위 1:1 로 복사한다.
 * 시각/동작 변화 0 — Step #02 와 동일하게 렌더.
 *
 * 향후 단계:
 *  - Step #03b: MobileRoomCard 도입 + 컬럼 헤더 제거 + 객실 영역 카드화
 *  - Step #04+: Zones, Header 등 추가 모바일화
 *  - DesktopLayout 은 손대지 않음 (PC 동작 보장)
 *
 * 사전조사: docs/plans/mobile-layout-step-03a-mobile-expand.md
 */

import dayjs from 'dayjs';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { TextInput } from '@/components/ui/input';
import { PageHeader } from '../components/PageHeader';
import { SummaryCards } from '../components/SummaryCards';
import { CampaignToolbar } from '../components/CampaignToolbar';
import { UnassignedZone } from '../components/zones/UnassignedZone';
import { PartyZone } from '../components/zones/PartyZone';
import { UnstableZone } from '../components/zones/UnstableZone';
import { CancelledZone } from '../components/zones/CancelledZone';
import { type DesktopLayoutProps } from './DesktopLayout';

export function MobileLayout({
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
  // Column resize / sticky — Step #03b 에서 컬럼 헤더 제거. 일부 prop 은 미사용이지만 인터페이스 호환을 위해 destructure 만 유지.
  dateHeaderRef,
  tableContainerRef,
  // BuildingGroup loop
  buildingGroups,
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
      {/* Step #03b: w-full + overflow-x-clip 로 viewport 묶음 (BuildingGroup bookmark translateX(-100%) 등 좌측 spillover 차단). overflow-x-clip 은 scroll container 를 만들지 않아 sticky 가 정상 작동. */}
      <div className="section-card !overflow-x-clip w-full">
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

        {/* 모바일: section-body 의 기본 p-5 (20px) 가 너무 큼 → 0 으로. 아래 table container 의 p-2 만 inset 담당. */}
        <div className="section-body !p-0 !pt-2">
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
            {/* Card list container (Step #03b — 컬럼 헤더 및 resize 가이드 제거) */}
            {/* 모바일: 개별 카드 분리. flex-col + gap 으로 카드 사이 간격. BuildingGroup 미사용 (모바일에선 책갈피 탭 / 그룹 접기 미지원, 객실들 flat 렌더). */}
            <div
              ref={tableContainerRef}
              className={`relative flex flex-col gap-2 p-2 ${loading ? 'pointer-events-none' : ''}`}
              onContextMenu={(e) => { if (!(e.target as HTMLElement).closest('[data-allow-context]')) e.preventDefault(); }}
            >
              {/* Rooms — buildingGroups 평탄화 */}
              {(() => {
                let rowIdx = 0;
                return buildingGroups.flatMap((group) =>
                  group.entries.map((entry) => {
                    const node = renderRoomRow(entry, rowIdx);
                    rowIdx += 1;
                    return node;
                  })
                );
              })()}

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
