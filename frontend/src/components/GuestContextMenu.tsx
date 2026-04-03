import React, { useRef, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Undo2, Music, Trash2, Link2, X, Zap, XCircle, CalendarPlus, CalendarMinus, Palette, ChevronRight, Calendar } from 'lucide-react';
import { GOOGLE_SHEETS_PALETTE } from '../lib/highlight-colors';

interface GuestContextMenuProps {
  position: { x: number; y: number };
  targetCount: number;
  currentSection: 'room' | 'unassigned' | 'party' | 'unstable';
  hasStayGroup: boolean;
  isUnstableCopy?: boolean;
  customColors?: string[];
  onMoveToPool: () => void;
  onMoveToParty: () => void;
  onDelete: () => void;
  onLinkStayGroup: () => void;
  onSetColor: (color: string | null) => void;
  onCopyToUnstable?: () => void;
  onRemoveFromUnstable?: () => void;
  onExtendStay?: () => void;
  onCancelExtendStay?: () => void;
  onChangeDates?: () => void;
  onClose: () => void;
}

export default function GuestContextMenu({
  position,
  targetCount,
  currentSection,
  hasStayGroup,
  isUnstableCopy,
  customColors = [],
  onMoveToPool,
  onMoveToParty,
  onDelete,
  onLinkStayGroup,
  onSetColor,
  onCopyToUnstable,
  onRemoveFromUnstable,
  onExtendStay,
  onCancelExtendStay,
  onChangeDates,
  onClose,
}: GuestContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [adjusted, setAdjusted] = useState<{ x: number; y: number }>(position);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const paletteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let x = position.x;
    let y = position.y;
    if (x + rect.width > vw - 8) x = vw - rect.width - 8;
    if (y + rect.height > vh - 8) y = vh - rect.height - 8;
    if (x < 8) x = 8;
    if (y < 8) y = 8;
    setAdjusted({ x, y });
  }, [position]);

  const plural = targetCount > 1 ? ` (${targetCount}명)` : '';

  const items: { icon: React.ReactNode; label: string; onClick: () => void; disabled: boolean; danger?: boolean }[] = [
    {
      icon: <Undo2 className="h-4 w-4" />,
      label: `미배정으로 이동${plural}`,
      onClick: onMoveToPool,
      disabled: currentSection === 'unassigned',
    },
    {
      icon: <Music className="h-4 w-4" />,
      label: `파티만으로 이동${plural}`,
      onClick: onMoveToParty,
      disabled: currentSection === 'party',
    },
  ];

  if (onCancelExtendStay) {
    items.push({
      icon: <CalendarMinus className="h-4 w-4" />,
      label: '수동연박 취소',
      onClick: onCancelExtendStay,
      disabled: false,
      danger: true,
    });
  } else if (onExtendStay) {
    items.push({
      icon: <CalendarPlus className="h-4 w-4" />,
      label: '내일 연박추가',
      onClick: onExtendStay,
      disabled: false,
    });
  }

  items.push({
    icon: <Link2 className="h-4 w-4" />,
    label: hasStayGroup ? '연박 해제' : '연박 묶기',
    onClick: onLinkStayGroup,
    disabled: false,
  });

  if (onChangeDates) {
    items.push({
      icon: <Calendar className="h-4 w-4" />,
      label: '예약 날짜 변경',
      onClick: onChangeDates,
      disabled: false,
    });
  }

  // 언스테이블 복사/제거 항목
  if (isUnstableCopy && onRemoveFromUnstable) {
    // 언스테이블 행의 복사본 → "제거"만 보임
    items.length = 0; // 기존 항목 제거 (복사본에는 이동/연박 불필요)
    items.push({
      icon: <XCircle className="h-4 w-4" />,
      label: '언스테이블 복사본 제거',
      onClick: onRemoveFromUnstable,
      disabled: false,
    });
  } else if (currentSection !== 'unstable' && onRemoveFromUnstable) {
    // 상단 예약자에서 이미 복사됨 → "언스테이블 복사본 제거" 표시
    items.push({
      icon: <XCircle className="h-4 w-4" />,
      label: '언스테이블 복사본 제거',
      onClick: onRemoveFromUnstable,
      disabled: false,
    });
  } else if (currentSection !== 'unstable' && onCopyToUnstable) {
    // 객실/미배정/파티만 → "언스테이블에 복사" 추가
    items.push({
      icon: <Zap className="h-4 w-4" />,
      label: `언스테이블에 복사${plural}`,
      onClick: onCopyToUnstable,
      disabled: false,
    });
  }

  return createPortal(
    <div
      ref={menuRef}
      style={{ position: 'fixed', left: adjusted.x, top: adjusted.y, zIndex: 10000 }}
      className="w-48 rounded-xl border border-[#E5E8EB] dark:border-gray-800 bg-white dark:bg-[#1E1E24] shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100"
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((item, i) => (
        <button
          key={i}
          onClick={(e) => { e.stopPropagation(); if (!item.disabled) item.onClick(); }}
          disabled={item.disabled}
          className={`w-full px-3 py-2 text-body flex items-center gap-2 transition-colors ${
            item.disabled
              ? 'text-[#B0B8C1] dark:text-[#4E5968] cursor-not-allowed'
              : item.danger
                ? 'text-[#F04452] hover:bg-[#FFF0F0] dark:hover:bg-[#F04452]/10 cursor-pointer'
                : 'text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer'
          }`}
        >
          {item.icon}
          {item.label}
        </button>
      ))}

      <div className="border-t border-[#E5E8EB] dark:border-gray-800 my-1" />

      {/* Color preset submenu trigger */}
      <div
        className="relative"
        onMouseEnter={() => { if (paletteTimerRef.current) clearTimeout(paletteTimerRef.current); setPaletteOpen(true); }}
        onMouseLeave={() => { paletteTimerRef.current = setTimeout(() => setPaletteOpen(false), 200); }}
      >
        <button
          className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer transition-colors"
          onClick={(e) => { e.stopPropagation(); setPaletteOpen(!paletteOpen); }}
        >
          <Palette className="h-4 w-4" />
          <span className="flex-1 text-left">컬러 프리셋</span>
          <ChevronRight className="h-3.5 w-3.5 text-[#8B95A1]" />
        </button>

        {/* Palette submenu */}
        {paletteOpen && (
          <div
            className="absolute left-full top-0 ml-1 p-2 rounded-xl border border-[#E5E8EB] dark:border-gray-800 bg-white dark:bg-[#1E1E24] shadow-lg z-[10001] animate-in fade-in zoom-in-95 duration-100"
            style={{ minWidth: '228px' }}
            onMouseEnter={() => { if (paletteTimerRef.current) clearTimeout(paletteTimerRef.current); }}
            onMouseLeave={() => { paletteTimerRef.current = setTimeout(() => setPaletteOpen(false), 200); }}
          >
            <div className="flex flex-col gap-0.5">
              {GOOGLE_SHEETS_PALETTE.map((row, ri) => (
                <div key={ri} className="flex gap-0.5">
                  {row.map((hex) => (
                    <button
                      key={hex}
                      title={hex}
                      onClick={(e) => { e.stopPropagation(); onSetColor(hex); }}
                      className="w-5 h-5 rounded-sm border border-gray-200 dark:border-gray-700 cursor-pointer hover:scale-125 hover:z-10 transition-transform flex-shrink-0"
                      style={{ backgroundColor: hex }}
                    />
                  ))}
                </div>
              ))}
            </div>
            <div className="border-t border-[#E5E8EB] dark:border-gray-800 mt-2 pt-1.5 flex justify-center">
              <button
                title="색상 해제"
                onClick={(e) => { e.stopPropagation(); onSetColor(null); }}
                className="text-caption text-[#8B95A1] hover:text-[#191F28] dark:hover:text-white cursor-pointer transition-colors"
              >
                색상 해제
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Quick colors */}
      <div className="px-3 py-1.5 flex flex-wrap items-center gap-1.5">
        {customColors.length > 0 ? (
          customColors.map((hex) => (
            <button
              key={hex}
              title={hex}
              onClick={(e) => { e.stopPropagation(); onSetColor(hex); }}
              className="w-5 h-5 rounded-full border border-gray-300 dark:border-gray-600 cursor-pointer hover:scale-110 transition-transform flex-shrink-0"
              style={{ backgroundColor: hex }}
            />
          ))
        ) : (
          <span className="text-caption text-[#B0B8C1] dark:text-[#4E5968]">테이블 설정에서 퀵 컬러를 추가하세요</span>
        )}
        <button
          title="색상 해제"
          onClick={(e) => { e.stopPropagation(); onSetColor(null); }}
          className="w-5 h-5 rounded-full border border-dashed border-gray-300 dark:border-gray-600 cursor-pointer hover:scale-110 transition-transform flex items-center justify-center flex-shrink-0"
        >
          <X className="h-2.5 w-2.5 text-[#8B95A1]" />
        </button>
      </div>

      {!isUnstableCopy && (
        <>
          <div className="border-t border-[#E5E8EB] dark:border-gray-800 my-1" />

          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#F04452] hover:bg-[#FFF0F0] dark:hover:bg-[#F04452]/10 cursor-pointer transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            게스트 삭제{plural}
          </button>
        </>
      )}
    </div>,
    document.body,
  );
}
