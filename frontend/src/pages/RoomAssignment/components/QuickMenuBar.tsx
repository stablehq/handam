import { createPortal } from 'react-dom';
import { BedDouble, UserRoundPlus, Undo2, Phone, Trash2, Menu, X } from 'lucide-react';
import { Tooltip } from '@/components/ui/tooltip';
import { Spinner } from '@/components/ui/spinner';
import type { Reservation } from '../types';

interface QuickMenuBarProps {
  // 자동 배정
  autoAssigning: boolean;
  onAutoAssign: () => void;
  // 파티 게스트 추가
  onPartyAdd: () => void;
  // 되돌리기
  canUndo: boolean;
  onUndo: () => void;
  // 모바일: InlineInput 활성화로 지정된 "활성 게스트". null 이면 추가 버튼 미노출.
  activeGuest?: Reservation | null;
  onActiveClear?: () => void;
  onActiveCall?: (g: Reservation) => void;
  onActiveDelete?: (g: Reservation) => void;
  onActiveContext?: (g: Reservation, e: React.MouseEvent) => void;
}

/**
 * 객실 배정 페이지 하단 고정 Quick Menu.
 *
 * Step #06c (2026-05-20): 모바일 selection 기반 버튼 제거.
 * 재도입 (2026-05-21): 모바일 InlineInput 활성화 → activeGuest 지정 시 3 버튼
 * (전화 / 삭제 / 컨텍스트 메뉴) + 닫기(X) 표시. selectedGuestIds 와 무관.
 *
 * createPortal 로 document.body 직속 렌더 + transform 없는 중앙정렬.
 */
export function QuickMenuBar({
  autoAssigning,
  onAutoAssign,
  onPartyAdd,
  canUndo,
  onUndo,
  activeGuest,
  onActiveClear,
  onActiveCall,
  onActiveDelete,
  onActiveContext,
}: QuickMenuBarProps) {
  const showActive = !!activeGuest;

  return createPortal(
    <div className="fixed bottom-4 left-0 right-0 z-50 flex justify-center pointer-events-none">
      <div className="rounded-2xl shadow-lg bg-white dark:bg-[#1E1E24] border border-[#E5E8EB] dark:border-gray-800 px-4 py-2.5 pointer-events-auto">
        <div className="flex items-center gap-3">
          {showActive && activeGuest ? (
            // 활성 모드: 전화 / 삭제 / 컨텍스트 / 닫기 (모바일 input 활성 시 노출)
            <>
              {/* 액션 버튼 3종: onMouseDown preventDefault 로 input focus 유지 →
                  blur 발생 안 함 → onInputDeactivate 안 불려 activeGuest 가 살아있는 상태로 click 처리. */}
              <Tooltip content="선택한 게스트에게 전화" placement="top">
                <div className="inline-block">
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => onActiveCall?.(activeGuest)}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-[#00C9A7]/10 text-[#00C9A7] border border-[#00C9A7]/20 hover:bg-[#00C9A7]/20 active:bg-[#00C9A7]/30 transition-colors cursor-pointer"
                  >
                    <Phone className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="선택한 게스트 삭제" placement="top">
                <div className="inline-block">
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => onActiveDelete?.(activeGuest)}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-[#F04452]/10 text-[#F04452] border border-[#F04452]/20 hover:bg-[#F04452]/20 active:bg-[#F04452]/30 transition-colors cursor-pointer"
                  >
                    <Trash2 className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="컨텍스트 메뉴" placement="top">
                <div className="inline-block">
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => onActiveContext?.(activeGuest, e)}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] transition-colors cursor-pointer"
                  >
                    <Menu className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="닫기" placement="top">
                <div className="inline-block">
                  <button
                    onClick={onActiveClear}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#B0B8C1] dark:text-[#4E5968] hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] transition-colors cursor-pointer"
                  >
                    <X className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
            </>
          ) : (
            // 기본 모드: 자동 배정 / 파티 추가 / 되돌리기 (라벨 포함)
            <>
              <span className="text-[9px] font-bold tracking-widest leading-tight text-[#B0B8C1] dark:text-[#4E5968]">QUICK<br/>MENU</span>
              <Tooltip content={autoAssigning ? '배정 중...' : '객실 자동 배정'} placement="top">
                <div className="inline-block">
                  <button
                    onClick={onAutoAssign}
                    disabled={autoAssigning}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-[#3182F6] text-white hover:bg-[#1B64DA] active:bg-[#1554B5] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    {autoAssigning ? <Spinner size="sm" /> : <BedDouble className="h-[18px] w-[18px]" />}
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="파티 게스트 추가" placement="top">
                <div className="inline-block">
                  <button
                    onClick={onPartyAdd}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] transition-colors cursor-pointer"
                  >
                    <UserRoundPlus className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="되돌리기 (Ctrl+Z)" placement="top">
                <div className="inline-block">
                  <button
                    onClick={onUndo}
                    disabled={!canUndo}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <Undo2 className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
