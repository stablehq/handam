import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { roomsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';

declare global {
  interface Window {
    __diagAction?: string;
  }
}

/**
 * 객실 자동 배정 흐름(확인 모달 + API 호출 + 결과 토스트 + 새로고침)을 캡슐화.
 *
 * Phase B-1: RoomAssignment.tsx 의 autoAssignConfirm/autoAssigning/handleAutoAssign 분리.
 * Phase 3b: roomsAPI.autoAssign → useMutation.
 */
export function useAutoAssign(selectedDate: Dayjs, refetch: () => void) {
  const qc = useQueryClient();
  const [autoAssignConfirm, setAutoAssignConfirm] = useState(false);

  const dateStr = selectedDate.format('YYYY-MM-DD');
  const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

  const mutation = useMutation({
    mutationFn: (ds: string) => {
      window.__diagAction = 'auto_assign_button';
      return roomsAPI.autoAssign(ds);
    },
    onSuccess: (res) => {
      const today = res.data.today;
      toast.success(`객실 자동 배정 완료: ${today.assigned}건 배정`);
      refetch();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || '객실 자동 배정에 실패했습니다.');
    },
    onSettled: () => {
      setAutoAssignConfirm(false);
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(dateStr) });
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(nextDateStr) });
      qc.invalidateQueries({ queryKey: queryKeys.rooms.list() });
    },
  });

  const handleAutoAssign = useCallback(() => {
    mutation.mutate(dateStr);
  }, [mutation, dateStr]);

  const openConfirm = useCallback(() => setAutoAssignConfirm(true), []);
  const closeConfirm = useCallback(() => setAutoAssignConfirm(false), []);

  return {
    autoAssignConfirm,
    autoAssigning: mutation.isPending,
    handleAutoAssign,
    openConfirm,
    closeConfirm,
  };
}
