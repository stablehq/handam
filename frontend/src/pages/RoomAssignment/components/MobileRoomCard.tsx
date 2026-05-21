/**
 * 객실 한 개 — 모바일(<768px) 세로 카드 레이아웃.
 *
 * Mobile Layout Step #03b (2026-05-20): PC `RoomRow` 의 가로 그리드를 세로 카드로 재구성.
 *
 * 레이아웃:
 *   ┌─ 101호 [📝메모]  도미(N/M)명  ─┐
 *   │ [MobileGuestRow]              │
 *   │ [MobileGuestRow]              │
 *   │ ── 내일 미리보기 ──            │
 *   │ • 이영희 ·남2  (텍스트 형태)   │
 *   └────────────────────────────────┘
 *
 * 보존 (PC RoomRow 와 동일):
 *  - 스트라이프 색상 (rowColors / overbooking / stripe pattern)
 *  - 그룹 경계 색상 (groupInfo.isLast 일 때 하단 테두리)
 *  - 도미토리 침대 매핑 (mapBedSlots) + 빈 자리 표시
 *  - 드롭존 (useGuestDropTarget) — selectionActive 일 때만 활성
 *  - dnd-kit useDroppable — PC 에서만 활성
 *  - is/isMainOver / isNextOver 시각 효과
 *  - 비활성 객실(isActive=false) 어둡게 처리
 *
 * 추가 props:
 *  - renderMobileGuestRow: 오늘 게스트 1명 렌더 함수 (RoomRow 의 renderGuestRow 대응)
 *
 * 사전조사: docs/plans/mobile-layout-step-03b-room-card.md
 */

import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { Reservation } from '../types';
import { useGuestDropTarget } from '../hooks/useGuestDropTarget';
import { useIsDesktop } from '../../../hooks/use-desktop';
import { mapBedSlots } from '../utils/mapBedSlots';
import { RoomMemoEditor } from './RoomMemoEditor';
import type { RoomRowProps } from './RoomRow';
import { formatGenderPeople, formatGuestSuffix } from '../utils/reservationFormat';

export interface MobileRoomCardProps extends Omit<RoomRowProps, 'renderGuestRow' | 'renderCompactCell' | 'GUEST_COLS' | 'NEXT_DAY_EXPANDED_WIDTH' | 'nextDayColWidth'> {
  /** 오늘 게스트 한 명 렌더 — MobileGuestRow 를 호출하는 closure. */
  renderMobileGuestRow: (res: Reservation, showGrip: boolean, zone?: string) => React.ReactNode;
}

export function MobileRoomCard({
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
  hover,
  setHover,
  clearHover,
  onDropZoneClick,
  selectionActive,
  nextDayExpanded,
  renderMobileGuestRow,
}: MobileRoomCardProps) {
  const { room_id, room_number, isDormitory, bed_capacity, isActive = true } = entry;

  // 도미토리는 bed_order 기준 정렬
  const guests = isDormitory
    ? [...guestsToday].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id)
    : guestsToday;
  const nextGuests = isDormitory
    ? [...guestsNextDay].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id)
    : guestsNextDay;

  // 도미토리 침대 매핑 (오늘)
  const guestByBed = isDormitory ? mapBedSlots(guests, bed_capacity) : new Map<number, Reservation>();

  // 도미토리: 활성 시 bed_capacity 만큼 슬롯, 비활성 시 0 (빈 침대 안 보임). 비도미토리: 게스트 수만큼 (최소 1).
  const totalSlots = isDormitory
    ? (isActive ? bed_capacity : 0)
    : Math.max(1, guests.length);

  const hasGuests = guests.length > 0;
  // 모바일 카드 스타일 — stripe / 그룹 경계 border 제거. 그룹 경계는 부모(renderRoomRow)에서 카드 사이 sibling divider 로 렌더.

  // 드롭존
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
  // Step #06a: 모바일도 드롭 활성.
  const dropMain = useDroppable({
    id: `room-${room_id}`,
    disabled: !isActive,
  });
  const dropNext = useDroppable({
    id: `next-room-${room_id}`,
    disabled: !isActive || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;

  return (
    <div
      className={`relative select-none transition-colors rounded-lg border ${
        hasGuests ? 'bg-white' : 'bg-[#FAFBFC]'
      } dark:bg-[#1E1E24] shadow-[0_1px_2px_rgba(0,0,0,0.04)] overflow-hidden ${
        isMainOver
          ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30 border-[#3182F6]/30'
          : 'border-[#E5E8EB] dark:border-gray-800'
      } ${selectionActive && isActive ? 'cursor-pointer' : ''}`}
      {...main.dropZoneProps}
      onClick={isActive ? onDropZoneClick : undefined}
    >
      {!isActive && (
        <div className="absolute inset-0 bg-black/30 dark:bg-black/50 pointer-events-none z-10" />
      )}

      {/* main droppable wrapper */}
      <div ref={dropMain.setNodeRef} className="relative">
        {isMainOver && (
          <div className="absolute inset-0 bg-[#3182F6]/15 dark:bg-[#3182F6]/20 pointer-events-none z-[5]" />
        )}

        {/* Card Header — 예약자 있을 때는 책갈피 형태로 축소. 배경/border 없음 → 객실 stripe 가 헤더~게스트 통째로 관통 (같은 객실 시각적 묶음). */}
        {hasGuests ? (
          <div className="flex items-center justify-center gap-1.5 px-2 h-[22px]">
            <span className="text-caption font-semibold text-[#3182F6] pl-[3px]">{room_number}</span>
            <RoomMemoEditor roomId={room_id} memo={roomMemo} onSave={onSaveRoomMemo} />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-semibold text-[#191F28] dark:text-white text-body shrink-0">{room_number}</span>
              <RoomMemoEditor roomId={room_id} memo={roomMemo} onSave={onSaveRoomMemo} />
            </div>
            <div className="flex items-center gap-2 text-caption text-[#8B95A1] dark:text-[#4E5968] shrink-0">
              {isDormitory && <span>도미 {guests.length}/{bed_capacity}</span>}
            </div>
          </div>
        )}

        {/* Today guests */}
        <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
          {isDormitory
            ? Array.from({ length: totalSlots }).map((_, i) => {
                const bedIdx = i + 1;
                const guest = guestByBed.get(bedIdx);
                if (guest) {
                  return <React.Fragment key={`bed-${bedIdx}`}>{renderMobileGuestRow(guest, true)}</React.Fragment>;
                }
                return null;
              })
            : guests.map((res) => (
                <React.Fragment key={res.id}>{renderMobileGuestRow(res, true)}</React.Fragment>
              ))}
        </div>

        {/* 내일 미리보기는 모바일에서 숨김 (요청). dropNext / next.dropZoneProps 는 추후 cross-day drop 활성 시 재추가. */}
      </div>
    </div>
  );
}
