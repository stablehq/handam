import React from 'react';
import type { Reservation } from '../types';
import type { HoverZoneState } from '../hooks/useHoverZone';
import { useGuestDropTarget } from '../hooks/useGuestDropTarget';
import { mapBedSlots } from '../utils/mapBedSlots';
import { ROOM_ROW_HEIGHT, ROOM_ROW_HEIGHT_EMPTY } from '../utils/layoutConstants';
import { RoomMemoEditor } from './RoomMemoEditor';
import type { RowColorSettings } from '@/lib/highlight-colors';

export interface RoomEntry {
  room_id: number;
  room_number: string;
  isDormitory: boolean;
  bed_capacity: number;
}

export interface RoomGroupInfo {
  group_id: number;
  groupIndex: number;
  isFirst: boolean;
  isLast: boolean;
}

export interface RoomRowProps {
  // 객실 메타
  entry: RoomEntry;
  rowIndex: number;
  groupInfo: RoomGroupInfo | undefined;
  groupColor: string | undefined;

  // 객실 데이터
  guestsToday: Reservation[];
  guestsNextDay: Reservation[];
  roomMemo: string;
  onSaveRoomMemo: (roomId: number, memo: string) => Promise<void>;

  // 시각 의존
  isDarkMode: boolean;
  rowColors: RowColorSettings;

  // 공유 zone props (sharedZoneProps spread 와 동일)
  hover: HoverZoneState;
  setHover: (s: HoverZoneState) => void;
  clearHover: () => void;
  onDropZoneClick: (e: React.MouseEvent) => void;
  selectionActive: boolean;
  nextDayExpanded: boolean;
  NEXT_DAY_EXPANDED_WIDTH: number;
  nextDayColWidth: number;
  GUEST_COLS: string;
  renderGuestRow: (res: Reservation, showGrip: boolean, zone?: string) => React.ReactNode;
  renderCompactCell: (guest: Reservation) => React.ReactNode;
}

/**
 * 객실 한 행 (객실 라벨 + 게스트 리스트 + 다음날 컬럼) 컴포넌트.
 *
 * Phase G-2: RoomAssignment.tsx 의 renderRoomRow 인라인 함수 (170+줄) 추출.
 * 도미토리 침대 매핑은 mapBedSlots 유틸 사용.
 * 드롭존 동작은 useGuestDropTarget 훅 사용 (오늘 + 내일 각각).
 */
