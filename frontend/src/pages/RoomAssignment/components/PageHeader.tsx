import { BedDouble } from 'lucide-react';

/**
 * 객실 배정 페이지 상단 제목 영역.
 *
 * Phase A-5: RoomAssignment.tsx 의 인라인 JSX 분리 (정적 콘텐츠).
 */
export function PageHeader() {
  return (
    <div>
      <div className="flex items-center gap-2.5">
        <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
          <BedDouble size={20} />
        </div>
        <div>
          <h1 className="page-title">객실 배정</h1>
          <p className="page-subtitle">날짜별 객실을 배정하고 SMS를 발송하세요</p>
        </div>
      </div>
    </div>
  );
}
