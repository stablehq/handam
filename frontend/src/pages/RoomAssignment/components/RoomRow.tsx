import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { Reservation } from '../types';
import type { HoverZoneState } from '../hooks/useHoverZone';
import { useGuestDropTarget } from '../hooks/useGuestDropTarget';
import { useIsDesktop } from '../../../hooks/use-desktop';
import { mapBedSlots } from '../utils/mapBedSlots';
import { ROOM_ROW_HEIGHT, ROOM_ROW_HEIGHT_EMPTY } from '../utils/layoutConstants';
import { RoomMemoEditor } from './RoomMemoEditor';
import type { RowColorSettings } from '@/lib/highlight-colors';

export interface RoomEntry {
  room_id: number;
  room_number: string;
  isDormitory: boolean;
  bed_capacity: number;
  isActive?: boolean;
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
  const { room_id, room_number, isDormitory, bed_capacity, isActive = true } = entry;

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

  // 도미토리는 항상 bed_capacity 만큼 행 표시 (비활성 시 1행), 비도미토리는 게스트 수만큼 (최소 1)
  const totalRows = isDormitory ? (isActive ? bed_capacity : 1) : Math.max(1, guests.length);
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
  const isDesktop = useIsDesktop();
  const main = useGuestDropTarget({
    zoneId: `room-${room_id}`,
    hover, setHover, clearHover,
    enabled: selectionActive && isActive,
  });
  const next = useGuestDropTarget({
    zoneId: `next-room-${room_id}`,
    hover, setHover, clearHover,
    enabled: nextDayExpanded && selectionActive && isActive,
  });
  // dnd-kit useDroppable — PC 드래그용. 모바일은 disabled
  const dropMain = useDroppable({
    id: `room-${room_id}`,
    disabled: !isDesktop || !isActive,
  });
  const dropNext = useDroppable({
    id: `next-room-${room_id}`,
    disabled: !isDesktop || !isActive || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;

  return (
    <div
      className={`group relative flex select-none transition-colors
        ${isMainOver
          ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
          : ''
        } ${selectionActive && isActive ? 'cursor-pointer' : ''}`}
      style={{ minHeight: `${totalRows * rowHeight}px`, ...(isMainOver ? {} : stripeBgStyle) }}
      {...main.dropZoneProps}
      onClick={isActive ? onDropZoneClick : undefined}
    >
      {!isActive && (
        <div className="absolute inset-0 bg-black/30 dark:bg-black/50 pointer-events-none z-10" />
      )}
      {/* main droppable wrapper — 라벨 + 게스트 리스트만 포함 (next 영역 분리로 IoU 기반 collision detection의 nested 우선순위 함정 회피) */}
      <div ref={dropMain.setNodeRef} className="relative flex flex-1 min-w-0">
        {isMainOver && (
          <div className="absolute inset-0 bg-[#3182F6]/15 dark:bg-[#3182F6]/20 pointer-events-none z-[5]" />
        )}
        {/* Room label - vertically centered, spans all rows */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-38 pl-3 pr-2 border-r border-r-[#E5E8EB] dark:border-r-gray-700 border-b" style={{ ...borderStyle, ...stripeBgStyle }}>
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
                <div key={`empty-${i}`} className="flex items-center cursor-default" style={{ height: hasGuests ? ROOM_ROW_HEIGHT : ROOM_ROW_HEIGHT_EMPTY }}>
                  <div className="flex-1 grid items-center" style={{ gridTemplateColumns: GUEST_COLS }}>
                    <div className="overflow-hidden truncate col-span-full text-body text-[#B0B8C1] dark:text-[#4E5968] italic px-1.5">
                                          </div>
                  </div>
                </div>
              );
            })
          ) : guests.length > 0 ? (
            guests.map((res) => renderGuestRow(res, true))
          ) : (
            <div className="flex items-center cursor-default" style={{ height: ROOM_ROW_HEIGHT_EMPTY }}>
              <div className="flex-1 grid items-center" style={{ gridTemplateColumns: GUEST_COLS }}>
                <div className="overflow-hidden truncate col-span-full text-body text-[#3182F6] dark:text-[#3182F6] italic px-1.5">
                                  </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Next day column */}
      <div
        ref={dropNext.setNodeRef}
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none border-b transition-all duration-200 ${
          isNextOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30'
            : ''
        } ${selectionActive ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, ...(isNextOver ? {} : { ...borderStyle, ...stripeBgStyle }) }}
        {...next.dropZoneProps}
        onClick={nextDayExpanded ? onDropZoneClick : undefined}
      >
        {isNextOver && (
          <div className="absolute inset-0 bg-[#3182F6]/15 dark:bg-[#3182F6]/20 pointer-events-none z-[5]" />
        )}
        <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
          {Array.from({ length: totalRows }).map((_, i) => {
            const nextGuest = isDormitory ? nextByBed.get(i + 1) : nextGuests[i];
            return (
              <div
                key={`next-${i}`}
                className={`flex items-center ${nextDayExpanded ? 'justify-start' : 'justify-center'} px-1 ${nextGuest?.is_long_stay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}
                style={{ height: hasGuests ? ROOM_ROW_HEIGHT : ROOM_ROW_HEIGHT_EMPTY }}
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
