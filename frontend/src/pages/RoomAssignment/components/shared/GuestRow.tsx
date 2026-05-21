import React from 'react';
import type { Dayjs } from 'dayjs';
import { GripVertical } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { normalizeUtcString } from '../../../../lib/utils';
import {
  PRESET_HIGHLIGHT_STYLES,
  isCustomHexColor,
  getCustomBgStyle,
  getCustomTextClass,
  isLightColor,
} from '@/lib/highlight-colors';
import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import { InlineInput } from '../InlineInput';
import { SmsCell } from '../SmsCell';
import type { Reservation } from '../../types';
import { ROOM_ROW_HEIGHT } from '../../utils/layoutConstants';

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

export interface GuestRowProps {
  // 행 데이터
  res: Reservation;
  showGrip: boolean;
  isSelected: boolean;
  zone?: string;

  // 공유 상태
  selectionActive: boolean;
  isDarkMode: boolean;
  GUEST_COLS: string;
  templateLabels: TemplateLabel[];
  selectedDate: Dayjs;
  quickAddedId: number | null;

  // 핸들러
  onGripClick: (e: React.MouseEvent | React.PointerEvent, resId: number) => void;
  onGuestContextMenu: (e: React.MouseEvent, resId: number, zone?: string) => void;
  handleFieldSave: (resId: number, field: string, value: string, targetDate?: Dayjs) => Promise<void>;
  handleSmsToggle: (resId: number, templateKey: string) => void | Promise<void>;
  handleSmsAssign: (resId: number, templateKey: string) => void | Promise<void>;
  handleSmsRemove: (resId: number, templateKey: string) => void | Promise<void>;
  cancelDeselect: () => void;

  // long-press refs (useContextMenu 가 소유, 이 행 핸들러가 read/write)
  longPressTimerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
  longPressFiredRef: React.MutableRefObject<boolean>;
}

/**
 * 게스트 한 줄을 렌더하는 공통 컴포넌트.
 *
 * Phase E-1: RoomAssignment.tsx 의 renderGuestRow 인라인 함수 (140줄) 추출.
 * Phase F (zones), G (rooms) 의 모든 행 렌더링이 이 컴포넌트를 공유한다.
 */
