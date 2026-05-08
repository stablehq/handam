import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { roomsAPI } from '../../../services/api';

declare global {
  interface Window {
    __diagAction?: string;
  }
}

/**
 * 객실 자동 배정 흐름(확인 모달 + API 호출 + 결과 토스트 + 새로고침)을 캡슐화.
 *
 * Phase B-1: RoomAssignment.tsx 의 autoAssignConfirm/autoAssigning/handleAutoAssign 분리.
 * `refetch` 는 부모에서 selectedDate 를 묶어 인자 없이 호출 가능한 형태로 넘긴다.
 */
export function useAutoAssign(selectedDate: Dayjs, refetch: () => void) {
  const [autoAssignConfirm, setAutoAssignConfirm] = useState(false);
  const [autoAssigning, setAutoAssigning] = useState(false);

  const handleAutoAssign = useCallback(async () => {
    setAutoAssigning(true);
    try {
      const dateStr = selectedDate.format('YYYY-MM-DD');
      // DIAG_BLOCK_START
      window.__diagAction = 'auto_assign_button';
      // DIAG_BLOCK_END
      const res = await roomsAPI.autoAssign(dateStr);
      const today = res.data.today;
      toast.success(`객실 자동 배정 완료: ${today.assigned}건 배정`);
      refetch();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '객실 자동 배정에 실패했습니다.');
    } finally {
      setAutoAssigning(false);
      setAutoAssignConfirm(false);
    }
  }, [selectedDate, refetch]);

  const openConfirm = useCallback(() => setAutoAssignConfirm(true), []);
  const closeConfirm = useCallback(() => setAutoAssignConfirm(false), []);

  return {
    autoAssignConfirm,
    autoAssigning,
    handleAutoAssign,
    openConfirm,
    closeConfirm,
  };
}
