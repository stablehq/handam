/**
 * 객실 배정 페이지 상단 통계 카드 — 모바일(<768px) 컴팩트 grid 변형.
 *
 * Mobile Layout Step #05 (2026-05-20): SummaryCards 의 가로 9-card 배열을
 * 2열 grid 로 재구성. 표시 데이터/색상은 PC 와 동일.
 *
 * PC 의 130px 고정 폭 카드 → 모바일 grid-cols-2 셀로. unstable 은 has_unstable 일 때만.
 */

import type { SummaryShape } from './SummaryCards';

interface MobileSummaryCardsProps {
  summary: SummaryShape;
  hasUnstable: boolean;
}

interface CellProps {
  label: string;
  male?: number;
  female?: number;
  value?: string | number;
  unit?: string;
  labelColor?: string;
}

function Cell({ label, male, female, value, unit, labelColor }: CellProps) {
  return (
    <div className="stat-card !p-1 flex flex-col items-center justify-center gap-0.5">
      <span className={`text-tiny text-[#8B95A1] whitespace-nowrap ${labelColor ?? ''}`}>{label}</span>
      {typeof male === 'number' && typeof female === 'number' ? (
        <div className="flex items-center gap-1 tabular-nums">
          <span className="text-label font-semibold text-[#4A90D9]">{male}</span>
          <span className="text-tiny text-[#B0B8C1]">/</span>
          <span className="text-label font-semibold text-[#E05263]">{female}</span>
        </div>
      ) : (
        <div className="tabular-nums">
          <span className="text-label font-semibold text-[#191F28] dark:text-white">{value}</span>
          {unit && <span className="ml-0.5 text-tiny text-[#B0B8C1]">{unit}</span>}
        </div>
      )}
    </div>
  );
}

export function MobileSummaryCards({ summary, hasUnstable }: MobileSummaryCardsProps) {
  return (
    <div className="grid grid-cols-4 gap-1">
      <Cell label="총 예약자" male={summary.roomMale} female={summary.roomFemale} />
      <Cell label="현재 신청인원" value={summary.partyTotal} unit="명" />
      <Cell label="1차" male={summary.firstMale} female={summary.firstFemale} />
      <Cell label="2차만" male={summary.secondOnlyMale} female={summary.secondOnlyFemale} />
      {hasUnstable && summary.unstableTotal > 0 && (
        <Cell
          label="언스테이블"
          male={summary.unstableMale}
          female={summary.unstableFemale}
          labelColor="text-[#FF6B2C]"
        />
      )}
      <Cell label="전체" male={summary.partyMale} female={summary.partyFemale} />
      <Cell label="2차 전환율" value={summary.conversionRate} unit="%" />
      <Cell label="파티 성비" value={summary.genderRatio} />
    </div>
  );
}
