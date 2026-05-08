import { useCallback, useState } from 'react';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { reservationsAPI, stayGroupAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
import type { Reservation } from '../types';

interface ChainEntry {
  id: number;
  customer_name: string;
  phone: string;
  check_in_date: string;
  check_out_date: string;
  stay_group_id?: string | null;
}

// 단일날짜(ci===co) 예약은 ci+1, 연박은 co 사용 — chain next 슬롯 계산.
const nextDateOf = (r: { check_in_date: string; check_out_date?: string | null }) =>
  (r.check_out_date && r.check_out_date !== r.check_in_date)
    ? r.check_out_date
    : dayjs(r.check_in_date).add(1, 'day').format('YYYY-MM-DD');

interface UseStayGroupProps {
  reservations: Reservation[];
}

/**
 * 연박 그룹 만들기 마법사 (모달 + 체인 + 후보 로드 + 백엔드 link/unlink).
 *
 * Phase B-4: RoomAssignment.tsx 의 7개 useState + 2 helper + 5 handler 통합.
 * Phase 3b: link/unlink → useMutation. window.location.reload() 제거.
 *           broad invalidation: queryKeys.reservations.all() + rooms.groups().
 */
export function useStayGroup({ reservations }: UseStayGroupProps) {
  const qc = useQueryClient();
  const [show, setShow] = useState(false);
  const [chain, setChain] = useState<ChainEntry[]>([]);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [direction, setDirection] = useState<'left' | 'right'>('right');

  const invalidateBroad = useCallback(() => {
    qc.invalidateQueries({ queryKey: queryKeys.reservations.all() });
    qc.invalidateQueries({ queryKey: queryKeys.rooms.groups() });
  }, [qc]);

  const loadReservationsForDate = useCallback(async (date: string) => {
    setLoading(true);
    try {
      const res = await reservationsAPI.getAll({ date });
      setCandidates(res.data.items || res.data || []);
    } catch {
      toast.error('예약자 목록을 불러올 수 없습니다');
    } finally {
      setLoading(false);
    }
  }, []);

  const open = useCallback((resId: number) => {
    const res = reservations.find(r => r.id === resId);
    if (!res) return;
    const initialEntry: ChainEntry = {
      id: res.id,
      customer_name: res.customer_name,
      phone: res.phone,
      check_in_date: res.check_in_date,
      check_out_date: res.check_out_date || res.check_in_date,
      stay_group_id: res.stay_group_id,
    };
    setShow(true);
    setChain([initialEntry]);
    setSelectedId(null);
    setDirection('right');
    loadReservationsForDate(nextDateOf(res));
  }, [reservations, loadReservationsForDate]);

  const close = useCallback(() => setShow(false), []);

  const addMore = useCallback(() => {
    const selected = candidates.find((r: any) => r.id === selectedId);
    if (!selected) return;

    const entry: ChainEntry = {
      id: selected.id,
      customer_name: selected.customer_name,
      phone: selected.phone,
      check_in_date: selected.check_in_date,
      check_out_date: selected.check_out_date || selected.check_in_date,
      stay_group_id: selected.stay_group_id,
    };

    if (direction === 'left') {
      const firstInChain = chain[0];
      if (firstInChain && nextDateOf(selected) !== firstInChain.check_in_date) {
        toast.error('체크아웃 날짜가 다음 예약의 체크인과 일치하지 않습니다');
        return;
      }
      setChain([entry, ...chain]);
      setSelectedId(null);
      const prevDate = dayjs(selected.check_in_date).subtract(1, 'day').format('YYYY-MM-DD');
      loadReservationsForDate(prevDate);
    } else {
      const lastInChain = chain[chain.length - 1];
      if (lastInChain && selected.check_in_date !== nextDateOf(lastInChain)) {
        toast.error('체크인 날짜가 이전 예약의 체크아웃과 일치하지 않습니다');
        return;
      }
      setChain([...chain, entry]);
      setSelectedId(null);
      loadReservationsForDate(nextDateOf(selected));
    }
  }, [candidates, selectedId, direction, chain, loadReservationsForDate]);

  const changeDirection = useCallback((dir: 'left' | 'right') => {
    setDirection(dir);
    setSelectedId(null);
    if (dir === 'left') {
      const first = chain[0];
      if (first) {
        const prevDate = dayjs(first.check_in_date).subtract(1, 'day').format('YYYY-MM-DD');
        loadReservationsForDate(prevDate);
      }
    } else {
      const last = chain[chain.length - 1];
      if (last) {
        loadReservationsForDate(nextDateOf(last));
      }
    }
  }, [chain, loadReservationsForDate]);

  // ===== link mutation =====
  const linkMutation = useMutation({
    mutationFn: ({ anchorId, ids }: { anchorId: number; ids: number[] }) =>
      stayGroupAPI.link(anchorId, ids),
    onSuccess: (_, { ids }) => {
      toast.success(`연박 그룹 생성 완료 (${ids.length}건)`);
      setShow(false);
      invalidateBroad();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || '연박 묶기에 실패했습니다');
    },
  });

  // ===== unlink mutation =====
  const unlinkMutation = useMutation({
    mutationFn: (reservationId: number) => stayGroupAPI.unlink(reservationId),
    onSuccess: () => {
      toast.success('연박 그룹에서 해제되었습니다');
      invalidateBroad();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || '연박 해제에 실패했습니다');
    },
  });

  const complete = useCallback(() => {
    if (chain.length < 2) {
      toast.error('최소 2개의 예약을 선택해야 합니다');
      return;
    }
    const ids = chain.map(c => c.id);
    linkMutation.mutate({ anchorId: ids[0], ids });
  }, [chain, linkMutation]);

  const unlink = useCallback((reservationId: number) => {
    if (!confirm('이 예약을 연박 그룹에서 해제하시겠습니까?\nSMS 스케줄이 변경될 수 있습니다.')) return;
    unlinkMutation.mutate(reservationId);
  }, [unlinkMutation]);

  return {
    show, chain, candidates, selectedId, loading,
    linking: linkMutation.isPending,
    direction,
    setSelectedId,
    open, close,
    addMore, changeDirection, complete, unlink,
  };
}
