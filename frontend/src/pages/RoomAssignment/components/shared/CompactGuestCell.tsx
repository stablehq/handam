import React from 'react';
import type { Dayjs } from 'dayjs';
import { GripVertical } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import { InlineInput } from '../InlineInput';
import type { Reservation } from '../../types';
import { ROOM_ROW_HEIGHT } from '../../utils/layoutConstants';

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
  // Step #06a: 모바일도 드래그 활성.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `guest-next-${guest.id}`,
  });

  // 다음날 데이터 저장 — selectedDate + 1일을 targetDate 로
  const saveNext = (id: number, field: string, value: string) =>
    handleFieldSave(id, field, value, selectedDate.add(1, 'day'));

  if (!expanded) {
    return (
      <div className="flex items-center gap-1.5 truncate">
        <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">
          {(guest.visitor_name && guest.visitor_name !== guest.customer_name) ? guest.visitor_name : guest.customer_name}
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
      className={`group/guest flex items-center w-full ${isDragging ? 'opacity-40' : ''}`}
      style={{ height: ROOM_ROW_HEIGHT }}
      onContextMenu={(e) => {
        if (document.activeElement instanceof HTMLInputElement) return;
        onGuestContextMenu(e, guest.id);
      }}
    >
      {/* Selection grip */}
      <div
        ref={setNodeRef}
        {...attributes}
        {...listeners}
        className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-grab active:cursor-grabbing touch-none text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
          isSelected
            ? 'text-[#3182F6] dark:text-[#3182F6]'
            : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
        }`}
      >
        {/* Step #06a: 모바일도 GripVertical. */}
        <GripVertical size={16} strokeWidth={1.5} />
      </div>
      {/* Editable fields */}
      <div className="flex-1 grid items-center" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
        <div className="overflow-hidden px-1 flex items-center gap-1 min-w-0">
          {(() => {
            const useVisitor = !!(guest.visitor_name && guest.visitor_name !== guest.customer_name);
            return (
              <InlineInput value={useVisitor ? (guest.visitor_name || '') : guest.customer_name} field={useVisitor ? 'visitor_name' : 'customer_name'} resId={guest.id}
                onSave={saveNext}
                className="font-medium text-[#191F28] dark:text-white text-caption" placeholder="이름" compact onActivate={cancelDeselect} singleClick />
            );
          })()}
          {formatGuestSuffix(guest) && (
            <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{formatGuestSuffix(guest)}</span>
          )}
        </div>
        <div className="overflow-hidden px-1">
          {(() => {
            const useVisitorPhone = !!(guest.visitor_phone && guest.visitor_phone !== guest.phone);
            return (
              <InlineInput value={useVisitorPhone ? (guest.visitor_phone || '') : (guest.phone || '')} field={useVisitorPhone ? 'visitor_phone' : 'phone'} resId={guest.id}
                onSave={saveNext}
                className="text-[#191F28] dark:text-white tabular-nums text-caption" placeholder="연락처" onActivate={cancelDeselect} singleClick />
            );
          })()}
        </div>
        <div className="overflow-hidden text-center px-1">
          <InlineInput value={guest.party_type || ''} field="party_type" resId={guest.id}
            onSave={saveNext}
            className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" onActivate={cancelDeselect} singleClick />
        </div>
        <div className="overflow-hidden text-center px-1">
          <InlineInput value={gp} field="genderPeople" resId={guest.id}
            onSave={saveNext}
            className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" onActivate={cancelDeselect} singleClick />
        </div>
      </div>
    </div>
  );
}
