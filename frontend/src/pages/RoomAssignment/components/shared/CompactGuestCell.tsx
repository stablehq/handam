import React from 'react';
import type { Dayjs } from 'dayjs';
import { Circle } from 'lucide-react';
import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import { InlineInput } from '../InlineInput';
import type { Reservation } from '../../types';

export interface CompactGuestCellProps {
  guest: Reservation;
  /** 펼침 모드: 그립 + 4-track 편집 그리드. 접힘 모드: 한 줄 텍스트 표시. */
  expanded: boolean;
  isSelected: boolean;
  selectionActive: boolean;
  /** 오늘 날짜 — 컴포넌트 내부에서 +1 일로 다음날 저장 시 사용. */
  selectedDate: Dayjs;
  NEXT_GUEST_COLS: string;
  onGripClick: (e: React.MouseEvent | React.PointerEvent, resId: number) => void;
  onGuestContextMenu: (e: React.MouseEvent, resId: number, zone?: string) => void;
  handleFieldSave: (resId: number, field: string, value: string, targetDate?: Dayjs) => Promise<void>;
  cancelDeselect: () => void;
}

/**
 * 다음날 컬럼의 게스트 셀 — 펼침/접힘 두 모드를 지원.
 *
 * Phase E-2: RoomAssignment.tsx 의 다음날 셀 인라인 JSX 를 3곳에서 통합.
 */
export function CompactGuestCell({
  guest,
  expanded,
  isSelected,
  // selectionActive 는 현재 시각 분기에 안 쓰지만 미래 일관성용으로 받아둠
  selectionActive: _selectionActive,
  selectedDate,
  NEXT_GUEST_COLS,
  onGripClick,
  onGuestContextMenu,
  handleFieldSave,
  cancelDeselect,
}: CompactGuestCellProps) {
  const gp = formatGenderPeople(guest);

  // 다음날 데이터 저장 — selectedDate + 1일을 targetDate 로
  const saveNext = (id: number, field: string, value: string) =>
    handleFieldSave(id, field, value, selectedDate.add(1, 'day'));

  if (!expanded) {
    return (
      <div className="flex items-center gap-1.5 truncate">
        <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">
          {guest.customer_name}
          {formatGuestSuffix(guest) && (
            <span className="ml-1 text-[#8B95A1] dark:text-[#4E5968]">{formatGuestSuffix(guest)}</span>
          )}
        </span>
        {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
      </div>
    );
  }

  return (
    <div
      className="group/guest flex items-center h-10 w-full"
      onContextMenu={(e) => onGuestContextMenu(e, guest.id)}
    >
      {/* Selection grip */}
      <div
        onClick={(e: React.MouseEvent) => onGripClick(e, guest.id)}
        className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
          isSelected
            ? 'text-[#3182F6] dark:text-[#3182F6]'
            : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
        }`}
      >
        <span className="relative flex items-center justify-center w-[16px] h-[16px] group/circle">
          <span className={`absolute inset-0 rounded-full bg-[#3182F6] transition-all duration-300 ease-out ${
            isSelected ? 'scale-[0.55] opacity-80' : 'scale-0 opacity-0 group-hover/circle:scale-[0.55] group-hover/circle:opacity-30'
          }`} />
          <Circle size={16} strokeWidth={1} className={`relative z-10 transition-colors duration-200 ${isSelected ? 'text-[#3182F6]' : ''}`} />
        </span>
      </div>
      {/* Editable fields */}
      <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
        <div className="overflow-hidden px-1 flex items-center gap-1 min-w-0">
          <InlineInput value={guest.customer_name} field="customer_name" resId={guest.id}
            onSave={saveNext}
            className="font-medium text-[#191F28] dark:text-white text-caption" placeholder="이름" compact onActivate={cancelDeselect} />
          {formatGuestSuffix(guest) && (
            <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{formatGuestSuffix(guest)}</span>
          )}
        </div>
        <div className="overflow-hidden px-1">
          <InlineInput value={guest.phone || ''} field="phone" resId={guest.id}
            onSave={saveNext}
            className="text-[#191F28] dark:text-white tabular-nums text-caption" placeholder="연락처" onActivate={cancelDeselect} />
        </div>
        <div className="overflow-hidden text-center px-1">
          <InlineInput value={guest.party_type || ''} field="party_type" resId={guest.id}
            onSave={saveNext}
            className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" onActivate={cancelDeselect} />
        </div>
        <div className="overflow-hidden text-center px-1">
          <InlineInput value={gp} field="genderPeople" resId={guest.id}
            onSave={saveNext}
            className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" onActivate={cancelDeselect} />
        </div>
      </div>
    </div>
  );
}