export function GuestRow({
  res,
  showGrip,
  isSelected,
  zone,
  selectionActive,
  isDarkMode,
  GUEST_COLS,
  templateLabels,
  selectedDate,
  quickAddedId,
  onGripClick,
  onGuestContextMenu,
  handleFieldSave,
  handleSmsToggle,
  handleSmsAssign,
  handleSmsRemove,
  cancelDeselect,
  longPressTimerRef,
  longPressFiredRef,
}: GuestRowProps) {
  const genderPeople = formatGenderPeople(res);
  const longStay = !!res.is_long_stay;
  const isCancelled = res.status === 'cancelled';
  // Step #06a: 모바일에서도 드래그 활성. cancelled 만 제외.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `guest-${res.id}`,
    disabled: isCancelled,
  });
  const isCustomHex = isCustomHexColor(res.highlight_color);
  const highlightStyle = !isCustomHex && res.highlight_color ? PRESET_HIGHLIGHT_STYLES[res.highlight_color] : null;
  const hasCustomText = isCustomHex || !!highlightStyle?.text;
  // 진한 hex 배경: 부수 텍스트(연한 회색)가 잘 안 보이므로 강한 색으로 전환
  const isDarkHexBg = isCustomHex && !isLightColor(res.highlight_color!);
  const subtleText = isDarkHexBg ? 'text-[#191F28] dark:text-white' : 'text-[#8B95A1] dark:text-[#4E5968]';
  const naverRoomText = isDarkHexBg ? 'text-[#191F28] dark:text-white' : 'text-[#8B95A1] dark:text-[#8B95A1]';
  const cellText = isCancelled ? 'text-[#F04452] line-through opacity-60' : hasCustomText ? 'text-inherit' : 'text-[#191F28] dark:text-white';

  return (
    <div
      key={res.id}
      className={`group/guest flex items-center ${showGrip && !isCancelled ? '' : 'pl-10'} transition-colors duration-150 ${isDragging ? 'opacity-40' : ''} ${
        isCancelled
          ? 'bg-[#FFEBEE] dark:bg-[#F04452]/10'
          : isSelected
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/15 ring-1 ring-inset ring-[#3182F6]/30'
            : isCustomHex
              ? `${getCustomTextClass(res.highlight_color!)} hover:brightness-[0.97] dark:hover:brightness-110`
              : highlightStyle
                ? `${highlightStyle.bg} ${highlightStyle.hover} ${highlightStyle.text || ''}`
                : longStay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15 hover:bg-[#FFE4CC] dark:hover:bg-[#FF9500]/20' : 'hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/8'
      } cursor-pointer`}
      style={{ height: ROOM_ROW_HEIGHT, ...(isCustomHex && !isSelected ? getCustomBgStyle(res.highlight_color!, isDarkMode) : {}) }}
      onContextMenu={(e) => {
        if (isCancelled) return;
        // 편집 중 InlineInput input이 활성이면 컨텍스트 메뉴 차단
        if (document.activeElement instanceof HTMLInputElement) return;
        onGuestContextMenu(e, res.id, zone);
      }}
      onTouchStart={(e) => {
        if (isCancelled) return;
        const target = e.target as HTMLElement;
        if (target.closest('input, textarea, button, a, [role="button"], [data-interactive]')) return;
        longPressFiredRef.current = false;
        const t = e.touches[0];
        const x = t.clientX;
        const y = t.clientY;
        if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
        longPressTimerRef.current = setTimeout(() => {
          longPressFiredRef.current = true;
          longPressTimerRef.current = null;
          onGuestContextMenu(
            { preventDefault: () => {}, stopPropagation: () => {}, clientX: x, clientY: y } as React.MouseEvent,
            res.id,
            zone,
          );
          // 안전망: 1초 후 자동 리셋 (touchend 가 어떤 이유로 발화 못 했을 때)
          setTimeout(() => { longPressFiredRef.current = false; }, 1000);
        }, 500);
      }}
      onTouchMove={() => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
      }}
      onTouchEnd={(e) => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
        // long-press 발화 시 default action(합성 mouse/click) 차단 — backdrop·document 의 close 트리거 방지.
        if (longPressFiredRef.current) {
          e.preventDefault();
        }
      }}
      onTouchCancel={() => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
      }}
      onClick={(e: React.MouseEvent) => {
        // Step #06b: selection 시스템 제거. long-press 합성 click 만 가드 (컨텍스트 메뉴 직후 의도치 않은 클릭 차단).
        if (longPressFiredRef.current) {
          longPressFiredRef.current = false;
          e.stopPropagation();
        }
      }}
    >
      {showGrip && !isCancelled && (
        <div
          ref={setNodeRef}
          {...attributes}
          {...listeners}
          className={`flex items-center justify-center w-10 px-0.5 flex-shrink-0 cursor-grab active:cursor-grabbing touch-none text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
            isSelected
              ? 'text-[#3182F6] dark:text-[#3182F6]'
              : longStay ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
          }`}
        >
          {/* Step #06a: 모바일도 PC 와 동일하게 GripVertical 사용 (drag 핸들 명시). */}
          <GripVertical size={18} strokeWidth={1.5} />
        </div>
      )}
      <div className="flex-1 grid items-center" style={{ gridTemplateColumns: GUEST_COLS }}>
        <div className="overflow-hidden px-1.5 flex items-center gap-0.5">
          <span className="flex items-center gap-1 min-w-0">
            <InlineInput value={res.customer_name} field="customer_name" resId={res.id} onSave={handleFieldSave} className={`font-medium ${cellText}`} placeholder="이름" autoFocus={res.id === quickAddedId} disabled={isCancelled} compact onActivate={cancelDeselect} singleClick />
            {formatGuestSuffix(res) && (
              <span className={`flex-shrink-0 text-caption ${subtleText}`}>{formatGuestSuffix(res)}</span>
            )}
            {res.has_unstable_booking && <span className="inline-block h-[6px] w-[6px] rounded-full bg-[#7B61FF] flex-shrink-0" title="언스테이블 파티 예약 확인" />}
          </span>
        </div>
        <div className="overflow-hidden px-1.5">
          <InlineInput value={res.phone} field="phone" resId={res.id} onSave={handleFieldSave} className={`${cellText} tabular-nums`} placeholder="연락처" onActivate={cancelDeselect} singleClick />
        </div>
        <div className="overflow-hidden text-center px-1.5">
          <InlineInput value={res.party_type || ''} field="party_type" resId={res.id} onSave={handleFieldSave} className={`${cellText} font-medium text-center`} placeholder="-" onActivate={cancelDeselect} singleClick />
        </div>
        <div className="overflow-hidden text-center px-1.5">
          <InlineInput value={genderPeople} field="genderPeople" resId={res.id} onSave={handleFieldSave} className={`${cellText} font-medium text-center`} placeholder="-" onActivate={cancelDeselect} singleClick />
        </div>
        <div className={`overflow-hidden truncate text-body text-center px-1.5 ${naverRoomText}`}>{res.naver_room_type || <span className="text-[#B0B8C1] dark:text-[#4E5968]">-</span>}</div>
        <div className="overflow-hidden px-1.5">
          {isCancelled && res.cancelled_at ? (
            <span className="text-caption text-[#F04452]">
              {new Date(normalizeUtcString(res.cancelled_at)).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })} 취소
            </span>
          ) : (
            <InlineInput value={res.notes || ''} field="notes" resId={res.id} onSave={handleFieldSave} className={cellText} placeholder="" onActivate={cancelDeselect} singleClick />
          )}
        </div>
        <div className="overflow-visible px-1.5">
          <SmsCell reservation={res} templateLabels={templateLabels} selectedDate={selectedDate.format('YYYY-MM-DD')} onToggle={handleSmsToggle} onAssign={handleSmsAssign} onRemove={handleSmsRemove} />
        </div>
      </div>
    </div>
  );
}
