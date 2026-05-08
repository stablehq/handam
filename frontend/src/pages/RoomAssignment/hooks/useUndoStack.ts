import { useCallback, useRef, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { reservationsAPI } from '../../../services/api';

declare global {
  interface Window {
    __diagAction?: string;
  }
}

export interface UndoEntry {
  resId: number;
  prevRoomId: number | null;
  prevRoomNumber: string | null;
  prevSection: string | null;
  date: string;
  customerName: string;
  /** 되돌릴 때 동일 범위로 복원 (원본 apply_subsequent 보존) */
  applySubsequent?: boolean;
  /** 그룹 이동 여부 */
  applyGroup?: boolean;
  /** 이동했던 방 (= 밀려난 사람의 원래 방) */
  movedToRoomId?: number | null;
  /** 밀려났던 예약자들 정보 — 복원 시 그 방으로 되돌려놓음 */
  pushedOut?: Array<{ reservation_id: number; customer_name: string | null; date: string }>;
}

const MAX_STACK = 20;

interface UseUndoStackProps {
  selectedDate: Dayjs;
  fetchReservations: (date: Dayjs) => void;
}

/**
 * 객실 배정 실행취소 스택.
 *
 * Phase I-1: undoStack + handleUndo + pushUndo 통합.
 * doAssignRoom (본체) 가 성공 시 pushUndo 호출.
 */
export function useUndoStack({ selectedDate, fetchReservations }: UseUndoStackProps) {
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const undoInProgress = useRef(false);

  const canUndo = undoStack.length > 0;

  const pushUndo = useCallback((entry: UndoEntry) => {
    setUndoStack(stack => [...stack.slice(-(MAX_STACK - 1)), entry]);
  }, []);

  const handleUndo = useCallback(() => {
    if (undoInProgress.current) return;
    if (undoStack.length === 0) return;
    undoInProgress.current = true;

    // updater 는 pure 하게 — slice 만 (StrictMode 가 두 번 호출해도 결과 동일).
    const last = undoStack[undoStack.length - 1];
    setUndoStack(prev => prev.slice(0, -1));

    // 부수 효과 (API + toast + refetch) 는 updater 밖에서 단 1회 실행.
    (async () => {
      try {
        window.__diagAction = 'undo_assign';
        // 1. 주 예약자 이전 방 복원 — 원본 범위(applySubsequent) + 그룹 여부 보존
        await reservationsAPI.assignRoom(last.resId, {
          room_id: last.prevRoomId,
          date: last.date,
          apply_subsequent: last.applySubsequent ?? false,
          apply_group: last.applyGroup ?? false,
        });
        // prevRoomId 가 null 일 때만 section 복원. 'room' 은 room_id 없으면 invalid → fallback.
        if (last.prevRoomId === null) {
          const safeSection = last.prevSection && last.prevSection !== 'room'
            ? last.prevSection
            : 'unassigned';
          await reservationsAPI.update(last.resId, { section: safeSection });
        }

        // 2. 밀려났던 예약자들을 원래 방(=주 예약자가 이동했던 방)으로 복원
        const pushedOut = last.pushedOut ?? [];
        if (pushedOut.length > 0 && last.movedToRoomId) {
          for (const p of pushedOut) {
            try {
              await reservationsAPI.assignRoom(p.reservation_id, {
                room_id: last.movedToRoomId,
                date: p.date,
                apply_subsequent: false,
              });
            } catch {
              toast.warning(`${p.customer_name ?? '예약자'} 복원 실패 — 수동 확인 필요`);
            }
          }
        }

        const pushedMsg = pushedOut.length > 0 ? ` (+ ${pushedOut.length}명 원복)` : '';
        toast.success(`되돌리기: ${last.customerName} → ${last.prevRoomId ? last.prevRoomNumber : '미배정'}${pushedMsg}`);
        fetchReservations(selectedDate);
      } catch {
        toast.error('되돌리기 실패');
      } finally {
        undoInProgress.current = false;
      }
    })();
  }, [undoStack, selectedDate, fetchReservations]);

  return { canUndo, pushUndo, handleUndo };
}
