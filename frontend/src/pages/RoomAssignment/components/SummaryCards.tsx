/**
 * 객실 배정 페이지 상단 통계 카드 묶음.
 *
 * Phase A-5: RoomAssignment.tsx 의 통계 영역 JSX 분리.
 * SummaryShape 는 부모의 useMemo 결과 shape 와 일치해야 한다 (RoomAssignment.tsx:2232~).
 *
 * Mobile Layout Step #05 (2026-05-20): useIsMobile 분기. 모바일은 MobileSummaryCards (grid-cols-2 컴팩트) 로 위임.
 */

import { useIsMobile } from '../../../hooks/use-mobile';
import { MobileSummaryCards } from './MobileSummaryCards';

export interface SummaryShape {
  roomTotal: number;
  roomMale: number;
  roomFemale: number;
  partyTotal: number;
  partyMale: number;
  partyFemale: number;
  firstTotal: number;
  firstMale: number;
  firstFemale: number;
  secondOnlyTotal: number;
  secondOnlyMale: number;
  secondOnlyFemale: number;
  conversionRate: number;
  genderRatio: string;
  unstableTotal: number;
  unstableMale: number;
  unstableFemale: number;
}

interface SummaryCardsProps {
  summary: SummaryShape;
  hasUnstable: boolean;
}

export function SummaryCards({ summary, hasUnstable }: SummaryCardsProps) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <MobileSummaryCards summary={summary} hasUnstable={hasUnstable} />;
  }
  return (
    <div className="flex flex-wrap gap-3 items-stretch">
      {/* 그룹 카드 */}
      <div className="stat-card flex overflow-hidden !p-0">
        <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
          <span className="stat-label whitespace-nowrap">총 예약자</span>
          <div className="flex items-center justify-center gap-2.5 mt-1">
            <span className="stat-value tabular-nums text-[#4A90D9]">{summary.roomMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
            <span className="stat-value tabular-nums text-[#E05263]">{summary.roomFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
          </div>
        </div>
        <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
        <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
          <span className="stat-label whitespace-nowrap">현재 신청인원</span>
          <div className="stat-value tabular-nums mt-1">{summary.partyTotal}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></div>
        </div>
        <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
        <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
          <span className="stat-label whitespace-nowrap">1차</span>
          <div className="flex items-center justify-center gap-2.5 mt-1">
            <span className="stat-value tabular-nums text-[#4A90D9]">{summary.firstMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
            <span className="stat-value tabular-nums text-[#E05263]">{summary.firstFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
          </div>
        </div>
        <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
        <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
          <span className="stat-label whitespace-nowrap">2차만</span>
          <div className="flex items-center justify-center gap-2.5 mt-1">
            <span className="stat-value tabular-nums text-[#4A90D9]">{summary.secondOnlyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
            <span className="stat-value tabular-nums text-[#E05263]">{summary.secondOnlyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
          </div>
        </div>
        {hasUnstable && summary.unstableTotal > 0 && (
          <>
            <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
            <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
              <span className="stat-label whitespace-nowrap text-[#FF6B2C]">언스테이블</span>
              <div className="flex items-center justify-center gap-2.5 mt-1">
                <span className="stat-value tabular-nums text-[#4A90D9]">{summary.unstableMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
                <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
                <span className="stat-value tabular-nums text-[#E05263]">{summary.unstableFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              </div>
            </div>
          </>
        )}
        <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
        <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
          <span className="stat-label whitespace-nowrap">전체</span>
          <div className="flex items-center justify-center gap-2.5 mt-1">
            <span className="stat-value tabular-nums text-[#4A90D9]">{summary.partyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
            <span className="stat-value tabular-nums text-[#E05263]">{summary.partyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
          </div>
        </div>
      </div>
      <div className="stat-card w-[120px] flex flex-col items-center justify-center">
        <span className="stat-label">2차 전환율</span>
        <div className="stat-value tabular-nums mt-1">{summary.conversionRate}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">%</span></div>
      </div>
      <div className="stat-card w-[120px] flex flex-col items-center justify-center">
        <span className="stat-label">파티 성비</span>
        <div className="stat-value tabular-nums mt-1">{summary.genderRatio}</div>
      </div>
    </div>
  );
}