export function RoomRow({
  entry,
  rowIndex,
  groupInfo,
  groupColor,
  guestsToday,
  guestsNextDay,
  roomMemo,
  onSaveRoomMemo,
  isDarkMode,
  rowColors,
  hover, setHover, clearHover,
  onDropZoneClick,
  selectionActive,
  nextDayExpanded,
  NEXT_DAY_EXPANDED_WIDTH,
  nextDayColWidth,
  GUEST_COLS,
  renderGuestRow,
  renderCompactCell,
}: RoomRowProps) {
  const { room_id, room_number, isDormitory, bed_capacity } = entry;

  // 도미토리는 bed_order 기준 정렬
  const guests = isDormitory
    ? [...guestsToday].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id)
    : guestsToday;
  const nextGuests = isDormitory
    ? [...guestsNextDay].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id)
    : guestsNextDay;

  // 도미토리 침대 매핑 (오늘/내일 분리)
  const guestByBed = isDormitory ? mapBedSlots(guests, bed_capacity) : new Map<number, Reservation>();
  const nextByBed = isDormitory ? mapBedSlots(nextGuests, bed_capacity) : new Map<number, Reservation>();

  // 가시 행 수 — 빈 슬롯 보존
  const highestBedOrder = isDormitory
    ? Math.max(
        0,
        ...guests.map(g => g.bed_order || 0),
        ...nextGuests.map(g => g.bed_order || 0),
      )
    : 0;
  const maxOccupancy = Math.max(guests.length, nextGuests.length, highestBedOrder, 1);
  const visibleRows = isDormitory
    ? Math.min(bed_capacity, maxOccupancy)
    : Math.max(1, guests.length);
  const totalRows = visibleRows;
  const hasGuests = guests.length > 0;
  const rowHeight = hasGuests ? ROOM_ROW_HEIGHT : ROOM_ROW_HEIGHT_EMPTY;
  const stripeKey = groupInfo ? groupInfo.groupIndex : rowIndex;
  const isOverbooking = !isDormitory && guests.length >= 2;

  // 줄무늬 색상
  const stripeBgStyle: React.CSSProperties = isOverbooking
    ? { backgroundColor: isDarkMode ? `${rowColors.overbooking}1A` : rowColors.overbooking }
    : stripeKey % 2 === 0
      ? { backgroundColor: isDarkMode ? rowColors.evenDark : rowColors.even }
      : { backgroundColor: isDarkMode ? rowColors.oddDark : rowColors.odd };

  // 그룹 경계 색상
  const groupLast = groupInfo?.isLast;
  const borderStyle: React.CSSProperties = groupLast
    ? { borderBottomColor: isDarkMode ? (groupColor || '#4E5968') : (groupColor || '#D1D5DB') }
    : { borderBottomColor: isDarkMode ? '#2C2C34' : '#E5E8EB' };

  // 드롭존 (오늘 / 내일) — 게스트 선택 시에만 활성. 비선택 시엔 일반 행 hover 만 동작.
  const main = useGuestDropTarget({
    zoneId: `room-${room_id}`,
    hover, setHover, clearHover,
    enabled: selectionActive,
  });
  const next = useGuestDropTarget({
    zoneId: `next-room-${room_id}`,
    hover, setHover, clearHover,
    enabled: nextDayExpanded && selectionActive,
  });

  return (
    <div
      className={`group flex select-none transition-colors
        ${main.isDragOver
          ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
          : ''
        } ${selectionActive ? 'cursor-pointer' : ''}`}
      style={{ minHeight: `${totalRows * rowHeight}px`, ...(main.isDragOver ? {} : stripeBgStyle) }}
      {...main.dropZoneProps}
      onClick={onDropZoneClick}
    >
      {/* Room label - vertically centered, spans all rows */}
      <div className="flex items-center gap-1.5 flex-shrink-0 w-38 pl-3 pr-2 py-2 border-r border-r-[#E5E8EB] dark:border-r-gray-700 border-b" style={{ ...borderStyle, ...stripeBgStyle }}>
        <span className="font-semibold text-[#191F28] dark:text-white text-body shrink-0">{room_number}</span>
        <RoomMemoEditor roomId={room_id} memo={roomMemo} onSave={onSaveRoomMemo} />
      </div>

      {/* Guest rows */}
      <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b" style={borderStyle}>
        {isDormitory ? (
          Array.from({ length: totalRows }).map((_, i) => {
            const bedIdx = i + 1;
            const guest = guestByBed.get(bedIdx);
            if (guest) {
              return renderGuestRow(guest, true);
            }
            return (
              <div key={`empty-${i}`} className={`flex items-center ${hasGuests ? 'h-10' : 'h-9'} cursor-default`}>
                <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: GUEST_COLS }}>
                  <div className="overflow-hidden truncate col-span-full text-body text-[#B0B8C1] dark:text-[#4E5968] italic px-1.5">
                    {main.isDragOver ? '여기에 놓으세요' : ''}
                  </div>
                </div>
              </div>
            );
          })
        ) : guests.length > 0 ? (
          guests.map((res) => renderGuestRow(res, true))
        ) : (
          <div className="flex items-center h-9 cursor-default">
            <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: GUEST_COLS }}>
              <div className="overflow-hidden truncate col-span-full text-body text-[#3182F6] dark:text-[#3182F6] italic px-1.5">
                {main.isDragOver ? '여기에 놓으세요' : ''}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Next day column */}
      <div
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none border-b transition-all duration-200 ${
          next.isDragOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30'
            : ''
        } ${selectionActive ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, ...(next.isDragOver ? {} : { ...borderStyle, ...stripeBgStyle }) }}
        {...next.dropZoneProps}
        onClick={nextDayExpanded ? onDropZoneClick : undefined}
      >
        <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
          {Array.from({ length: totalRows }).map((_, i) => {
            const nextGuest = isDormitory ? nextByBed.get(i + 1) : nextGuests[i];
            return (
              <div
                key={`next-${i}`}
                className={`flex items-center ${nextDayExpanded ? 'justify-start' : 'justify-center'} ${hasGuests ? 'h-10' : 'h-9'} px-1 ${nextGuest?.is_long_stay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}
              >
                {nextGuest ? renderCompactCell(nextGuest) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
